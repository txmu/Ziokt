"""Tests for ZKT reputation and credit scoring engine.

ZKT is a non-monetary reputation/merit credit system, not a financial token or cryptocurrency.
It rewards infrastructure providers for delivering Shadow6 Cores (especially urgent/in-demand cores)
and Corium application services with freely configurable acquisition rules.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ziokt._zkt_runtime import (
    DEFAULT_REPUTATION_POLICY,
    zkt_validate_policy,
    zkt_validate_claim,
    zkt_calculate_points,
    zkt_record_claim,
    zkt_status,
    zkt_account,
    zkt_tier,
    zkt_set_policy,
    ProtocolError,
)


class ZKTReputationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "chain.db"
        self.operator1 = "a" * 64
        self.operator2 = "b" * 64

    def sample_claim(self, **kwargs):
        base = {
            "schema": "ziokt.zkt-service-claim.v1",
            "operator": self.operator1,
            "provider": "shadow6",
            "service_kind": "core",
            "service_name": "Core-Rust",
            "units_delivered": 5,
            "evidence_digest": "sha256:" + hashlib.sha256(b"evidence-1").hexdigest(),
            "epoch": 1,
            "nonce": "nonce-001",
        }
        base.update(kwargs)
        return base

    def test_default_reputation_policy_structure(self):
        policy = zkt_validate_policy(DEFAULT_REPUTATION_POLICY)
        self.assertEqual(policy["schema"], "ziokt.zkt-reputation-policy.v1")
        self.assertIn("Core-Rust", policy["urgent_cores"])
        self.assertIn("Core-Go", policy["urgent_cores"])
        self.assertEqual(policy["urgent_core_multiplier"], 3)
        self.assertEqual(policy["standard_core_multiplier"], 1)
        self.assertIn("wiki", policy["application_services"])
        self.assertIn("recovery", policy["application_services"])

    def test_urgent_core_rewards_higher_points_than_standard(self):
        policy = DEFAULT_REPUTATION_POLICY
        urgent_claim = self.sample_claim(service_name="Core-Rust", units_delivered=10)
        standard_claim = self.sample_claim(service_name="Core-Common", units_delivered=10)

        urgent_pts = zkt_calculate_points(policy, urgent_claim)
        standard_pts = zkt_calculate_points(policy, standard_claim)

        # Urgent core has 3x multiplier
        self.assertEqual(urgent_pts, 10 * 10 * 3)
        self.assertEqual(standard_pts, 10 * 10 * 1)
        self.assertEqual(urgent_pts, standard_pts * 3)

    def test_corium_application_service_points(self):
        policy = DEFAULT_REPUTATION_POLICY
        wiki_claim = self.sample_claim(
            provider="corium",
            service_kind="application",
            service_name="wiki",
            units_delivered=4,
        )
        recovery_claim = self.sample_claim(
            provider="corium",
            service_kind="application",
            service_name="recovery",
            units_delivered=4,
        )

        wiki_pts = zkt_calculate_points(policy, wiki_claim)
        recovery_pts = zkt_calculate_points(policy, recovery_claim)

        self.assertEqual(wiki_pts, 15 * 4)
        self.assertEqual(recovery_pts, 25 * 4)

    def test_configurable_policy_and_custom_weights(self):
        custom_policy = {
            "schema": "ziokt.zkt-reputation-policy.v1",
            "policy_id": "custom-community-policy",
            "version": 2,
            "network_id": "test-net",
            "base_points_per_unit": 20,
            "urgent_cores": ["Core-Nim", "Core-Scheme"],
            "urgent_core_multiplier": 5,
            "standard_core_multiplier": 1,
            "application_services": {
                "wiki": 50,
                "custom_app": 100,
            },
            "max_points_per_claim": 10000,
        }
        zkt_set_policy(self.db_path, custom_policy)

        status = zkt_status(self.db_path)
        self.assertEqual(status["policy_id"], "custom-community-policy")
        self.assertEqual(status["urgent_core_multiplier"], 5)
        self.assertEqual(status["urgent_cores"], ["Core-Nim", "Core-Scheme"])

        claim = self.sample_claim(
            service_name="Core-Nim",
            units_delivered=2,
            evidence_digest="sha256:" + hashlib.sha256(b"custom").hexdigest(),
        )
        awarded = zkt_record_claim(self.db_path, claim)
        # 20 base * 2 units * 5 multiplier = 200
        self.assertEqual(awarded["points_awarded"], 200)

    def test_record_claim_and_duplicate_suppression(self):
        claim1 = self.sample_claim(
            evidence_digest="sha256:" + hashlib.sha256(b"work-1").hexdigest(),
            nonce="nonce-1",
        )
        result1 = zkt_record_claim(self.db_path, claim1)
        self.assertEqual(result1["status"], "awarded")
        self.assertEqual(result1["points_awarded"], 150)
        self.assertEqual(result1["total_reputation"], 150)

        # Attempt to record identical claim must be rejected
        with self.assertRaises(ProtocolError) as ctx:
            zkt_record_claim(self.db_path, claim1)
        self.assertEqual(ctx.exception.code, "ZKT_DUPLICATE_CLAIM")

        # Attempt to re-use same nonce and epoch must be rejected
        replay_nonce = self.sample_claim(
            evidence_digest="sha256:" + hashlib.sha256(b"work-2").hexdigest(),
            nonce="nonce-1",
            epoch=1,
        )
        with self.assertRaises(ProtocolError) as ctx:
            zkt_record_claim(self.db_path, replay_nonce)
        self.assertEqual(ctx.exception.code, "ZKT_DUPLICATE_CLAIM")

    def test_tier_progression_with_cumulative_contributions(self):
        self.assertEqual(zkt_tier(0), "Contributor")
        self.assertEqual(zkt_tier(99), "Contributor")
        self.assertEqual(zkt_tier(100), "Reliable Provider")
        self.assertEqual(zkt_tier(399), "Reliable Provider")
        self.assertEqual(zkt_tier(400), "Core Guardian")
        self.assertEqual(zkt_tier(999), "Core Guardian")
        self.assertEqual(zkt_tier(1000), "Federation Pillar")

        # Record multiple verified contributions
        for i in range(4):
            claim = self.sample_claim(
                service_name="Core-Rust",
                units_delivered=10,  # 300 points each
                evidence_digest="sha256:" + hashlib.sha256(f"work-{i}".encode()).hexdigest(),
                nonce=f"nonce-{i}",
                epoch=i,
            )
            zkt_record_claim(self.db_path, claim)

        account = zkt_account(self.db_path, self.operator1)
        self.assertEqual(account["total_reputation"], 1200)
        self.assertEqual(account["shadow6_core_reputation"], 1200)
        self.assertEqual(account["corium_app_reputation"], 0)
        self.assertEqual(account["tier"], "Federation Pillar")
        self.assertEqual(account["claims_count"], 4)
        self.assertFalse(account["is_financial_token"])

    def test_status_and_account_views_are_strictly_non_financial(self):
        claim_s6 = self.sample_claim(
            provider="shadow6",
            service_kind="core",
            service_name="Core-Rust",
            units_delivered=5,
            evidence_digest="sha256:" + hashlib.sha256(b"s6").hexdigest(),
            nonce="n1",
        )
        claim_c108 = self.sample_claim(
            provider="corium",
            service_kind="application",
            service_name="wiki",
            units_delivered=2,
            evidence_digest="sha256:" + hashlib.sha256(b"c108").hexdigest(),
            nonce="n2",
        )
        zkt_record_claim(self.db_path, claim_s6)
        zkt_record_claim(self.db_path, claim_c108)

        status = zkt_status(self.db_path)
        self.assertFalse(status["is_financial_token"])
        self.assertEqual(status["reputation_type"], "merit_and_service_credit")
        self.assertEqual(status["active_operators_count"], 1)
        self.assertEqual(status["total_claims_recorded"], 2)
        # 150 (Core-Rust) + 30 (wiki) = 180
        self.assertEqual(status["total_reputation_awarded"], 180)

        account = zkt_account(self.db_path, self.operator1)
        self.assertFalse(account["is_financial_token"])
        self.assertEqual(account["total_reputation"], 180)
        self.assertEqual(account["shadow6_core_reputation"], 150)
        self.assertEqual(account["corium_app_reputation"], 30)
        self.assertEqual(account["tier"], "Reliable Provider")
        self.assertEqual(len(account["recent_claims"]), 2)


if __name__ == "__main__":
    unittest.main()


class ZKTGovernanceTests(unittest.TestCase):
    def setUp(self):
        import copy
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'ledger.db';self.keys=[Ed25519PrivateKey.generate() for _ in range(3)]
        self.public=[k.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex() for k in self.keys]
        self.policy=copy.deepcopy(DEFAULT_REPUTATION_POLICY)
        self.policy.update(network_id='test',governance={'authorities':dict(zip(self.public,['a','b','c'])),'threshold':2,'minimum_domains':2,'veto_threshold':2,'timelock_seconds':60,'voting_period_seconds':3600},anti_abuse={'max_claims_per_day':2,'max_points_per_day':500,'global_points_per_day':600,'max_epoch_age_days':1},service_limits={'Core-Rust':10},tiers=[{'name':'New','minimum':0},{'name':'Member','minimum':100}])
        zkt_set_policy(self.path,self.policy)

    def signed(self,payload,index=0):
        from ziokt.security import sign
        from cryptography.hazmat.primitives import serialization
        return sign(payload,self.keys[index].private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()),'Ziokt/zkt-governance/v1')

    def proposal(self):
        import copy
        from ziokt._zkt_runtime import _zkt_digest
        nxt=copy.deepcopy(self.policy);nxt['version']+=1;nxt['application_services']['network_relay']=7
        return {'operation':'propose','network_id':'test','base_policy':_zkt_digest(self.policy),'policy':nxt,'nonce':'1'*64,'created_at':100000,'activate_at':100060,'expires_at':101000}

    def test_signed_quorum_timelock_persistence_and_no_direct_bypass(self):
        from unittest.mock import patch
        from ziokt._zkt_runtime import zkt_governance
        with patch('ziokt._zkt_runtime.time.time',return_value=100000):
            pid=zkt_governance(self.path,'propose',self.signed(self.proposal()))['proposal']
            with self.assertRaises(ProtocolError):zkt_set_policy(self.path,self.proposal()['policy'])
            forged=self.signed(self.proposal());forged['payload']['nonce']='2'*64
            with self.assertRaises(ProtocolError):zkt_governance(self.path,'propose',forged)
            for i in range(2):
                ballot=self.signed({'operation':'vote','network_id':'test','proposal':pid,'approve':True},i)
                zkt_governance(self.path,'vote',ballot)
                with self.assertRaises(ProtocolError):zkt_governance(self.path,'vote',ballot)
            with self.assertRaises(ProtocolError):zkt_governance(self.path,'enact',{'proposal':pid})
        with patch('ziokt._zkt_runtime.time.time',return_value=100061):
            result=zkt_governance(self.path,'enact',{'proposal':pid});self.assertEqual(result['state'],'enacted')
            self.assertEqual(zkt_status(self.path)['policy']['application_services']['network_relay'],7)
            with self.assertRaises(ProtocolError):zkt_governance(self.path,'enact',{'proposal':pid})

    def test_cross_identity_evidence_budget_and_concurrent_claims(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        claim={'schema':'ziokt.zkt-service-claim.v1','operator':'a'*64,'provider':'shadow6','service_kind':'core','service_name':'Core-Rust','units_delivered':5,'evidence_digest':'sha256:'+'1'*64,'epoch':int(time.time())//86400,'nonce':'1'}
        def submit(value):
            try:return zkt_record_claim(self.path,value)['points_awarded']
            except ProtocolError as e:return e.code
        with ThreadPoolExecutor(4) as pool:results=list(pool.map(submit,[claim]*4))
        self.assertEqual(results.count(150),1);self.assertEqual(results.count('ZKT_DUPLICATE_CLAIM'),3)
        self.assertEqual(submit(claim|{'operator':'b'*64,'nonce':'2'}),'ZKT_DUPLICATE_CLAIM')
        self.assertEqual(submit(claim|{'evidence_digest':'sha256:'+'2'*64,'nonce':'2'}),150)
        self.assertEqual(submit(claim|{'evidence_digest':'sha256:'+'3'*64,'nonce':'3'}),'ZKT_RATE_LIMIT')
        self.assertEqual(zkt_account(self.path,'a'*64)['tier'],'Member')
        with self.assertRaises(ProtocolError):zkt_record_claim(self.path,claim,DEFAULT_REPUTATION_POLICY)

    def test_veto_and_expired_proposals_fail_closed(self):
        from unittest.mock import patch
        from ziokt._zkt_runtime import zkt_governance
        with patch('ziokt._zkt_runtime.time.time',return_value=100000):
            pid=zkt_governance(self.path,'propose',self.signed(self.proposal()))['proposal']
            for i in range(2):result=zkt_governance(self.path,'vote',self.signed({'operation':'vote','network_id':'test','proposal':pid,'approve':False},i))
            self.assertEqual(result['state'],'vetoed')
        with patch('ziokt._zkt_runtime.time.time',return_value=101001):
            with self.assertRaises(ProtocolError):zkt_governance(self.path,'enact',{'proposal':pid})

    def test_service_observation_signatures_bind_policy_and_claim(self):
        import copy,time
        from ziokt._zkt_runtime import _zkt_digest
        from ziokt.security import sign
        from cryptography.hazmat.primitives import serialization
        policy=copy.deepcopy(self.policy);policy.pop('governance')
        policy['claim_attestors']={'authorities':self.policy['governance']['authorities'],'threshold':2,'minimum_domains':2}
        claim={'schema':'ziokt.zkt-service-claim.v1','operator':'a'*64,'provider':'corium','service_kind':'application','service_name':'wiki','units_delivered':1,'evidence_digest':'sha256:'+'9'*64,'epoch':int(time.time())//86400,'nonce':'9'}
        other=Path(self.temp.name)/'observed.db';zkt_set_policy(other,policy)
        with self.assertRaises(ProtocolError):zkt_record_claim(other,claim)
        payload={'operation':'claim','network_id':'test','policy_digest':_zkt_digest(policy),'claim':claim.copy()}
        witnesses=[sign(payload,k.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()),'Ziokt/zkt-service-observation/v1') for k in self.keys[:2]]
        with self.assertRaises(ProtocolError):zkt_record_claim(other,claim|{'units_delivered':2,'witnesses':witnesses})
        self.assertEqual(zkt_record_claim(other,claim|{'witnesses':witnesses})['points_awarded'],15)

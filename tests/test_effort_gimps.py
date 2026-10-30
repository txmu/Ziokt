import json
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import unittest

from test_native_integration import C
from ziokt.client import NativeClient
from ziokt.config import fingerprint
from ziokt.effort_gimps import GimpsPool
from ziokt.protocol import ProtocolError


class GimpsEffortTests(unittest.TestCase):
    def test_real_corium_independent_task_and_native_transaction(self):
        sys.path.insert(0,str(C));from test_core import Fixture
        fixture=Fixture();fixture.setUp();self.addCleanup(fixture.doCleanups)
        for path in fixture.root.rglob('*'):
            if path.is_dir():path.chmod(0o700)
        (fixture.etc/'identity.key').chmod(0o600)
        config=fixture.etc/'corix.conf';config.write_text('[ziokt]\nenabled=TRUE\nfederation_id=effort\nprovider_id=corium-local\nallow_mutations=TRUE\nallowed_operations=compute.submit\nallowed_resources=compute:gimps-effort\n');config.chmod(0o600)
        with sqlite3.connect(fixture.chain) as db:
            head,height=db.execute('SELECT hash,height FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
            db.execute("INSERT OR REPLACE INTO chain_state VALUES ('chain_info',?)",(head+'|'+str(height),))
            db.execute("INSERT INTO compute_engines(engine_id,pkg_id,description,compute_program_hash,verifier_script_hash,is_active) VALUES ('gimps-effort','corium/built-in-gimps','native','BUILT_IN','BUILT_IN',1)")
            db.execute("INSERT INTO problem_sets(set_id,engine_id,metadata,activation_height) VALUES ('effort-set','gimps-effort',?,0)",(json.dumps({'start_exponent':5,'end_exponent':7}),))
        client=NativeClient('effort',{'native_project':'corium','provider_id':'corium-local','root':str(C),'native_config':str(config),'entrypoint_digest':fingerprint(C/'corix_v108.sh'),'network_id':'default','state_root':str(fixture.root)})
        pool=GimpsPool(client,fixture.identity,fixture.root/'effort-gimps',expected_network='default');self.addCleanup(pool.close)
        job=pool.issue();self.assertEqual(job['engine_id'],'gimps-effort');self.assertEqual(job['exponent'],5)
        self.assertEqual(client.call('compute.challenge',{'engine':'gimps','exclude_exponents':[5]})['exponent'],7)
        with self.assertRaises(ProtocolError):client.call('compute.challenge',{'engine':'gimps','exclude_exponents':[True]})
        proof={'schema':'corium.gimps-proof.v2','exponent':5,'method':'lucas-lehmer','residue':'0','is_prime':True,'iterations':3}
        with self.assertRaises(ProtocolError):pool.submit(job['token'],dict(proof,residue='1'))
        receipt=pool.submit(job['token'],proof);self.assertTrue(receipt['accepted']);self.assertFalse(receipt['confirmed'])
        self.assertTrue(pool.submit(job['token'],proof)['duplicate'])
        with sqlite3.connect(fixture.chain) as db:
            rows=db.execute("SELECT data FROM transactions WHERE type='submit_math_proof'").fetchall()
            self.assertEqual(len(rows),1);payload=json.loads(rows[0][0]);self.assertEqual(payload['engine_id'],'gimps-effort');self.assertEqual(payload['proof_data'],proof)
        self.assertEqual(pool.issue()['exponent'],7)

    def test_no_engine_zero_fallback_when_gimps_has_no_tasks(self):
        class Chain:
            def call(self,method,args):
                self_args=(method,args)
                if self_args!=('compute.challenge',{'engine':'gimps'}):raise AssertionError(self_args)
                return {'schema':'corium.gimps-challenge.v1','available':False,'submitter_id':'a'*64,'network_id':'default','reason':'no-active-gimps-engine'}
        with tempfile.TemporaryDirectory() as directory:
            pool=GimpsPool(Chain(),'a'*64,Path(directory),expected_network='default')
            try:self.assertFalse(pool.issue()['available']);self.assertFalse(pool.jobs)
            finally:pool.close()

    def test_prp_proof_submission_and_content_fabric_export(self):
        sys.path.insert(0, str(C))
        from test_core import Fixture
        fixture = Fixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for path in fixture.root.rglob('*'):
            if path.is_dir():
                path.chmod(0o700)
        (fixture.etc / 'identity.key').chmod(0o600)
        config = fixture.etc / 'corix.conf'
        config.write_text('[ziokt]\nenabled=TRUE\nfederation_id=effort\nprovider_id=corium-local\nallow_mutations=TRUE\nallowed_operations=compute.submit\nallowed_resources=compute:gimps-effort\n')
        config.chmod(0o600)
        with sqlite3.connect(fixture.chain) as db:
            head, height = db.execute('SELECT hash,height FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
            db.execute("INSERT OR REPLACE INTO chain_state VALUES ('chain_info',?)", (head + '|' + str(height),))
            db.execute("INSERT INTO compute_engines(engine_id,pkg_id,description,compute_program_hash,verifier_script_hash,is_active) VALUES ('gimps-effort','corium/built-in-gimps','native','BUILT_IN','BUILT_IN',1)")
            db.execute("INSERT INTO problem_sets(set_id,engine_id,metadata,activation_height) VALUES ('effort-set','gimps-effort',?,0)", (json.dumps({'start_exponent': 7, 'end_exponent': 7}),))
        client = NativeClient('effort', {'native_project': 'corium', 'provider_id': 'corium-local', 'root': str(C), 'native_config': str(config), 'entrypoint_digest': fingerprint(C / 'corix_v108.sh'), 'network_id': 'default', 'state_root': str(fixture.root)})
        chunkstore = fixture.root / 'test-chunkstore'
        pool = GimpsPool(client, fixture.identity, fixture.root / 'effort-gimps', expected_network='default', chunkstore_dir=chunkstore)
        self.addCleanup(pool.close)

        job = pool.issue()
        self.assertEqual(job['engine_id'], 'gimps-effort')
        self.assertEqual(job['exponent'], 7)

        # Worker computes PRP test for p=7 (M_7 = 127 is prime, residue=126, res64=000000000000007E)
        if str(C) not in sys.path:
            sys.path.insert(0, str(C))
        import gimps_consensus as G
        generated = G.generate_prp_proof(7, base=3, depth=4)
        prp_proof = {
            'schema': 'corium.gimps-prp-proof.v1',
            'exponent': 7,
            'method': 'prp-fiat-shamir',
            'base': 3,
            'residue': '126',
            'res64': '000000000000007E',
            'is_prp': True,
            'prp_result': 'PRP',
            'is_prime': True,
            'iterations': 6,
            'proof_steps': generated['proof_steps'],
            'gerbicz_status': 'OK',
            'gerbicz_checkpoints': generated['gerbicz_checkpoints'],
            'gerbicz_check': generated['gerbicz_check']
        }
        # Strict prover-verifier separation: submission without proof_steps fails
        bad_proof = dict(prp_proof, proof_steps=[])
        with self.assertRaises(ProtocolError):
            pool.submit(job['token'], bad_proof)

        receipt = pool.submit(job['token'], prp_proof)
        self.assertTrue(receipt['accepted'])
        self.assertTrue(receipt['math_certified'])
        self.assertEqual(receipt['primenet_status'], 'local_staged_untransmitted')
        self.assertFalse(receipt['corium_settled'])
        self.assertIn("M(7) is PRP!", receipt['primenet_v5_result'])

        # Native transcripts are explicitly Corium JSON, never fake official .proof.
        self.assertFalse((chunkstore / "p7.proof").exists())
        json_file = chunkstore / "p7.corium-proof.json"
        self.assertTrue(json_file.exists())
        proof_json = json.loads(json_file.read_text())
        self.assertEqual(proof_json['format'], 'corium-json')
        self.assertFalse(proof_json['primenet_accepted'])
        self.assertEqual(proof_json['schema'], 'corium.gimps-scientific-proof.v1')
        self.assertEqual(proof_json['exponent'], 7)

    def test_resource_governor_and_checkpoint_manager(self):
        from ziokt.effort_gimps import ResourceGovernor, CheckpointManager
        governor = ResourceGovernor(max_memory_mb=2048, max_checkpoint_bytes=1024, max_proof_bytes=2048)
        self.assertTrue(governor.check_memory())
        tiny_governor = ResourceGovernor(max_memory_mb=1, max_checkpoint_bytes=1024, max_proof_bytes=2048)
        self.assertFalse(tiny_governor.check_memory())
        self.assertTrue(governor.check_checkpoint_size({'step': 100}))
        self.assertFalse(governor.check_checkpoint_size({'huge': 'X' * 2000}))
        self.assertTrue(governor.check_proof_size({'proof': 'small'}))
        self.assertFalse(governor.check_proof_size({'huge': 'Y' * 4000}))

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'test_chk.sqlite'
            with sqlite3.connect(db_path) as db:
                cm = CheckpointManager(db, governor)
                cm.save_checkpoint('task-1', 'gimps-1', 13, 'worker-1', 5, {'midpoint': '0xABC'})
                loaded = cm.load_checkpoint('task-1')
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded['exponent'], 13)
                self.assertEqual(loaded['checkpoint_data'], {'midpoint': '0xABC'})

                by_exp = cm.load_checkpoint_by_exponent(13)
                self.assertIsNotNone(by_exp)
                self.assertEqual(by_exp['iteration'], 5)

                cm.delete_checkpoint('task-1')
                self.assertIsNone(cm.load_checkpoint('task-1'))

    def test_primenet_adapter_formatting_and_lifecycle(self):
        from ziokt.effort_gimps import PrimeNetAdapter
        v5_str = PrimeNetAdapter.format_v5_result(127, True, "123456789ABCDEF0", uid="WORKER-1", gerbicz_status="OK")
        self.assertIn("UID: WORKER-1;", v5_str)
        self.assertIn("M(127) is PRP!", v5_str)
        self.assertIn("RES64: 123456789ABCDEF0;", v5_str)

        parsed = PrimeNetAdapter.parse_v5_result(v5_str)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['uid'], "WORKER-1")
        self.assertEqual(parsed['exponent'], 127)
        self.assertTrue(parsed['is_prime'])
        self.assertEqual(parsed['res64'], "123456789ABCDEF0")
        self.assertEqual(parsed['gerbicz_status'], "OK")

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'test_pnet.sqlite'
            with sqlite3.connect(db_path) as db:
                pnet = PrimeNetAdapter(db)
                pnet.record_assignment(127, 'ASSIGN-127')
                att = pnet.get_attestation(127)
                self.assertEqual(att['assignment_uid'], 'ASSIGN-127')
                self.assertEqual(att['status'], 'assigned')

                pnet.record_submission(127, v5_str, receipt={'tx': '0x123'})
                att = pnet.get_attestation(127)
                self.assertEqual(att['status'], 'submitted')
                self.assertEqual(att['v5_result'], v5_str)

                with self.assertRaises(ValueError):
                    pnet.record_acceptance(127, receipt={'confirmed': True})
                att = pnet.get_attestation(127)
                self.assertEqual(att['status'], 'submitted')

                # Test staging & offline transmission
                res_offline = pnet.transmit_v5_result(127, v5_str, primenet_url=None)
                self.assertEqual(res_offline['status'], PrimeNetAdapter.STATE_LOCAL_STAGED)
                self.assertFalse(res_offline['acknowledged'])

        # Test MPrimeEngineAdapter
        from ziokt.effort_gimps import MPrimeEngineAdapter
        with tempfile.TemporaryDirectory() as mprime_dir:
            res_txt = Path(mprime_dir) / 'results.txt'
            res_txt.write_text("UID: TEST-UID; M(127) is PRP! RES64: 123456789ABCDEF0; Gerbicz: OK\n")
            adapter = MPrimeEngineAdapter(bin_path=None, work_dir=mprime_dir)
            parsed_list = adapter.parse_results_file(res_txt)
            self.assertEqual(len(parsed_list), 1)
            self.assertEqual(parsed_list[0]['exponent'], 127)

    def test_official_gimps_results_and_proof_fixtures(self):
        import base64
        import hashlib
        from ziokt.gimps_files import verify_proof
        from ziokt.effort_gimps import MPrimeEngineAdapter
        fixtures = Path(__file__).parent / 'fixtures/gimps'
        provenance = json.loads((fixtures / 'mprime-provenance.json').read_text())
        for name, expected in provenance['files'].items():
            raw = base64.b64decode((fixtures / (name + '.b64')).read_text(), validate=False)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected['sha256'])
            verified = verify_proof(raw)
            self.assertEqual(verified['exponent'], expected['exponent'])
            self.assertTrue(verified['math_verified'])
            self.assertFalse(verified['primenet_accepted'])
            with tempfile.TemporaryDirectory() as directory:
                (Path(directory) / name).write_bytes(raw)
                converted = MPrimeEngineAdapter(work_dir=directory).build_proof_from_mprime(expected['exponent'])
                from ziokt._runtime import _native_gimps
                self.assertTrue(_native_gimps.verify_prp_proof(expected['exponent'], converted))
        parsed = MPrimeEngineAdapter().parse_results_file(fixtures / 'mprime-results.jsonl')
        self.assertEqual([r['exponent'] for r in parsed], [127, 521])
        self.assertTrue(all(r['is_prp'] and not r['is_prime'] for r in parsed))

    def test_lease_persistence_and_node_restart(self):
        sys.path.insert(0, str(C))
        from test_core import Fixture
        fixture = Fixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for path in fixture.root.rglob('*'):
            if path.is_dir():
                path.chmod(0o700)
        (fixture.etc / 'identity.key').chmod(0o600)
        config = fixture.etc / 'corix.conf'
        config.write_text('[ziokt]\nenabled=TRUE\nfederation_id=effort\nprovider_id=corium-local\nallow_mutations=TRUE\nallowed_operations=compute.submit\nallowed_resources=compute:gimps-effort\n')
        config.chmod(0o600)
        with sqlite3.connect(fixture.chain) as db:
            head, height = db.execute('SELECT hash,height FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
            db.execute("INSERT OR REPLACE INTO chain_state VALUES ('chain_info',?)", (head + '|' + str(height),))
            db.execute("INSERT INTO compute_engines(engine_id,pkg_id,description,compute_program_hash,verifier_script_hash,is_active) VALUES ('gimps-effort','corium/built-in-gimps','native','BUILT_IN','BUILT_IN',1)")
            db.execute("INSERT INTO problem_sets(set_id,engine_id,metadata,activation_height) VALUES ('effort-set','gimps-effort',?,0)", (json.dumps({'start_exponent': 13, 'end_exponent': 13}),))

        client = NativeClient('effort', {'native_project': 'corium', 'provider_id': 'corium-local', 'root': str(C), 'native_config': str(config), 'entrypoint_digest': fingerprint(C / 'corix_v108.sh'), 'network_id': 'default', 'state_root': str(fixture.root)})
        state_dir = fixture.root / 'effort-gimps'
        pool1 = GimpsPool(client, fixture.identity, state_dir, expected_network='default')

        # 1. Issue task and verify lease in DB
        job = pool1.issue()
        token = job['token']
        self.assertEqual(job['exponent'], 13)

        row = pool1.db.execute("SELECT exponent, expires FROM gimps_leases WHERE token=?", (token,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 13)
        pool1.close()

        # 2. Simulate Node / Gateway restart: new GimpsPool instance restores active lease from SQLite
        pool2 = GimpsPool(client, fixture.identity, state_dir, expected_network='default')
        self.addCleanup(pool2.close)
        self.assertIn(token, pool2.jobs)
        self.assertEqual(pool2.jobs[token]['exponent'], 13)

        # 3. Heartbeat succeeds on restarted node
        hb = pool2.heartbeat(token, progress_pct=50, checkpoint_data={'iteration': 6, 'val': 'test'})
        self.assertTrue(hb['renewed'])
        self.assertEqual(hb['exponent'], 13)

        # 4. Submit proof succeeds on restarted node
        import gimps_consensus as G
        proof_13 = G.generate_prp_proof(13, base=3, depth=3)
        receipt = pool2.submit(token, proof_13)
        self.assertTrue(receipt['accepted'])
        self.assertTrue(receipt['math_certified'])

        # Lease deleted after submission
        row = pool2.db.execute("SELECT 1 FROM gimps_leases WHERE token=?", (token,)).fetchone()
        self.assertIsNone(row)
        # A completed token has a durable idempotent receipt, even after restart.
        pool3 = GimpsPool(client, fixture.identity, state_dir, expected_network='default')
        self.addCleanup(pool3.close)
        self.assertTrue(pool3.submit(token, proof_13)['duplicate'])

    def test_primenet_response_verification(self):
        from ziokt.effort_gimps import PrimeNetAdapter
        # 1. Official JSON with pnErrorResult = 0 -> accepted
        resp_json_ok = json.dumps({'pnErrorResult': 0, 'pnErrorDetail': 'Result accepted', 'assignment_uid': 'UID-999'})
        ack, rej, receipt = PrimeNetAdapter.parse_primenet_response(resp_json_ok, 200)
        self.assertTrue(ack)
        self.assertFalse(rej)
        self.assertEqual(receipt['status'], 'protocol_success')

        # 2. Official JSON with pnErrorResult = 1 -> rejected
        resp_json_err = json.dumps({'pnErrorResult': 1, 'pnErrorDetail': 'Assignment expired or unknown'})
        ack, rej, receipt = PrimeNetAdapter.parse_primenet_response(resp_json_err, 200)
        self.assertFalse(ack)
        self.assertTrue(rej)
        self.assertEqual(receipt['reason'], 'Assignment expired or unknown')

        # 3. Ambiguous HTTP 200 HTML page -> NOT accepted
        resp_html = "<html><body>Welcome to nginx!</body></html>"
        ack, rej, receipt = PrimeNetAdapter.parse_primenet_response(resp_html, 200)
        self.assertFalse(ack)
        self.assertFalse(rej)
        self.assertEqual(receipt['status'], 'unrecognized')

"""Real signed SQLite receipt export; does not claim container or chain execution."""
import copy
import secrets
import tempfile
import unittest
from openci.state import Store,Error
from openci.attestation import DOMAIN,statement
from openci import chain,quorum,_consensus as consensus
from ziokt.security import sign
from test_openci_state import pipeline,task,REF,OTHER


class NativeContributionPlanTests(unittest.TestCase):
    def setUp(self):
        area=tempfile.TemporaryDirectory();self.addCleanup(area.cleanup)
        self.store=Store(area.name);self.keys={name:secrets.token_bytes(32) for name in ('one','two')}
        workers=[]
        for name,pool in [('one','community'),('two','trusted')]:
            public=sign({},self.keys[name],'key')['public_key']
            self.store.approve_worker('owner',name,arch='x86_64',pool=pool,cpu=1,memory_mb=128,slots=1,projects=['demo'])
            self.store.approve_receipt_key('owner',name,public,'sha256:'+'1'*64)
            quorum.approve(self.store,'owner',name,name,[task()['image']],'sha256:'+'2'*64)
            workers.append({'id':name,'pool':pool,'public_key':public,'failure_domain':name})
        program={k:v for k,v in task().items() if k in {'image','argv','arch','cpu','memory_mb','timeout'}}
        program['outputs']=['result'];bounty={'name':'build','beneficiary':'b'*64,'anchor':'a'*64,'source':REF,'program':program}
        self.policy={'schema':consensus.SCHEMA,'network':'test-export','genesis':'a'*64,'activation_height':111,'expiry_height':1000,'threshold':2,'workers':workers,'bounties':[bounty]}
        program['argv'].append(consensus.claim_token(self.policy,bounty))
        tasks=[{**task('build'),**program},{**task('verify',['build'],'trusted'),**program}]
        self.pid=self.store.submit('owner',pipeline(tasks))['pipeline']
        result={'exit_code':0,'artifact':REF,'logs':OTHER}
        for name in ('one','two'):
            claim=self.store.claim(name);envelope=sign(statement(name,claim,result),self.keys[name],DOMAIN)
            self.store.finish(name,self.pid,claim['task']['id'],claim['lease'],**result,attestation=envelope)
        self.store.verify_rebuild('owner',self.pid,'build','verify')

    def plan(self,policy=None):return chain.prepare(self.store,self.pid,'build',policy or self.policy,'c'*64,'build')

    def test_exact_current_signed_receipts_export_without_settlement(self):
        first=self.plan();self.assertEqual(first,self.plan())
        self.assertFalse(first['ledger_modified']);self.assertFalse(first['corium_settled'])
        self.assertEqual(first['governance_approved'],'not_assessed')
        self.assertEqual(first['payload']['problem_id'],consensus.problem(self.policy,'build'))
        self.assertEqual(len(first['payload']['proof_data']['receipts']),2)

    def test_mainnet_recipient_and_approval_changes_reject(self):
        for change in ('network','beneficiary','key','domain'):
            policy=copy.deepcopy(self.policy)
            if change=='network':policy['network']='ziokt-main'
            if change=='beneficiary':policy['bounties'][0]['beneficiary']='d'*64
            if change=='key':policy['workers'][0]['public_key']='f'*64
            if change=='domain':policy['workers'][0]['failure_domain']='other'
            with self.subTest(change=change),self.assertRaises(Error):self.plan(policy)
        self.store.disable_worker('owner','two')
        with self.assertRaises(Error):self.plan()

if __name__=='__main__':unittest.main()

"""Actual Ed25519 receipts and persistent SQLite; no claimed container execution."""
import copy
import secrets
import tempfile
import unittest
from openci.state import Store,Error
from openci.attestation import DOMAIN,statement
from ziokt.security import sign
from test_openci_state import pipeline,task,REF,OTHER


class WorkerAttestationTests(unittest.TestCase):
    def setUp(self):
        area=tempfile.TemporaryDirectory();self.addCleanup(area.cleanup);self.root=area.name;self.store=Store(self.root)
        self.keys={name:secrets.token_bytes(32) for name in ('one','two')}
        for name,pool in [('one','community'),('two','trusted')]:
            self.store.approve_worker('owner',name,arch='x86_64',pool=pool,cpu=1,memory_mb=128,slots=1,projects=['demo'])
            self.enroll(name)
        tasks=[task('build'),task('verify',['build'],'trusted')]
        for item in tasks:item['outputs']=['firmware']
        self.pid=self.store.submit('owner',pipeline(tasks))['pipeline']
        self.result={'exit_code':0,'artifact':REF,'logs':OTHER}

    def enroll(self,name):
        self.store.approve_receipt_key('owner',name,sign({},self.keys[name],'test-key')['public_key'],'sha256:'+'1'*64)

    def envelope(self,name,assignment):return sign(statement(name,assignment,self.result),self.keys[name],DOMAIN)

    def finish(self,name,assignment,envelope):
        return self.store.finish(name,self.pid,assignment['task']['id'],assignment['lease'],**self.result,attestation=envelope)

    def completed(self):
        for name in ('one','two'):
            assignment=self.store.claim(name);self.finish(name,assignment,self.envelope(name,assignment))
        return self.store.verify_rebuild('owner',self.pid,'build','verify')

    def test_approved_identity_requires_signature_and_exact_result(self):
        assignment=self.store.claim('one');valid=self.envelope('one',assignment)
        with self.assertRaises(Error):self.finish('one',assignment,None)
        for field,value in [('worker','two'),('pipeline','a'*64),('attempt',2),('source',OTHER),('lease_digest','sha256:'+'2'*64),('task_digest','sha256:'+'3'*64),('result',{**self.result,'artifact':OTHER})]:
            forged=copy.deepcopy(valid);forged['payload'][field]=value
            # Both tampered signatures and correctly signed wrong-context claims must fail.
            with self.subTest(field=field),self.assertRaises(Error):self.finish('one',assignment,forged)
            signed=sign(forged['payload'],self.keys['one'],DOMAIN)
            with self.assertRaises(Error):self.finish('one',assignment,signed)
        self.assertEqual(self.finish('one',assignment,valid)['state'],'completed')
        self.assertTrue(self.finish('one',assignment,valid)['duplicate'])

    def test_wrong_key_and_domain_cannot_complete(self):
        assignment=self.store.claim('one');payload=statement('one',assignment,self.result)
        for envelope in (sign(payload,self.keys['two'],DOMAIN),sign(payload,self.keys['one'],'Other/domain')):
            with self.assertRaises(Error):self.finish('one',assignment,envelope)
        with self.assertRaises(Error):self.enroll('one')  # running Worker cannot change signer

    def test_receipts_survive_restart_and_rotation_blocks_release(self):
        self.completed();self.store=Store(self.root)
        tasks=self.store.inspect(self.pid)['tasks'];self.assertTrue(all(t['attestation'] for t in tasks))
        self.assertNotIn('lease',tasks[0]['attestation']['payload'])
        request={'pipeline':self.pid}
        release=self.store.prepare_release('owner',self.pid,'build','package','1','a'*64,request)
        self.keys['two']=secrets.token_bytes(32);self.enroll('two')
        with self.assertRaises(Error):self.store.complete_release('owner',release['id'],{'package_id':'fixture'})
        self.assertEqual(self.store.release(release['id'])['state'],'prepared')

    def test_two_worker_names_with_one_signing_key_are_not_independent(self):
        self.keys['two']=self.keys['one'];self.enroll('two')
        with self.assertRaises(Error) as caught:self.completed()
        self.assertEqual(caught.exception.code,'SELF_VERIFICATION')

    def test_unsigned_legacy_completion_remains_ordinary_ci_not_signed_evidence(self):
        self.store.approve_worker('owner','legacy',arch='x86_64',pool='community',cpu=1,memory_mb=128,slots=1,projects=['other'])
        value=pipeline(project='other',nonce='legacy');pid=self.store.submit('owner',value)['pipeline'];claim=self.store.claim('legacy')
        self.store.finish('legacy',pid,'build',claim['lease'],**self.result)
        self.assertIsNone(self.store.inspect(pid)['tasks'][0]['attestation'])
        self.assertEqual(self.store.inspect(pid)['settlement'],'not_requested')

if __name__=='__main__':unittest.main()

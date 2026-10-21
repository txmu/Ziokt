"""Real SQLite scheduling/liveness only; no container or consensus evidence."""
import tempfile
import unittest
from openci.state import Store,Error
from openci.quorum import approve,presence,enqueue
from test_openci_state import task,pipeline,REF,OTHER


class QuorumTests(unittest.TestCase):
    def setUp(self):
        area=tempfile.TemporaryDirectory();self.addCleanup(area.cleanup)
        self.now=1000;self.store=Store(area.name,clock=lambda:self.now)
        self.spec=task();self.spec['outputs']=['firmware.img']
        self.pid=self.store.submit('owner',pipeline([self.spec]))['pipeline']

    def worker(self,name,domain,pool='community'):
        self.store.approve_worker('owner',name,arch='x86_64',pool=pool,cpu=1,memory_mb=256,slots=1,projects=['demo'])
        approve(self.store,'owner',name,domain,[self.spec['image']],'sha256:'+'a'*64)
        presence(self.store,name,[self.spec['image']])

    def plan(self,nonce='replication'):
        return enqueue(self.store,'owner',self.pid,'build',nonce)

    def test_sparse_nodes_disabled_then_live_recovery_and_expiry(self):
        self.assertEqual(self.plan()['state'],'disabled')
        self.worker('one','site1','trusted')
        self.assertEqual(self.plan()['state'],'disabled')
        self.worker('two','site2')
        self.now+=60
        self.assertEqual(self.plan()['state'],'disabled')
        for name in ['one','two']:presence(self.store,name,[self.spec['image']])
        result=self.plan();self.assertEqual(result['state'],'submitted')
        self.assertFalse(result['selection']['consensus_activation'])
        self.assertFalse(result['selection']['compiler_backdoor_exclusion_verified'])
        self.store.disable_worker('owner','two')
        self.assertEqual(self.plan()['pipeline'],result['pipeline'])
        self.assertEqual(self.plan('new')['state'],'disabled')

    def test_two_identities_on_same_host_or_without_trusted_verifier_do_not_count(self):
        self.worker('one','same');self.worker('two','same','trusted')
        self.assertEqual(self.plan()['state'],'disabled')
        approve(self.store,'owner','two','different',[self.spec['image']],'sha256:'+'b'*64)
        self.assertEqual(self.plan()['state'],'disabled')  # reapproval requires fresh presence
        presence(self.store,'two',[self.spec['image']])
        self.assertEqual(self.plan()['state'],'submitted')

    def test_actual_affinity_queue_and_independent_output_verification(self):
        self.worker('one','site1','trusted');self.worker('two','site2')
        result=self.plan();pid=result['pipeline']
        # Original ordinary pipeline is not part of the replica plan.
        self.store.cancel('owner',self.pid)
        claims={name:self.store.claim(name) for name in ['one','two']}
        for name,claim in claims.items():
            self.assertEqual(claim['pipeline'],pid)
            self.assertEqual(claim['task']['worker'],name)
            self.store.finish(name,pid,claim['task']['id'],claim['lease'],exit_code=0,artifact=REF,logs=OTHER)
        verified=self.store.verify_rebuild('owner',pid,claims['two']['task']['id'],claims['one']['task']['id'])
        self.assertEqual(verified['status'],'matched')
        self.assertFalse(verified['software_security_verified'])
        approve(self.store,'owner','two','site1',[self.spec['image']],'sha256:'+'b'*64)
        with self.assertRaises(Error) as denied:
            self.store.verify_rebuild('owner',pid,claims['two']['task']['id'],claims['one']['task']['id'])
        self.assertEqual(denied.exception.code,'BUILD_DOMAINS')

    def test_unapproved_image_and_disabled_worker_cannot_enable_replicas(self):
        self.worker('one','site1','trusted');self.worker('two','site2')
        presence(self.store,'two',['other.invalid/toolchain@sha256:'+'2'*64])
        self.assertEqual(self.plan()['state'],'disabled')
        self.store.disable_worker('owner','two')
        with self.assertRaises(Error):presence(self.store,'two',[self.spec['image']])
        with self.assertRaises(Error):presence(self.store,'one',[{}])
        with self.assertRaises(Error):self.plan('bad nonce')

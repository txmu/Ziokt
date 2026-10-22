"""Real SQLite revocation/restart checks; these are not native settlement tests."""
import tempfile
import unittest
from openci.state import Store,Error
from openci.quorum import approve,presence,enqueue
from test_openci_state import task,pipeline,REF,OTHER


class ReleaseAuthorityTests(unittest.TestCase):
    def setUp(self):
        area=tempfile.TemporaryDirectory();self.addCleanup(area.cleanup)
        self.root=area.name;self.store=Store(self.root)
        self.image=task()['image'];spec=task();spec['outputs']=['firmware.img']
        original=self.store.submit('owner',pipeline([spec]))['pipeline']
        for name,domain,pool in [('producer','site1','community'),('verifier','site2','trusted')]:
            self.store.approve_worker('owner',name,arch='x86_64',pool=pool,cpu=1,memory_mb=256,slots=1,projects=['demo'])
            approve(self.store,'owner',name,domain,[self.image],'sha256:'+'a'*64)
            presence(self.store,name,[self.image])
        self.pid=enqueue(self.store,'owner',original,'build','replicas')['pipeline']
        self.store.cancel('owner',original)
        self.tasks={}
        for name in ['producer','verifier']:
            claim=self.store.claim(name);self.tasks[name]=claim['task']['id']
            self.store.finish(name,self.pid,claim['task']['id'],claim['lease'],exit_code=0,artifact=REF,logs=OTHER)
        self.verify()

    def verify(self):
        return self.store.verify_rebuild('owner',self.pid,self.tasks['producer'],self.tasks['verifier'])

    def prepare(self):
        return self.store.prepare_release('owner',self.pid,self.tasks['producer'],'firmware','1','1'*64,{'pipeline':self.pid})

    def change_profile(self,domain='site3',images=None):
        approve(self.store,'owner','verifier',domain,images or [self.image],'sha256:'+'b'*64)

    def test_domain_merger_blocks_preparation(self):
        self.change_profile('site1')
        with self.assertRaises(Error) as caught:self.prepare()
        self.assertEqual(caught.exception.code,'RELEASE_BUILD_PROFILE_CHANGED')

    def test_image_revocation_blocks_preparation(self):
        self.change_profile(images=['other.invalid/image@sha256:'+'2'*64])
        with self.assertRaises(Error):self.prepare()

    def test_profile_revision_requires_new_verification(self):
        self.change_profile()
        with self.assertRaises(Error):self.prepare()
        self.verify();self.assertEqual(self.prepare()['state'],'prepared')

    def test_producer_revocation_blocks_preparation(self):
        self.store.disable_worker('owner','producer')
        with self.assertRaises(Error):self.prepare()

    def test_revocation_between_prepare_and_complete_survives_restart(self):
        prepared=self.prepare();self.change_profile('site1')
        self.store=Store(self.root)
        with self.assertRaises(Error):self.store.complete_release('owner',prepared['id'],{'package_id':'fixture'})
        self.assertEqual(self.store.release(prepared['id'])['state'],'prepared')
        self.assertFalse(any(e['action']=='release.published' for e in self.store.audit(self.pid)))

    def test_unchanged_approval_allows_publication_and_idempotency(self):
        prepared=self.prepare();result={'package_id':'fixture','corium_settled':False}
        self.assertEqual(self.store.complete_release('owner',prepared['id'],result)['state'],'published')
        self.assertEqual(self.store.complete_release('owner',prepared['id'],result)['publication'],result)

if __name__=='__main__':unittest.main()

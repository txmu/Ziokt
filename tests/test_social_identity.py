"""Real key signatures and SQLite persistence; no simulated applications."""
import secrets,tempfile,time,unittest
from pathlib import Path
from ziokt.security import sign
from ziokt.social_identity import IdentityLinks,DOMAIN,identity

class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'links.db';self.store=IdentityLinks(self.path,'test');self.addCleanup(lambda:self.store.close())
        self.keys=[secrets.token_bytes(32) for _ in range(5)]
        self.ids=[{'app':app,'network':'test','algorithm':'ed25519','public_key':sign({},k,DOMAIN)['public_key']} for app,k in zip(['community','content-fabric','etp','corium','watchat'],self.keys)]
        self.statement={'schema':'ziokt.social-link.v1','network':'test','id':secrets.token_hex(32),'revision':1,'previous':'','action':'bind','left':self.ids[0],'right':self.ids[1],'recovery':{'left':{'threshold':2,'keys':self.ids[2:4]},'right':{'threshold':0,'keys':[]}},'issued':int(time.time()),'expires':int(time.time())+1000}
    def envelope(self,s,indices):return {'statement':s,'proofs':[{'identity':self.ids[i],'signature':sign(s,self.keys[i],DOMAIN)['signature']} for i in indices]}
    def test_bilateral_proof_and_tamper_replay_and_isolation(self):
        with self.assertRaises(ValueError):self.store.apply('alice',self.envelope(self.statement,[0]))
        e=self.envelope(self.statement,[0,1]);r=self.store.apply('alice',e);self.assertFalse(r['grants_application_access'])
        self.assertTrue(self.store.apply('alice',e)['duplicate']);self.assertEqual(self.store.list('bob')['items'],[])
        altered=dict(self.statement,network='other')
        with self.assertRaises(ValueError):self.store.apply('alice',self.envelope(altered,[0,1]))
        self.assertEqual(len(self.store.export('alice',r['id'])['proofs']),1)
    def test_rotation_and_unilateral_irreversible_revocation(self):
        r=self.store.apply('alice',self.envelope(self.statement,[0,1]))
        rotated=dict(self.statement,action='rotate',revision=2,previous=r['head'],left=self.ids[4])
        with self.assertRaises(ValueError):self.store.apply('alice',self.envelope(rotated,[1,4]))
        r=self.store.apply('alice',self.envelope(rotated,[0,1,4]))
        revoked=dict(rotated,action='revoke',revision=3,previous=r['head']);r=self.store.apply('alice',self.envelope(revoked,[1]))
        self.assertEqual(r['state'],'revoked')
        with self.assertRaises(ValueError):self.store.apply('alice',self.envelope(dict(revoked,action='rotate',revision=4,previous=r['head']),[1,4]))
    def test_recovery_needs_previous_quorum_counterparty_and_new_key(self):
        r=self.store.apply('alice',self.envelope(self.statement,[0,1]));s=dict(self.statement,action='recover-left',revision=2,previous=r['head'],left=self.ids[4])
        for indices in ([1,2,4],[2,3,4],[1,2,3]):
            with self.assertRaises(ValueError):self.store.apply('alice',self.envelope(s,indices))
        self.store.apply('alice',self.envelope(s,[1,2,3,4]));self.store.close();self.store=IdentityLinks(self.path,'test')
        self.assertEqual(self.store.list('alice')['items'][0]['revision'],2)

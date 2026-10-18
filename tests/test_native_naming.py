"""Actual native journal, owner signatures, NNS consensus and identity linking."""
import json
import sqlite3
import sys
import time
import unittest
from test_native_integration import C
from ziokt.client import NativeClient
from ziokt.config import fingerprint
from ziokt.protocol import ProtocolError
from ziokt.security import sign
from ziokt.gateway_store import Store
from ziokt.naming_corium import CoriumNames
from ziokt.naming import Names

class NativeNamingTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0,str(C))
        try:from test_core import Fixture
        finally:sys.path.pop(0)
        fixture=Fixture();fixture.setUp();self.addCleanup(fixture.doCleanups);self.fixture=fixture
        for path in fixture.root.rglob('*'):
            if path.is_dir():path.chmod(0o700)
        (fixture.etc/'identity.key').chmod(0o600)
        config=fixture.etc/'corix.conf'
        config.write_text('[ziokt]\nenabled=TRUE\nfederation_id=test\nprovider_id=corium-local\nallow_mutations=TRUE\nallowed_operations=identity.register,naming.submit,chain.mine\nallowed_resources=*\n');config.chmod(0o600)
        self.client=NativeClient('test',{'native_project':'corium','provider_id':'corium-local','root':str(C),'native_config':str(config),'state_root':str(fixture.root),'network_id':'default','entrypoint_digest':fingerprint(C/'corix_v108.sh')})
    def execute(self,operation,action,resource,arguments):
        plan=self.client.call('operation.prepare',{'operation_id':operation,'action':action,'resource':resource,'expected_revision':None,'arguments':arguments})
        return self.client.call('operation.commit',{'operation_id':operation,'plan_digest':plan['plan_digest']})
    def update(self,operation,target):
        return self.execute(operation,'naming.submit','naming:default',{'transaction_type':'nns_update','payload':{'records':[{'domain_name':'corium','target_hash':target}]}})
    def test_owner_scoped_nns_update_plan_and_actual_inclusion(self):
        result=self.update('nns-update','a'*64)
        self.assertEqual(result['result']['phase'],'pending-native-consensus')
        self.fixture.run_core('blockchain_mine_block')
        with sqlite3.connect(self.fixture.forum) as db:self.assertEqual(db.execute("SELECT target_hash FROM nns_records WHERE domain_name='corium'").fetchone()[0],'a'*64)
        with self.assertRaises(ProtocolError):self.execute('not-owned','naming.submit','naming:default',{'transaction_type':'nns_update','payload':{'records':[{'domain_name':'other','target_hash':'a'*64}]}})
    def test_native_identity_and_name_ownership_verified_independently(self):
        fixture=self.fixture;key=bytes(range(32));public=sign({},key,'test')['public_key'];policy='sha256:'+'a'*64
        self.execute('identity','identity.register','identity:'+public,{'document_commitment':'sha256:'+'b'*64,'policy_digest':policy})
        fixture.run_core('blockchain_mine_block')
        expiry=int(time.time())+300
        delegation={'network_id':'default','component':'corium','path':'corium','parent_revision':1,'revision':1,'expires_at':expiry,'delegate':None,'descriptor':{'public_dns':[{'type':'A','value':'8.8.8.8','ttl':30}],'services':{},'private':None}}
        registration={'network_id':'default','owner':public,'revision':1,'expires_at':expiry,'published_suffixes':['corix'],'delegations':{'corium':sign(delegation,key,'Ziokt/name-delegation/v1')},'identity_registration':{'member_public':public,'policy_digest':policy,'issuer':fixture.identity}}
        store=Store(fixture.root/'var/lib/corix/p2p/objects');target=store.put(json.dumps({'ziokt_naming':registration}).encode())
        self.update('publish-linked',target);fixture.run_core('blockchain_mine_block')
        names=Names({'corium':CoriumNames(forum_db=fixture.forum,chain_db=fixture.chain,objects=store.directory,network_id='default')},network_id='default')
        value=names.resolve('corium.corix',component='corium',public=False)
        self.assertTrue(value['ownership_proof']['identity_registration']['registered'])
        self.assertNotIn(fixture.identity,str(names.resolve('corium.corix')))
        self.assertFalse(value['authenticated_access'])
        registration['identity_registration']['issuer']='f'*64
        target=store.put(json.dumps({'ziokt_naming':registration}).encode());self.update('bad-link',target);fixture.run_core('blockchain_mine_block')
        with self.assertRaises(ProtocolError):names.resolve('corium.corix')

if __name__=='__main__':unittest.main()

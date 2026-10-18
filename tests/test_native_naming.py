"""Actual native operation journal -> node signature -> NNS consensus update."""
import sqlite3
import sys
import unittest
from test_native_integration import C
from ziokt.client import NativeClient
from ziokt.config import fingerprint
from ziokt.protocol import ProtocolError

class NativeNamingTests(unittest.TestCase):
    def test_owner_scoped_nns_update_plan_and_actual_inclusion(self):
        sys.path.insert(0,str(C))
        try:from test_core import Fixture
        finally:sys.path.pop(0)
        fixture=Fixture();fixture.setUp();self.addCleanup(fixture.doCleanups)
        for path in fixture.root.rglob('*'):
            if path.is_dir():path.chmod(0o700)
        (fixture.etc/'identity.key').chmod(0o600)
        config=fixture.etc/'corix.conf'
        config.write_text('[ziokt]\nenabled=TRUE\nfederation_id=test\nprovider_id=corium-local\nallow_mutations=TRUE\nallowed_operations=naming.submit,chain.mine\nallowed_resources=*\n');config.chmod(0o600)
        client=NativeClient('test',{'native_project':'corium','provider_id':'corium-local','root':str(C),'native_config':str(config),'state_root':str(fixture.root),'network_id':'default','entrypoint_digest':fingerprint(C/'corix_v108.sh')})
        request={'operation_id':'nns-update','action':'naming.submit','resource':'naming:default','expected_revision':None,
                 'arguments':{'transaction_type':'nns_update','payload':{'records':[{'domain_name':'corium','target_hash':'a'*64}]}}}
        plan=client.call('operation.prepare',request)
        result=client.call('operation.commit',{'operation_id':'nns-update','plan_digest':plan['plan_digest']})
        self.assertEqual(result['result']['phase'],'pending-native-consensus')
        fixture.run_core('blockchain_mine_block')
        with sqlite3.connect(fixture.forum) as db:self.assertEqual(db.execute("SELECT target_hash FROM nns_records WHERE domain_name='corium'").fetchone()[0],'a'*64)
        request['operation_id']='not-owned';request['arguments']['payload']['records'][0]['domain_name']='other'
        with self.assertRaises(ProtocolError):client.call('operation.prepare',request)

if __name__=='__main__':unittest.main()

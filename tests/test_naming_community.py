import secrets
import tempfile
import time
from pathlib import Path
import unittest
from types import SimpleNamespace
import test_companion_crypto as fixtures
from ziokt.companion_bridge import CompanionBridge
from ziokt.community import create_policy,RIGHTS
from ziokt.security import sign
from ziokt.naming import Names
from ziokt.naming_community import ComponentNames,DOMAIN,check_record
from ziokt.protocol import ProtocolError

class ComponentNamesTests(unittest.TestCase):
    def test_native_signing_key_accepts_bytes_and_private_file_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            key=secrets.token_bytes(32);public=sign({},key,'test')['public_key']
            path=Path(directory)/'signing.key';path.write_bytes(key);path.chmod(0o600)
            record={'network_id':'network-one','component':'safefs','root':'village','owner':public,
                    'revision':1,'expires_at':int(time.time())+3600,'delegations':{},'published_suffixes':[]}
            envelope=sign(record,key,DOMAIN)
            for material in (key,path,str(path)):
                bridge=SimpleNamespace(app='safefs',signing_key=material,naming_namespaces=['network-one'],community=SimpleNamespace())
                with self.subTest(material=type(material).__name__):
                    checked,native=check_record(bridge,envelope,'network-one','village')
                    self.assertEqual(checked,record)
                    self.assertEqual(native['proof']['authority'],public)
            bridge.signing_key=secrets.token_bytes(32)
            with self.assertRaises(ProtocolError):check_record(bridge,envelope,'network-one','village')

    def test_component_node_opt_in_registration_update_and_unpublish(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);key=secrets.token_bytes(32);public=sign({},key,'test')['public_key']
            policy=create_policy(key,'network-one',{public:sorted(RIGHTS)})
            path=fixtures.CompanionCrypto()._make_bridge(root,key,public,policy,app='safefs')
            bridge=CompanionBridge(path);self.addCleanup(bridge.close)
            expiry=int(time.time())+3600
            delegation={'network_id':'network-one','component':'safefs','path':'community','parent_revision':1,'revision':1,'expires_at':expiry,'delegate':None,'descriptor':{'public_dns':[{'type':'A','value':'8.8.8.8','ttl':60}],'services':{},'private':None}}
            registration={'network_id':'network-one','component':'safefs','root':'community','owner':public,'revision':1,'expires_at':expiry,'delegations':{'community':sign(delegation,key,'Ziokt/name-delegation/v1')},'published_suffixes':['fs']}
            resolver=Names({'safefs':ComponentNames(path,component='safefs',network_id='network-one')},network_id='network-one')
            with self.assertRaises(ProtocolError):resolver.resolve('community.fs')
            bridge.call('naming.publish',{'registration':sign(registration,key,DOMAIN)})
            self.assertTrue(resolver.resolve('community.fs')['records'])
            with self.assertRaises(ProtocolError):resolver.resolve('community.f')
            with self.assertRaises(ProtocolError):bridge.call('naming.publish',{'registration':sign(registration,secrets.token_bytes(32),DOMAIN)})
            revoked={**registration,'revision':2,'published_suffixes':[]}
            bridge.call('naming.publish',{'registration':sign(revoked,key,DOMAIN)})
            with self.assertRaises(ProtocolError):resolver.resolve('community.fs')
            with self.assertRaises(ProtocolError):bridge.call('naming.publish',{'registration':sign(registration,key,DOMAIN)})
            wrong=Names({'safefs':ComponentNames(path,component='safefs',network_id='another-chain')},network_id='another-chain')
            with self.assertRaises(ProtocolError):wrong.resolve('community.fs')

if __name__=='__main__':unittest.main()

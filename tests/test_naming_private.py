import unittest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat,PrivateFormat,NoEncryption
from ziokt.naming_private import seal,open_descriptor
from ziokt.protocol import ProtocolError

class PrivateNamesTests(unittest.TestCase):
    def test_real_encryption_fixed_frame_and_network_name_component_binding(self):
        key=X25519PrivateKey.generate();private=key.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption());public=key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        args={'network_id':'chain-one','name':'community.ziokt','component':'etp'}
        secret={'service_id':'not-public','endpoint':'10.0.0.1:1234','profile':'private'}
        envelope=seal(secret,public,**args)
        self.assertNotIn('10.0.0.1',str(envelope));self.assertEqual(open_descriptor(envelope,private,**args),secret)
        for change in ({'network_id':'chain-two'},{'name':'other.ziokt'},{'component':'shadow6'}):
            with self.assertRaises(ProtocolError):open_descriptor(envelope,private,**{**args,**change})
        with self.assertRaises(ProtocolError):open_descriptor(envelope,bytes(range(32)),**args)

if __name__=='__main__':unittest.main()

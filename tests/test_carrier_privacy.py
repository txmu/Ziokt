"""No DNS/direct socket use for alternate spellings of anonymous names."""
import unittest
from unittest.mock import patch
from ziokt.carrier import open_carrier
from ziokt.protocol import ProtocolError


class CarrierPrivacyTests(unittest.TestCase):
    def test_anonymous_suffix_variants_never_enter_direct_resolver(self):
        for suffix in ('onion','ONION','i2p','I2P'):
            for separator in ('.','\u3002','\uff0e','\uff61'):
                for trailing in ('','.'):
                    host='destination'+separator+suffix+trailing
                    with self.subTest(host=host),patch('ziokt.carrier.socket.create_connection',side_effect=AssertionError('direct/DNS leak')):
                        with self.assertRaises(ProtocolError) as failure:open_carrier(host,443)
                        self.assertEqual(failure.exception.code,'NO_POLICY_COMPLIANT_PATH')

    def test_failed_explicit_carrier_does_not_attempt_a_direct_retry(self):
        from ziokt.carrier import onion_address
        import base64,hashlib
        key=b'x'*32;version=b'\x03';checksum=hashlib.sha3_256(b'.onion checksum'+key+version).digest()[:2]
        host=base64.b32encode(key+checksum+version).decode().lower()+'.onion'
        onion_address(host)
        with patch('ziokt.carrier.socket.create_connection',side_effect=OSError('proxy unavailable')) as connect:
            with self.assertRaises(ProtocolError):open_carrier(host,443,{'kind':'tor-socks5','proxy_host':'127.0.0.1','proxy_port':19050})
            self.assertEqual(connect.call_count,1)
            self.assertEqual(connect.call_args.args[0],('127.0.0.1',19050))

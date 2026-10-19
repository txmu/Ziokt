import base64
import hashlib
import socket
import ssl
import threading
import unittest
from unittest.mock import patch
from ziokt.protocol import ProtocolError
from ziokt.resilient_transport import request_resilient


def onion(seed):
    key=hashlib.sha256(seed.encode()).digest();v=b'\x03'
    return base64.b32encode(key+hashlib.sha3_256(b'.onion checksum'+key+v).digest()[:2]+v).decode().lower()+'.onion'


class ResilienceTests(unittest.TestCase):
    def endpoint(self):
        observed={'end_to_end_authentication':True,'encrypted_content':True,'private_discovery':True,'anonymous_carrier':True,'direct_fallback':False}
        return {'host':onion('parent'),'port':443,'connection_policy':{'mode':'approved-paths','allow_direct_fallback':False},'candidates':[
            {'host':onion(str(i)),'port':443,'approved':True,'observed':observed,'carrier':{'kind':'tor-socks5','proxy_host':'127.0.0.1','proxy_port':19050+i},'connection_policy':{'mode':'anonymous','allow_direct_fallback':False}} for i in range(2)]}

    def test_blocked_entry_fails_over_with_new_grant_and_padding(self):
        endpoint=self.endpoint();grants=[]
        def grant():grants.append(len(grants));return {'nonce':str(len(grants))}
        def send(*args,**kwargs):
            self.assertTrue(kwargs['privacy_padding']);args[4]()
            if len(grants)==1:raise ConnectionRefusedError('blocked entry')
            return {'ok':'verified response'}
        with patch('ziokt.remote.request_remote',side_effect=send) as transport:
            self.assertEqual(request_resilient('restricted',endpoint,None,{'method':'community.event.put'},grant),{'ok':'verified response'})
        self.assertEqual(len(grants),2);self.assertEqual(transport.call_count,2)

    def test_tls_or_authorization_error_never_uses_another_route(self):
        for error in (ssl.SSLCertVerificationError('wrong peer'),ProtocolError('POLICY_DENIED','revoked member')):
            with self.subTest(error=type(error)),patch('ziokt.remote.request_remote',side_effect=error) as transport:
                with self.assertRaises(type(error)):request_resilient('restricted',self.endpoint(),None,{'method':'community.status'},lambda:{})
                self.assertEqual(transport.call_count,1)

    def test_no_downgrade_no_retry_for_uncertain_native_mutation(self):
        endpoint=self.endpoint();endpoint['candidates'][1].pop('carrier');endpoint['candidates'][1]['connection_policy']={'mode':'direct','allow_direct_fallback':False}
        with patch('ziokt.remote.request_remote',side_effect=ConnectionRefusedError()) as transport:
            with self.assertRaisesRegex(ProtocolError,'privacy preserved'):request_resilient('restricted',endpoint,None,{'method':'community.status'},lambda:{})
            self.assertEqual(transport.call_count,1)
        with patch('ziokt.remote.request_remote',side_effect=TimeoutError()) as transport:
            with self.assertRaises(ProtocolError):request_resilient('restricted',self.endpoint(),None,{'method':'operation.commit'},lambda:{})
            self.assertEqual(transport.call_count,1)

    def test_cancelled_before_connection_and_no_reused_grant(self):
        cancel=threading.Event();cancel.set()
        with patch('ziokt.remote.request_remote') as transport:
            with self.assertRaisesRegex(ProtocolError,'cancelled'):request_resilient('restricted',self.endpoint(),None,{'method':'community.status'},lambda:{},cancellation=cancel)
            transport.assert_not_called()
        with self.assertRaisesRegex(ProtocolError,'fresh scoped'):request_resilient('restricted',self.endpoint(),None,{'method':'community.status'},{'old':'grant'})

    def test_public_image_read_can_fail_over_and_diagnostics_strip_private_values(self):
        error = ProtocolError('CARRIER_UNAVAILABLE', 'private destination and isolation password')
        error.transport_diagnostic = {'phase': 'target-socks-connect', 'kind': 'OSError', 'socks_reply': 0xf0,
                                      'destination': 'private-node.onion', 'password': 'private-password'}
        with patch('ziokt.remote.request_remote', side_effect=[error, {'verified': True}]) as transport:
            self.assertEqual(request_resilient('restricted', self.endpoint(), None, {'method': 'zkn.shield.images'}, lambda: {}), {'verified': True})
            self.assertEqual(transport.call_count, 2)
        with patch('ziokt.remote.request_remote', side_effect=error):
            with self.assertRaises(ProtocolError) as caught:
                request_resilient('restricted', self.endpoint(), None, {'method': 'community.status'}, lambda: {})
        self.assertEqual(caught.exception.transport_diagnostics[0],
                         {'code': 'CARRIER_UNAVAILABLE', 'phase': 'target-socks-connect', 'kind': 'OSError', 'socks_reply': 0xf0})
        self.assertNotIn('private', str(caught.exception.transport_diagnostics))


if __name__=='__main__':unittest.main()

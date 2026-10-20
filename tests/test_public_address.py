"""Observation is not a service proof; offline failure must never reuse an old IP."""
import io
import unittest
from unittest.mock import patch
from ziokt.public_address import PublicAddress


class PublicAddressTests(unittest.TestCase):
    def test_global_address_cached_without_reachability_claim(self):
        observer = PublicAddress()
        with patch('ziokt.public_address.build_opener') as create:
            create.return_value.open.return_value = io.BytesIO(b'8.8.8.8\n')
            first = observer.observe()
            self.assertTrue(first['ok'])
            self.assertEqual(first['address'], '8.8.8.8')
            self.assertFalse(first['service_reachability_verified'])
            first['address'] = 'tampered'
            self.assertEqual(observer.observe()['address'], '8.8.8.8')
            self.assertEqual(create.return_value.open.call_count, 1)

    def test_private_malformed_oversized_and_offline_fail_closed(self):
        for raw in (b'127.0.0.1', b'192.168.1.1', b'not an IP', b'x'*65, b'\xff', b'::1'):
            with self.subTest(raw=raw), patch('ziokt.public_address.build_opener') as create:
                create.return_value.open.side_effect = lambda *a, **kw: io.BytesIO(raw)
                observer = PublicAddress()
                result = observer.observe()
                self.assertFalse(result['ok'])
                self.assertNotIn('address', result)
                self.assertEqual(result['error']['code'], 'PUBLIC_ADDRESS_UNAVAILABLE')
        with patch('ziokt.public_address.build_opener') as create:
            create.return_value.open.side_effect = OSError('offline')
            observer = PublicAddress()
            self.assertFalse(observer.observe()['ok'])
            self.assertFalse(observer.observe()['ok'])
            self.assertEqual(create.return_value.open.call_count, 2)

    def test_expired_success_is_not_reused_when_sources_fail(self):
        observer = PublicAddress(ttl=0)
        with patch('ziokt.public_address.build_opener') as create:
            create.return_value.open.return_value = io.BytesIO(b'8.8.8.8')
            self.assertTrue(observer.observe()['ok'])
            create.return_value.open.side_effect = OSError('offline')
            self.assertFalse(observer.observe()['ok'])
            self.assertNotIn('address', observer.observe())

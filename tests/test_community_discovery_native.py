import base64
import hashlib
import json
import threading
import unittest
from unittest.mock import Mock

from ziokt.discovery_native import fetch_records
from ziokt.protocol import ProtocolError
from ziokt.transport import plan_profiles
from pathlib import Path


class NativeDiscoveryTests(unittest.TestCase):
    def test_pinned_ranges_digest_cancellation_and_no_progress(self):
        data = json.dumps([{'signed-record':'x'*7000}]).encode()
        digest = 'sha256:'+hashlib.sha256(data).hexdigest()
        peer = '1'*64
        def call(method,params,**kwargs):
            offset = params['offset']; part = data[offset:offset+6144]
            return {'status':'success','digest':digest,'offset':offset,'total_size':len(data),'data_base64':base64.b64encode(part).decode()}
        client = Mock(); client.call.side_effect = call
        self.assertEqual(fetch_records(client,peer,digest),json.loads(data))
        event = threading.Event(); event.set()
        with self.assertRaises(ProtocolError): fetch_records(client,peer,digest,cancellation=event)
        client.call.side_effect = None
        client.call.return_value = {'status':'success','digest':digest,'offset':0,'total_size':len(data),'data_base64':''}
        with self.assertRaises(ProtocolError): fetch_records(client,peer,digest)

    def test_all_profiles_use_explicit_native_contracts(self):
        root = Path(__file__).resolve().parents[2]/'Shadow6'
        if not root.exists(): self.skipTest('source catalog exercised by native CI')
        records = plan_profiles(root,'discovery')
        self.assertEqual(len(records),13)
        self.assertTrue(all(r['eligible'] and not r['runtime_verified'] for r in records))
        streams = plan_profiles(root,'proxy-stream')
        self.assertTrue(all(r['eligible'] == (r['boundary']['kind']=='stream') for r in streams))

"""Bounded F2F admission and integrity tests; no fabricated native delivery."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from ziokt.protocol import ProtocolError
from ziokt.retroshare import native_json
from ziokt.retroshare_transport import FileCarrier
from ziokt.retroshare_node import private_json

class RetroShareTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.peer='a'*32;self.native=Mock();self.native.enabled=True;self.native.config={'transport':{'root':str(self.root/'spool'),'allowed_peers':[self.peer]}}
        self.native.inspect.return_value={'items':[self.peer]};self.native._request.return_value={'retval':True};self.carrier=FileCarrier(self.native)
        self.data=b'harmless fixture';self.digest=hashlib.sha256(self.data).hexdigest();self.native_hash=hashlib.sha1(self.data).hexdigest()
    def test_requests_are_native_friend_and_operator_allowlist_bound(self):
        self.native.inspect.return_value={'items':[]}
        with self.assertRaises(ProtocolError):self.carrier.request(self.native_hash,self.digest,len(self.data),self.peer)
        self.native._request.assert_not_called()
        self.native.inspect.return_value={'items':[self.peer]}
        result=self.carrier.request(self.native_hash,self.digest,len(self.data),self.peer);self.assertFalse(result['delivered'])
        arguments=self.native._request.call_args.args[1];self.assertEqual(arguments['srcIds'],[self.peer]);self.assertEqual(arguments['flags'],0x02000080)
    def test_collect_requires_exact_bytes_and_both_hashes(self):
        self.carrier.request(self.native_hash,self.digest,len(self.data),self.peer)
        self.assertFalse(self.carrier.collect(self.digest)['delivered'])
        path=self.root/'spool/incoming'/self.digest/(self.digest+'.bin');path.write_bytes(b'wrong')
        with self.assertRaises(ProtocolError):self.carrier.collect(self.digest)
        path.write_bytes(self.data);self.assertTrue(self.carrier.collect(self.digest)['delivered'])
        path.unlink();path.symlink_to(self.root/'outside');(self.root/'outside').write_bytes(self.data)
        with self.assertRaises((ProtocolError,OSError)):self.carrier.collect(self.digest)
    def test_offer_does_not_read_caller_paths_and_queueing_is_not_delivery(self):
        result=self.carrier.offer(self.data,60);self.assertFalse(result['delivered'])
        self.native._request.return_value={'retval':False};self.assertEqual(self.carrier.offer_status(self.digest)['state'],'hashing')
        self.native._request.return_value={'retval':True,'info':{'hash':self.native_hash,'size':{'xint64':len(self.data),'xstr64':str(len(self.data))}}}
        self.assertEqual(self.carrier.offer_status(self.digest)['state'],'offered')
        with self.assertRaises(ProtocolError):self.carrier.offer(b'x'*65537)
    def test_native_diagnostic_floats_cannot_become_trusted_sizes(self):
        value=native_json(b'{"rank":0.0,"size":12.0}');self.assertEqual(value['size'],'12.0')
        for raw in (b'{"size":1,"size":2}',b'{"rank":NaN}',b'{"rank":1e999}'):
            with self.assertRaises(ProtocolError):native_json(raw)
    def test_private_profile_configuration_contains_only_private_files(self):
        path=self.root/'node.json';private_json(path,{'test':'private'});self.assertEqual(path.stat().st_mode&0o777,0o600)

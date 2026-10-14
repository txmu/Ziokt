"""Signed Extensions against the six existing Core artifacts; never compiles."""
import os
from pathlib import Path
import secrets
import tempfile
import unittest
from ziokt.extensions import Extensions,feature_matrix,install
from ziokt.protocol import ProtocolError

ROOT=Path(os.environ.get('ZIOKT_EXTENSION_ROOT',Path(__file__).resolve().parents[2]/'Shadow6'))

class ZioktExtensions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.key=secrets.token_bytes(32);self.binding=install(ROOT,Path(self.temp.name)/'bundle',self.key)
        self.payload={'schema':'ziokt.extension-event.v1','kind':'zkn-gift','network_id':'default','content_digest':'sha256:'+'a'*64,'hops':2,'private':True,'free_forwarding':True}

    def test_six_existing_cores_authorize_real_isolated_signed_plugin(self):
        rows=feature_matrix(ROOT)
        self.assertEqual(len(rows),6)
        available=[r for r in rows if r['eligible']]
        if os.environ.get('ZIOKT_REQUIRE_EXTENSION_MATRIX')=='1': self.assertEqual(len(available),6,rows)
        if not available:self.skipTest('matching existing compiled extension artifacts unavailable')
        for row in available:
            with self.subTest(core=row['core']):
                result=Extensions(self.binding,self.key,row['core'],row['binary_digest'])(self.payload)
                self.assertEqual(result['result']['results'][0]['result']['allow'],True)

    def test_private_metadata_only_and_no_policy_fallback(self):
        rows=[r for r in feature_matrix(ROOT) if r['eligible']]
        if not rows:self.skipTest('matching existing compiled extension artifacts unavailable')
        row=rows[0];invoke=Extensions(self.binding,self.key,row['core'],row['binary_digest'])
        for payload in ({**self.payload,'recipient':'b'*64},{**self.payload,'free_forwarding':False},{**self.payload,'private':False},{**self.payload,'hops':1}):
            with self.assertRaises(ProtocolError):invoke(payload)
        plugin=Path(self.binding['bundle'])/'plugins/ziokt-policy/main.py'
        plugin.write_bytes(plugin.read_bytes()+b'\n# altered\n')
        with self.assertRaises(ProtocolError):invoke(self.payload)

    def test_wrong_owner_and_stale_core_are_rejected(self):
        with self.assertRaises(ProtocolError):Extensions(self.binding,secrets.token_bytes(32),'go','sha256:'+'0'*64)
        invoke=Extensions(self.binding,self.key,'go','sha256:'+'0'*64)
        with self.assertRaises(ProtocolError):invoke(self.payload)

import json
from pathlib import Path
import secrets
import tempfile
import unittest
from ziokt.ufsdcpm import IntegratedStorage,package_bytes,read_package
from ziokt.safefs import Vault
from ziokt.security import sign
from ziokt.protocol import ProtocolError,encoded

class IntegratedPackages(unittest.TestCase):
    def test_signature_manifest_ciphertext_and_native_storage_roundtrip(self):
        private=secrets.token_bytes(32);public=sign({},private,'test')['public_key']
        files={'bin/tool':b'example binary','docs/readme.txt':b'private metadata','empty':b''}
        blob=package_bytes('demo','1.0',files,['runtime'],private);manifest,restored=read_package(blob,public)
        self.assertEqual(restored,files);self.assertFalse(manifest['install_scripts'])
        with tempfile.TemporaryDirectory() as tmp:
            storage=IntegratedStorage(Vault(Path(tmp),'packages',secrets.token_bytes(32)));item=storage.publish_package('demo','1.0',files,[],private)
            self.assertTrue(item['native_integration']);self.assertEqual(storage.download_package(item['digest'],public)[1],files)
            self.assertNotIn(b'private metadata',storage.vault.blob(item['digest']))
        value=json.loads(blob);value['content']['bin/tool']=['YmFk']
        with self.assertRaises(ProtocolError):read_package(encoded(value),public)
        with self.assertRaises(ProtocolError):read_package(blob,'0'*64)
    def test_no_pickle_eval_traversal_or_path_collisions(self):
        key=secrets.token_bytes(32)
        for files in ({'../x':b'x'},{'a':b'x','a/b':b'x'},{'/absolute':b'x'}):
            with self.assertRaises(ProtocolError):package_bytes('demo','1',files,[],key)
        with self.assertRaises(ProtocolError):read_package(b'cos\nsystem\n(S"malicious"\ntR.','0'*64)

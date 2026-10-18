import hashlib
from pathlib import Path
import secrets
import tempfile
import unittest

from ziokt.chunkstore import ChunkStore,CHUNK_BYTES
from ziokt.safefs import Vault
from ziokt.protocol import ProtocolError,strict_json,encoded
from ziokt.security import sign
from ziokt.ufsdcpm import reference_package,verify_reference_package


def sha(data):return 'sha256:'+hashlib.sha256(data).hexdigest()


class ReferencePackages(unittest.TestCase):
    def test_streaming_signature_limits_lifetimes_and_no_execution(self):
        with tempfile.TemporaryDirectory() as root:
            store=ChunkStore(Vault(Path(root),'dcpm',b'a'*32))
            try:
                data=b'program'*5000;store.begin('source',len(data),sha(data),100)
                for pos,start in enumerate(range(0,len(data),CHUNK_BYTES)):
                    chunk=data[start:start+CHUNK_BYTES];store.put('source',pos,sha(chunk),chunk)
                ref=store.finish('source');obj=ref['manifest_digest']
                key=secrets.token_bytes(32);public=sign({},key,'test')['public_key']
                blob=reference_package(store,'demo','1.0.0',{'bin/program':obj},[],key)
                self.assertLess(len(blob),4096)
                report=verify_reference_package(store,blob,public)
                self.assertEqual(report['content_bytes'],len(data));self.assertFalse(report['execution_authorized'])
                with self.assertRaises(ProtocolError):verify_reference_package(store,blob,'0'*64)
                changed=strict_json(blob);changed['manifest']['payload']['version']='2.0.0'
                with self.assertRaises(ProtocolError):verify_reference_package(store,encoded(changed),public)
                with self.assertRaises(ProtocolError):reference_package(store,'demo','1',{'../escape':obj},[],key)
                holder=sha(blob);store.pin(holder,[obj]);store.release(obj,'source');store.gc()
                self.assertEqual(store.reference(obj)['reference_count'],1)
                self.assertEqual(verify_reference_package(store,blob,public)['files_verified'],1)
                store.unpin(holder);self.assertGreater(store.gc()['removed_chunks'],0)
                with self.assertRaises(ProtocolError):store.reference(obj)
            finally:store.close()

    def test_multiple_upload_leases_prevent_early_collection(self):
        with tempfile.TemporaryDirectory() as root:
            store=ChunkStore(Vault(Path(root),'ufs',b'b'*32))
            try:
                for name in ('first','second'):
                    store.begin(name,1,sha(b'x'),10);store.put(name,0,sha(b'x'),b'x');ref=store.finish(name)
                obj=ref['manifest_digest'];self.assertEqual(store.reference(obj)['reference_count'],2)
                store.release(obj,'first');store.gc();self.assertEqual(store.read(obj,0),b'x')
                store.release(obj,'second');self.assertEqual(store.gc()['removed_chunks'],1)
            finally:store.close()

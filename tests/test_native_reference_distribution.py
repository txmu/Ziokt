"""Real native dCPM admits signed references into the existing encrypted store."""
import hashlib
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from ziokt.chunkstore import ChunkStore,CHUNK_BYTES
from ziokt.safefs import Vault
from ziokt.ufsdcpm import reference_package

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'companions/ufsdcpm/src'))
PackageStore=importlib.import_module('dcpm_ufs_packages').PackageStore
sys.path.pop(0)


class NativeReferenceDistribution(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=ChunkStore(Vault(self.root/'objects','dcpm',b'd'*32));self.addCleanup(self.store.close)
        self.native=PackageStore(self.root/'native',reference_store=self.store)
        self.addCleanup(lambda:self.native.close())
        self.data=b'actual independently verified output\n'*1700
        digest='sha256:'+hashlib.sha256(self.data).hexdigest()
        self.store.begin('build',len(self.data),digest,3600)
        for position,start in enumerate(range(0,len(self.data),CHUNK_BYTES)):
            chunk=self.data[start:start+CHUNK_BYTES]
            self.store.put('build',position,'sha256:'+hashlib.sha256(chunk).hexdigest(),chunk)
        self.object=self.store.finish('build')['manifest_digest']

    def package(self,version='1'):
        return reference_package(self.store,'native-output',version,{'images/output.bin':self.object},[],self.native.private)

    def test_signature_native_index_retention_and_streamed_content(self):
        publication=self.native.admit(self.package())
        self.assertTrue(publication['durably_stored']);self.assertFalse(publication['installed'])
        self.assertEqual(publication['package_schema'],'ziokt.dcpm-package.v2')
        self.store.release(self.object,'build');self.store.gc()
        entries=list(self.native.content_files(publication['package_id'],publication['version_id']))
        self.assertEqual(entries[0][0],'images/output.bin')
        self.assertEqual(b''.join(entries[0][3]),self.data)
        self.assertEqual(self.native.blob(publication['package_id']),self.package())
        # Native descriptor is small and has no duplicate raw payload body.
        self.assertLess(len(self.native.blob(publication['package_id'])),4096)

    def test_prepared_reference_admission_resumes_after_storage_interruption(self):
        blob=self.package()
        with patch.object(self.store,'pin',side_effect=OSError('injected retention interruption')):
            with self.assertRaises(OSError):self.native.admit(blob)
        self.assertEqual(self.native.list(),[])
        self.assertEqual(self.native.db.execute('SELECT count(*) FROM reference_pending').fetchone()[0],1)
        self.native.close()
        self.native=PackageStore(self.root/'native',reference_store=self.store)
        self.assertEqual(len(self.native.list()),1)
        self.assertEqual(self.native.db.execute('SELECT count(*) FROM reference_pending').fetchone()[0],0)
        self.assertEqual(self.native.resume_pending(),[])

    def test_unsupported_reference_store_and_version_conflict_fail_explicitly(self):
        with tempfile.TemporaryDirectory() as other:
            native=PackageStore(other,trusted_publishers=[self.native.public])
            try:
                with self.assertRaisesRegex(PermissionError,'REFERENCE_STORE'):native.admit(self.package())
            finally:native.close()
        self.native.admit(self.package())
        changed=reference_package(self.store,'native-output','1',{'different.bin':self.object},[],self.native.private)
        with self.assertRaisesRegex(ValueError,'VERSION_CONFLICT'):self.native.admit(changed)


if __name__=='__main__':unittest.main()

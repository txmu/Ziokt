"""Native dCPM file install/activate/rollback with real encrypted source objects."""
import hashlib
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from ziokt.chunkstore import ChunkStore,CHUNK_BYTES
from ziokt.safefs import Vault
from ziokt.ufsdcpm import reference_package
from ziokt.protocol import ProtocolError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'companions/ufsdcpm/src'))
PackageStore=importlib.import_module('dcpm_ufs_packages').PackageStore
sys.path.pop(0)


class NativeFileInstall(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.objects=ChunkStore(Vault(self.root/'source','dcpm',b'k'*32));self.addCleanup(self.objects.close)
        self.native=PackageStore(self.root/'native',reference_store=self.objects);self.addCleanup(self.native.close)
        self.installer=self.native.file_installer(self.root/'installed')

    def publish(self,version,data):
        digest='sha256:'+hashlib.sha256(data).hexdigest();upload='source-'+version
        self.objects.begin(upload,len(data),digest,3600)
        for position,start in enumerate(range(0,len(data),CHUNK_BYTES)):
            chunk=data[start:start+CHUNK_BYTES];self.objects.put(upload,position,'sha256:'+hashlib.sha256(chunk).hexdigest(),chunk)
        obj=self.objects.finish(upload)['manifest_digest']
        blob=reference_package(self.objects,'firmware-demo',version,{'images/rootfs.img':obj},[],self.native.private)
        return self.native.admit(blob)

    def test_explicit_native_install_upgrade_rollback_and_offline_check(self):
        first=self.publish('1',b'original image'*10000);second=self.publish('2',b'updated image'*10000)
        package=first['package_id']
        with self.assertRaises(PermissionError):self.installer.install(package,first['version_id'])
        self.assertFalse((self.root/'installed'/package).exists())
        installed=self.installer.install(package,first['version_id'],allow=True)
        self.assertTrue(installed['installed']);self.assertFalse(installed['activated']);self.assertFalse(installed['execution_authorized'])
        with self.assertRaises(PermissionError):self.installer.activate(package,first['version_id'])
        self.installer.activate(package,first['version_id'],allow=True)
        self.assertTrue(self.installer.install(package,first['version_id'],allow=True)['activated'])
        self.installer.install(package,second['version_id'],allow=True)
        self.installer.activate(package,second['version_id'],allow=True)
        self.assertEqual(self.installer.active(package)['version'],'2')
        self.assertEqual(self.installer.rollback(package,allow=True)['version'],'1')
        # Installed verification does not need the source object store or a license server.
        self.native.reference_store=None
        self.assertEqual(self.installer.active(package)['version'],'1')
        self.assertEqual((Path(installed['directory'])/'images/rootfs.img').read_bytes(),b'original image'*10000)

    def test_tamper_and_revoked_publisher_block_activation_without_deleting_files(self):
        item=self.publish('1',b'checked bytes')
        installed=self.installer.install(item['package_id'],item['version_id'],allow=True)
        target=Path(installed['directory'])/'images/rootfs.img';target.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'CONTENT_CHANGED'):self.installer.activate(item['package_id'],item['version_id'],allow=True)
        self.assertTrue(target.exists());self.assertFalse((self.root/'installed'/item['package_id']/'active.json').exists())
        target.write_bytes(b'checked bytes');self.native.authorities.clear()
        with self.assertRaises(PermissionError):self.installer.activate(item['package_id'],item['version_id'],allow=True)
        self.assertTrue(target.exists())

    def test_symlink_version_root_rejected(self):
        item=self.publish('1',b'original')
        base=self.root/'installed'/item['package_id'];base.mkdir();outside=self.root/'outside';outside.mkdir();(base/'versions').symlink_to(outside,target_is_directory=True)
        with self.assertRaises((ProtocolError,ValueError,OSError)):self.installer.install(item['package_id'],item['version_id'],allow=True)
        self.assertEqual(list(outside.iterdir()),[])

    def test_missing_dependency_prevents_installation(self):
        item=self.publish('1',b'payload')
        _,manifest,_=self.native.validate(self.native.blob(item['package_id']))
        blob=reference_package(self.objects,'dependent','1',{'images/rootfs.img':manifest['files'][0]['object']},['missing-runtime'],self.native.private)
        dependent=self.native.admit(blob)
        with self.assertRaisesRegex(ValueError,'DEPENDENCY_NOT_INSTALLED'):
            self.installer.install(dependent['package_id'],dependent['version_id'],allow=True)
        self.assertFalse((self.root/'installed'/dependent['package_id']).exists())


if __name__=='__main__':unittest.main()

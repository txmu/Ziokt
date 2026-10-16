"""Product IntegratedSystem instances exchange signed packages over real UFS HTTP."""
import asyncio
import hashlib
import http.client
import importlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from urllib.parse import urlencode

from ziokt.protocol import make_private, ProtocolError
from ziokt.ufsdcpm import package_bytes
import test_ufs_native_http as native_http

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'companions/ufsdcpm/src'))
module=importlib.import_module('dcpm_ufs_integration')
sys.path.pop(0)


@unittest.skipUnless(os.open in os.supports_dir_fd and hasattr(os,'O_NOFOLLOW'), 'native UFS descriptor confinement unavailable on this platform')
class NativeUFSDCPMIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.systems=[]; self.tasks=[]
        self.password='native-integration-password-strong'
        self.source=await self.node('source')
        self.server=self.source.ufs_server
        self.port=self.server.server_port

    async def node(self,name,*,trusted=None,sources=None):
        root=self.root/name; root.mkdir()
        config={'p2p':{'enabled':False},'ufs':{'host':'127.0.0.1','port':0,'ssl':False,'upload':True,
            'auth':{'enabled':True,'users':{'admin':{'password':self.password,'role':'admin'}}}},
            'storage':{'cache':str(root/'cache'),'ufs_root':str(root/'files')},
            'logging':{'file':str(root/'native.log')},'packages':{'trusted_publishers':trusted or [],'http_sources':sources or []}}
        path=root/'config.json'; path.write_text(json.dumps(config)); make_private(path)
        system=module.IntegratedSystem(str(path)); self.systems.append(system)
        task=asyncio.create_task(system.start()); self.tasks.append(task)
        for _ in range(100):
            if system.running: return system
            if task.done(): await task
            await asyncio.sleep(0.01)
        raise AssertionError('native UFS startup timed out')

    async def asyncTearDown(self):
        for system in reversed(self.systems): await system.stop()
        for task in self.tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)

    call=native_http.NativeUFSHTTP.call
    authorization=native_http.NativeUFSHTTP.authorization
    authenticated=native_http.NativeUFSHTTP.authenticated

    async def test_two_product_nodes_signed_http_persistence_and_tamper_rejection(self):
        blob=package_bytes('native-demo','1',{'docs/hello.txt':b'actual-native-package'},[],self.source.package_store.private)
        status,_,body=self.authenticated('POST','/api/dcpm/publish',blob,**{'Content-Type':'application/octet-stream'})
        self.assertEqual(status,200,body); publication=json.loads(body)
        self.assertTrue(publication['durably_stored']); self.assertFalse(publication['chain_confirmed'])
        self.assertFalse(publication['network_published'])
        source_file=self.root/'native.zpkg'; source_file.write_bytes(blob); make_private(source_file)
        native_receipt=await self.source.publish_package(str(source_file),redundancy=2)
        self.assertFalse(native_receipt['replication_satisfied'])
        self.assertEqual(native_receipt['replica_count'],1)
        # One-shot product CLI must not bind a second listener or reset keys.
        config_path=self.root/'source/config.json'
        configured=json.loads(config_path.read_text()); configured['ufs']['port']=self.port
        config_path.write_text(json.dumps(configured)); make_private(config_path)
        import subprocess
        result=await asyncio.to_thread(subprocess.run,[sys.executable,str(ROOT/'companions/ufsdcpm/src/dcpm_ufs_integration.py'),
            '--config',str(config_path),'package','publish',str(source_file),'--redundancy','1'],
            cwd=ROOT,env=dict(os.environ,PYTHONPATH=str(ROOT)),capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('durably_stored',result.stdout)
        source={'url':'http://127.0.0.1:'+str(self.port),'username':'admin','password':self.password}
        target=await self.node('target',trusted=[self.source.package_store.public],sources=[source])
        package=await target.download_package(publication['package_id'],publication['version_id'])
        self.assertEqual(package.files,{'docs/hello.txt':b'actual-native-package'})
        self.assertEqual(target.package_store.blob(publication['package_id']),blob)
        # Stop the provider: the second product instance still retrieves its
        # independently persisted, reverified package without network success.
        await self.source.stop()
        again=await target.download_package(publication['package_id'],publication['version_id'])
        self.assertEqual(again.files,package.files)
        from dcpm_ufs_packages import PackageStore
        reopened=PackageStore(target.package_store.root,trusted_publishers=[self.source.package_store.public])
        try:
            self.assertEqual(reopened.public,target.package_store.public)
            self.assertEqual(reopened.blob(publication['package_id']),blob)
            digest=publication['sha256']; path=reopened.root/'objects'/digest
            path.write_bytes(blob[:-1]+bytes([blob[-1]^1]))
            with self.assertRaises(ValueError): reopened.blob(publication['package_id'])
        finally: reopened.close()

    async def test_wrong_publisher_version_conflict_unsigned_and_identity_mismatch(self):
        blob=package_bytes('signed','1',{'data':b'first'},[],self.source.package_store.private)
        publication=self.source.package_store.admit(blob)
        changed=package_bytes('signed','1',{'data':b'changed'},[],self.source.package_store.private)
        unknown=package_bytes('signed','2',{'data':b'unknown'},[],secrets.token_bytes(32))
        for malformed in (b'not-json',unknown,changed):
            status,_,_=self.authenticated('POST','/api/dcpm/publish',malformed,**{'Content-Type':'application/octet-stream'})
            self.assertIn(status,(400,403,409))
        other=package_bytes('other','1',{'data':b'other'},[],self.source.package_store.private)
        with self.assertRaises(ValueError): self.source.package_store.admit(other,expected_id='f'*64)
        self.assertEqual(self.source.package_store.blob(publication['package_id']),blob)
        self.assertEqual(len(self.source.package_store.list()),1)
        from dcpm_ufs_packages import PackageStore
        limited=PackageStore(self.root/'limited',trusted_publishers=[self.source.package_store.public],max_bytes=32)
        try:
            with self.assertRaises(ValueError): limited.admit(blob)
            self.assertEqual(limited.list(),[])
            self.assertEqual(list((limited.root/'objects').iterdir()),[])
        finally: limited.close()
        self.assertEqual(self.call('GET','/api/dcpm/packages')[0],401)
        self.server.accounts['admin']['role']='guest'
        self.assertEqual(self.authenticated('GET','/api/dcpm/packages')[0],403)
        with self.assertRaises(PermissionError): await self.source.install_package('f'*64)
        with self.assertRaises(PermissionError): await self.source.uninstall_package('test-system-package')


if __name__=='__main__': unittest.main()

"""Real native signing and installation; task receipts are explicit integration fixtures."""
import io
import json
from pathlib import Path
import tarfile
from unittest.mock import patch
from test_openci_http import HTTPTests
from test_openci_state import pipeline,task
from openci.artifacts import publish_outputs
from openci.client import Client
from openci.release import configure,ReleaseService
from openci.state import Error


class ReleaseTests(HTTPTests):
    def test_native_publish_recover_install_and_withdraw(self):
        config=self.root/'controller.json';config.write_bytes(self.config.read_bytes());config.chmod(0o600)
        configure(self.root,Path(__file__).resolve().parents[1]/'companions/ufsdcpm/src')
        settings=json.loads(config.read_text())
        import hashlib
        settings['principals']['verifier']={'role':'worker','worker':'node2','projects':['demo'],'token_sha256':hashlib.sha256(b'verifier-test').hexdigest()}
        self.config.write_text(json.dumps(settings))
        verifier=Client(self.owner.origin,'verifier-test')
        source=self.owner.upload('demo',self.source)
        tasks=[task('build'),task('verify',['build'],'trusted')]
        for entry in tasks:entry['outputs']=['firmware.bin']
        value=pipeline(tasks);value['source']=source
        pid=self.owner.request('POST','/v1/pipelines',value)['pipeline']
        archive=self.root/'payload.tar';data=b'real-test-firmware-payload'
        with tarfile.open(archive,'w') as output:
            entry=tarfile.TarInfo('firmware.bin');entry.size=len(data);output.addfile(entry,io.BytesIO(data))
        artifact=publish_outputs(self.owner,'demo',archive,['firmware.bin'],source,tasks[0]['image'])
        request={'pipeline':pid,'task':'build','name':'test-firmware','version':'1.0'}
        with self.assertRaises(Error):self.owner.request('POST','/v1/releases',request)
        for worker,pool,client in [('node1','community',self.worker),('node2','trusted',verifier)]:
            self.owner.request('POST','/v1/workers/approve',{'worker':worker,'arch':'x86_64','pool':pool,'cpu':1,'memory_mb':128,'slots':1,'projects':['demo']})
            claim=client.request('POST','/v1/claim',{})['assignment']
            client.request('POST','/v1/finish',{'pipeline':pid,'task':claim['task']['id'],'lease':claim['lease'],'exit_code':0,'artifact':artifact,'logs':source})
        self.owner.request('POST','/v1/verify',{'pipeline':pid,'task':'build','independent_task':'verify'})
        with self.assertRaises(Error):self.worker.request('POST','/v1/releases',request)
        # Failure after native publication must remain prepared and be recoverable.
        with patch.object(self.controller.state,'complete_release',side_effect=RuntimeError('injected interruption')):
            with self.assertRaises(RuntimeError):ReleaseService(self.controller).publish('owner',pid,'build','test-firmware','1.0')
        release=self.owner.request('POST','/v1/releases',request)
        self.assertEqual(release['state'],'published')
        self.assertNotIn('worker_attestations',release['request'])  # preserve legacy request identity
        self.assertTrue(release['publication']['release_signed'])
        self.assertFalse(release['publication']['corium_settled'])
        self.assertEqual(self.owner.request('POST','/v1/releases',request)['id'],release['id'])
        installed=ReleaseService(self.controller).install(release['id'],self.root/'installed',activate=True)
        self.assertFalse(installed['execution_authorized'])
        provenance=json.loads((Path(installed['directory'])/'provenance.json').read_text())
        self.assertNotIn('worker_attestations',provenance['openciVerification'])
        self.assertTrue(any(p.read_bytes()==data for p in (self.root/'installed').rglob('firmware.bin')))
        withdrawn=self.owner.request('POST','/v1/releases/withdraw',{'release':release['id']})
        self.assertEqual(withdrawn['state'],'withdrawn')
        self.assertTrue(any(p.read_bytes()==data for p in (self.root/'installed').rglob('firmware.bin')))
        with self.assertRaises(Error):ReleaseService(self.controller).install(release['id'],self.root/'other-install')

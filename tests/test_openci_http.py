"""Actual loopback Controller HTTP -> Content Fabric -> encrypted native chunks."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from openci.client import Client
from openci.controller import Controller, Server, handler
from openci.state import Error
from test_openci_state import pipeline


class HTTPTests(unittest.TestCase):
    def test_rebuild_endpoint_scope_and_no_self_approved_resources(self):
        from test_openci_state import task
        ref=self.owner.upload('demo',self.source)
        spec=task();spec['outputs']=['image']
        value=pipeline([spec]);value['source']=ref
        pid=self.owner.request('POST','/v1/pipelines',value)['pipeline']
        request={'pipeline':pid,'task':'build','nonce':'replicas'}
        with self.assertRaises(Error) as denied:self.other.request('POST','/v1/rebuilds',request)
        self.assertEqual(denied.exception.status,403)
        with self.assertRaises(Error):self.worker.request('POST','/v1/workers/build-profile',{})
        self.owner.request('POST','/v1/workers/approve',{'worker':'node1','arch':'x86_64','pool':'community','cpu':1,'memory_mb':128,'slots':1,'projects':['demo']})
        self.worker.request('POST','/v1/workers/presence',{'images':[spec['image']]})
        result=self.owner.request('POST','/v1/rebuilds',request)
        self.assertEqual(result['state'],'disabled')
        self.assertEqual(result['selection']['workers'],[])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        principals = {
            'owner': {'role':'admin','projects':[], 'token_sha256':hashlib.sha256(b'owner-test').hexdigest()},
            'worker': {'role':'worker','worker':'node1','projects':['demo'],'token_sha256':hashlib.sha256(b'worker-test').hexdigest()},
            'other': {'role':'submit','projects':['other'],'token_sha256':hashlib.sha256(b'other-test').hexdigest()},
        }
        self.config = self.root/'config.json'; self.config.write_text(json.dumps({'principals':principals}));self.config.chmod(0o600)
        self.controller = Controller(self.root/'state', self.config)
        self.server = Server(('127.0.0.1',0),handler(self.controller))
        self.thread = threading.Thread(target=self.server.serve_forever); self.thread.start()
        def cleanup():
            self.server.shutdown();self.server.server_close();self.thread.join();self.controller.close()
        self.addCleanup(cleanup)
        origin = 'http://127.0.0.1:'+str(self.server.server_port)
        self.owner, self.worker, self.other = [Client(origin,token) for token in ('owner-test','worker-test','other-test')]
        self.source = self.root/'source.tar';self.source.write_bytes(b'real-source-bytes'*2000)

    def test_native_bytes_pipeline_assignment_failure_and_scope(self):
        ref = self.owner.upload('demo',self.source)
        self.assertTrue(ref['object'].startswith('cf1-'))
        out = self.root/'roundtrip';self.owner.download('demo',ref,out)
        self.assertEqual(out.read_bytes(), self.source.read_bytes())
        value = pipeline();value['source'] = ref
        pid = self.owner.request('POST','/v1/pipelines',value)['pipeline']
        with self.assertRaises(Error) as denied:self.other.request('GET','/v1/pipelines/'+pid)
        self.assertEqual(denied.exception.status,403)
        with self.assertRaises(Error):self.other.download('other',ref,self.root/'stolen')
        self.owner.request('POST','/v1/workers/approve',{'worker':'node1','arch':'x86_64','pool':'community','cpu':1,'memory_mb':128,'slots':1,'projects':['demo']})
        claim = self.worker.request('POST','/v1/claim',{})['assignment']
        self.assertEqual(claim['pipeline'],pid)
        with self.assertRaises(Error):self.worker.request('POST','/v1/workers/approve',{})
        artifact = self.worker.upload('demo', self.source)
        receipt = {'pipeline':pid,'task':'build','lease':claim['lease'],'exit_code':0,'artifact':artifact,'logs':artifact}
        self.assertEqual(self.worker.request('POST','/v1/finish',receipt)['state'],'completed')
        self.assertTrue(self.worker.request('POST','/v1/finish',receipt)['duplicate'])
        inspected = self.owner.request('GET','/v1/pipelines/'+pid)
        self.assertEqual(inspected['state'],'completed');self.assertEqual(inspected['release'],'unpublished')
        # API storage is native AEAD chunks, never a parallel plaintext CAS.
        self.assertFalse(any(self.source.read_bytes() in p.read_bytes() for p in (self.root/'state/content/accounts').rglob('*') if p.is_file()))

    def test_revoked_credentials_and_false_source_digest(self):
        ref = self.owner.upload('demo',self.source)
        value = pipeline();value['source'] = {**ref,'digest':'sha256:'+'0'*64}
        with self.assertRaises(Error) as rejected:self.owner.request('POST','/v1/pipelines',value)
        self.assertEqual(rejected.exception.code,'REFERENCE_MISMATCH')
        settings = json.loads(self.config.read_text());del settings['principals']['worker'];self.config.write_text(json.dumps(settings))
        with self.assertRaises(Error) as rejected:self.worker.request('POST','/v1/claim',{})
        self.assertEqual(rejected.exception.status,401)

    def test_matching_empty_artifacts_cannot_verify_declared_outputs(self):
        import copy
        from test_openci_state import task
        empty=self.root/'empty.tar';empty.write_bytes(b'\0'*10240)
        reference=self.owner.upload('demo',empty)
        first=task('build');first['outputs']=['expected.bin']
        second=task('verify',['build'],'trusted');second['outputs']=['expected.bin']
        value=pipeline([first,second]);value['source']=reference
        pid=self.owner.request('POST','/v1/pipelines',value)['pipeline']
        settings=json.loads(self.config.read_text())
        settings['principals']['verifier']={'role':'worker','worker':'node2','projects':['demo'],'token_sha256':hashlib.sha256(b'verifier-test').hexdigest()}
        self.config.write_text(json.dumps(settings))
        verifier=Client(self.owner.origin,'verifier-test')
        for worker,pool,client in [('node1','community',self.worker),('node2','trusted',verifier)]:
            self.owner.request('POST','/v1/workers/approve',{'worker':worker,'arch':'x86_64','pool':pool,'cpu':1,'memory_mb':128,'slots':1,'projects':['demo']})
            claim=client.request('POST','/v1/claim',{})['assignment']
            client.request('POST','/v1/finish',{'pipeline':pid,'task':claim['task']['id'],'lease':claim['lease'],'exit_code':0,'artifact':reference,'logs':reference})
        with self.assertRaises(Error) as missing:
            self.owner.request('POST','/v1/verify',{'pipeline':pid,'task':'build','independent_task':'verify'})
        self.assertEqual(missing.exception.code,'OUTPUT_MISSING')
        self.assertTrue(all(row['verification'] is None for row in self.owner.request('GET','/v1/pipelines/'+pid)['tasks']))

    def test_artifact_set_reuses_native_file_objects_without_storing_archive(self):
        import io,tarfile
        from openci.artifacts import publish_outputs
        source=self.owner.upload('demo',self.source)
        value=pipeline();value['source']=source;value['tasks'][0]['outputs']=['result.json']
        pid=self.owner.request('POST','/v1/pipelines',value)['pipeline']
        archive=self.root/'outputs.tar';data=b'{"result":42}'
        with tarfile.open(archive,'w') as output:
            entry=tarfile.TarInfo('result.json');entry.size=len(data);output.addfile(entry,io.BytesIO(data))
        artifact=publish_outputs(self.owner,'demo',archive,['result.json'],source,value['tasks'][0]['image'])
        self.owner.request('POST','/v1/workers/approve',{'worker':'node1','arch':'x86_64','pool':'community','cpu':1,'memory_mb':128,'slots':1,'projects':['demo']})
        claim=self.worker.request('POST','/v1/claim',{})['assignment']
        self.worker.request('POST','/v1/finish',{'pipeline':pid,'task':'build','lease':claim['lease'],'exit_code':0,'artifact':artifact,'logs':source})
        # A deduplicated object's original MIME hint is not its format authority.
        with self.controller.fabric.transaction():
            row=self.controller.fabric.db.execute('SELECT metadata FROM objects WHERE id=?',(artifact['object'],)).fetchone()
            meta=json.loads(row[0]);meta['mime']='application/octet-stream'
            self.controller.fabric.db.execute('UPDATE objects SET metadata=? WHERE id=?',(json.dumps(meta),artifact['object']))
        checked=self.controller.check_outputs(self.controller.state.inspect(pid),'build')
        self.assertEqual(checked[0]['size'],len(data))
        destination=self.root/'downloaded-result.json';self.owner.download_artifact_file('demo',artifact,'result.json',destination)
        self.assertEqual(destination.read_bytes(),data)
        digest='sha256:'+hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(self.controller.fabric.db.execute("SELECT count(*) FROM objects WHERE json_extract(metadata,'$.digest')=?",(digest,)).fetchone()[0],0)


if __name__=='__main__': unittest.main()

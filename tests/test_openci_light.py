"""Real admission, task leasing, integrity and executor-boundary regressions."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_openci_http as http_fixture
from test_openci_state import pipeline,task
from openci.state import Error
from openci import light
from openci.quorum import approve


class LightTests(unittest.TestCase):
    def setUp(self):
        http_fixture.HTTPTests.setUp(self)
        self.compiler=self.root/'compiler';self.compiler.mkdir()
        targets={}
        for arch in ('x86_64','aarch64'):
            files={}
            for extension in ('.js','.wasm'):
                name=arch+extension;raw=b'fixture-integrity-bytes'
                (self.compiler/name).write_bytes(raw);files[name]=hashlib.sha256(raw).hexdigest()
            targets[arch]={'files':files,'image':'openci/tcc-wasm-'+arch+'@sha256:'+'a'*64}
        manifest={'schema':'openci.light-compiler.v1','targets':targets}
        raw=json.dumps(manifest).encode();(self.compiler/'manifest.json').write_bytes(raw)
        config=json.loads(self.config.read_text());config['light_compile']={'compiler_root':str(self.compiler),'manifest_sha256':hashlib.sha256(raw).hexdigest(),'cross_compile':False}
        self.config.write_text(json.dumps(config));self.images={arch:value['image'] for arch,value in targets.items()}
        self.controller.state.approve_worker('owner','node1',arch='x86_64',pool='community',cpu=1,memory_mb=64,slots=1,projects=['demo'])
        approve(self.controller.state,'owner','node1','domain1',[self.images['x86_64'],self.images['aarch64']],'sha256:'+'e'*64)
        self.controller.state.approve_receipt_key('owner','node1','d'*64,'sha256:'+'f'*64)

    def submit_light(self,target='x86_64',nonce='light'):
        spec=task();spec.update(executor='light-c',image=self.images[target],argv=['light-c',target,'unit.i','unit.o'],outputs=['unit.o'],memory_mb=64,timeout=20)
        return self.controller.state.submit('owner',pipeline([spec],nonce=nonce))['pipeline']

    def test_architecture_rejection_cannot_claim_or_consume_task(self):
        pid=self.submit_light()
        with patch('openci.light.platform.machine',return_value='x86_64'):
            for invalid in (None,False,0,'',[],{}):
                with self.subTest(invalid=invalid),self.assertRaises(Error):self.worker.request('POST','/v1/light/claim',{'architecture':invalid})
                self.assertEqual(self.controller.state.inspect(pid)['tasks'][0]['state'],'queued')
            with self.assertRaises(Error) as denied:self.worker.request('POST','/v1/light/claim',{'architecture':'aarch64'})
            self.assertEqual(denied.exception.code,'LIGHT_ARCH_MISMATCH')
            self.assertEqual(self.controller.state.inspect(pid)['tasks'][0]['state'],'queued')
            self.assertIsNone(self.worker.request('POST','/v1/claim',{})['assignment'])
            assignment=self.worker.request('POST','/v1/light/claim',{'architecture':'x86_64'})['assignment']
            self.assertEqual(assignment['pipeline'],pid)
            self.assertEqual(assignment['task']['executor'],'light-c')

    def test_cross_compile_is_explicit_and_does_not_change_host_architecture(self):
        self.submit_light('aarch64')
        with patch('openci.light.platform.machine',return_value='x86_64'):
            self.assertIsNone(self.worker.request('POST','/v1/light/claim',{'architecture':'x86_64'})['assignment'])
            config=json.loads(self.config.read_text());config['light_compile']['cross_compile']=True;self.config.write_text(json.dumps(config))
            assignment=self.worker.request('POST','/v1/light/claim',{'architecture':'x86_64'})['assignment']
            self.assertEqual(assignment['task']['arch'],'x86_64')
            self.assertEqual(assignment['task']['argv'][1],'aarch64')

    def test_compiler_tampering_and_unapproved_principals_fail_closed(self):
        with patch('openci.light.platform.machine',return_value='x86_64'):
            light.asset(self.controller,'x86_64.wasm')
            (self.compiler/'x86_64.wasm').write_bytes(b'changed')
            with self.assertRaises(Error) as changed:light.asset(self.controller,'x86_64.wasm')
            self.assertEqual(changed.exception.code,'LIGHT_COMPILER_INTEGRITY')
            with self.assertRaises(Error):self.owner.request('POST','/v1/light/claim',{'architecture':'x86_64'})
            with self.assertRaises(Error):light.asset(self.controller,'../controller.json')

    def test_unsupported_or_unbounded_light_tasks_are_rejected_before_queue(self):
        for change in ({'timeout':21},{'cpu':2},{'argv':['light-c','x86_64','unit.i','execute']},{'memory_mb':128},{'outputs':['other.o']}):
            value=task();value.update(executor='light-c',image=self.images['x86_64'],argv=['light-c','x86_64','unit.i','unit.o'],outputs=['unit.o'],memory_mb=64,timeout=20);value.update(change)
            with self.subTest(change=change),self.assertRaises(Error):self.controller.state.submit('owner',pipeline([value]))

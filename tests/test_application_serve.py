"""Actual app-serve subprocess, real math implementation and helper IPC lifecycle.

The pinned helper is an IPC fixture, not an ETP native-network replacement.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest
from ziokt.cli import write_exclusive,write_binary_exclusive
from ziokt.protocol import encoded
from ziokt.community import create_policy,RIGHTS
from ziokt.security import sign
from ziokt.ano import ZDANumber

ROOT=Path(__file__).resolve().parents[1]

class ApplicationServeTests(unittest.TestCase):
    def routes(self,root):
        seed=secrets.token_bytes(32);public=sign({},seed,'test')['public_key']
        policy=root/'policy.json';write_exclusive(policy,create_policy(seed,'apps',{public:sorted(RIGHTS)}))
        for name,value in [('signing',seed),('encryption',secrets.token_bytes(32)),('application',secrets.token_bytes(32))]:write_binary_exclusive(root/(name+'.key'),value)
        bridge=root/'bridge.json';write_exclusive(bridge,{'schema':'ziokt.companion-bridge.v1','application':'zda','community_root':str(root/'community'),'owner':public,'policy':str(policy),'signing_key':str(root/'signing.key'),'encryption_key':str(root/'encryption.key'),'application_key':str(root/'application.key')})
        binary=root/'ipc-fixture';config=root/'etp.json';write_exclusive(config,{})
        binary.write_text('''#!/usr/bin/env python3
import json,sys,os
for line in sys.stdin:
 r=json.loads(line)
 if r['method']=='etp.shutdown':
  open(sys.argv[1]+'.stopped','w').write(str(os.getpid()));break
 print(json.dumps({'id':r['id'],'ok':True,'result':{'schema':'ziokt.etp-forum-identity.v1','name':r['params']['name'],'author_id':format(os.getpid(),'064x')}}),flush=True)
''');binary.chmod(0o700)
        path=root/'router.json';write_exclusive(path,{'schema':'ziokt.application-router.v1','components':{'zda':{'config':str(bridge),'methods':['ano.calculate','ano.defence']},'etp':{'binary':str(binary),'digest':'sha256:'+hashlib.sha256(binary.read_bytes()).hexdigest(),'config':str(config),'methods':['etp.forum.identity']}}})
        return path,config
    def test_real_serve_math_reuses_child_and_eof_requests_graceful_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path,config=self.routes(root)
            process=subprocess.Popen([sys.executable,'-m','ziokt','companion','app','serve','--bridge-config',str(path)],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.addCleanup(lambda: process.kill() if process.poll() is None else None)
            requests=[{'target':'etp','method':'etp.forum.identity','params':{'name':'alice'}},{'target':'zda','method':'ano.calculate','params':{'kind':'zda','operation':'add','left':ZDANumber(1).document(),'right':ZDANumber(2).document()}},{'target':'zda','method':'ano.defence','params':{'evidence':{'signature':True,'authorization':None},'required':['signature','authorization']}},{'target':'etp','method':'etp.forum.identity','params':{'name':'alice'}},{'target':'etp','method':'etp.forum.publish','params':{'topic':'not-granted','content':'text','author':None}}]
            stdout,stderr=process.communicate(b''.join(encoded(item)+b'\n' for item in requests),timeout=15)
            self.assertEqual(process.returncode,0,stderr.decode());rows=[json.loads(line) for line in stdout.splitlines()];self.assertEqual(len(rows),5)
            self.assertEqual(rows[1]['result']['result'],ZDANumber(3).document());self.assertEqual(rows[2]['result']['decision'],'hold')
            self.assertEqual(rows[0]['result']['author_id'],rows[3]['result']['author_id'])
            self.assertEqual(rows[4]['error']['code'],'POLICY_DENIED')
            pid=int(rows[0]['result']['author_id'],16);self.assertEqual(int(Path(str(config)+'.stopped').read_text()),pid)
            with self.assertRaises(ProcessLookupError):os.kill(pid,0)
    def test_bounded_frames_and_invalid_json_return_typed_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,_=self.routes(Path(tmp));payload=b'{}\n'+b'x'*131073+b'\n'
            result=subprocess.run([sys.executable,'-m','ziokt','companion','app','serve','--bridge-config',str(path)],cwd=ROOT,input=payload,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr.decode());rows=[json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual([row['error']['code'] for row in rows],['INVALID_REQUEST','REQUEST_LIMIT'])

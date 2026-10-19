"""Three independent OS processes, TCP, distinct WAL databases and vaults.

Bounded data only; full stress and browser matrices run in dedicated CI jobs.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError

from ziokt.content_fabric import Fabric


class MultiNodeTests(unittest.TestCase):
    def test_real_partition_restart_resume_and_tombstone(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);keys=[];ports=[];processes={};configs=[]
            # Reserve ephemeral ports without starting any native compiler or daemon.
            import socket
            for i in range(3):
                node=Fabric(root/str(i));keys.append(node.public);node.close()
                with socket.socket() as sock:sock.bind(('127.0.0.1',0));ports.append(sock.getsockname()[1])
            token='a'*48
            peers={str(i):{'url':f'http://127.0.0.1:{ports[i]}','public_key':keys[i],'token':token,'groups':['books.open']} for i in range(3)}
            scopes=['content:read','content:write','content:replicate','content:admin','library:read','library:write','netnews:read','netnews:write']
            for i in range(3):
                cfg=root/(str(i)+'.json');cfg.write_text(json.dumps({'root':str(root/str(i)),'port':ports[i],'tokens':[{'account':'alice','token':token,'scopes':scopes}],'peers':peers}));cfg.chmod(0o600);configs.append(cfg)
            def start(i):
                proc=subprocess.Popen([sys.executable,'-m','ziokt.content_server','--config',str(configs[i])],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                processes[i]=proc
                if not select.select([proc.stdout],[],[],8)[0]:raise AssertionError('node did not start')
                line=proc.stdout.readline()
                if not line:raise AssertionError(proc.stderr.read())
                self.assertEqual(json.loads(line)['node'],keys[i])
            def stop(i):
                proc=processes.pop(i,None)
                if proc:
                    proc.terminate();proc.wait(timeout=5);proc.stdout.close();proc.stderr.close()
            def call(i,op,args=None):
                with urlopen(Request(f'http://127.0.0.1:{ports[i]}/api',data=json.dumps({'operation':op,'arguments':args or {}}).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}),timeout=10) as response:return json.load(response)
            def synchronize(target,source):
                for _ in range(20):
                    result=call(target,'federation.sync',{'peer':str(source)})
                    if not result['has_more']:return
                raise AssertionError('unexpected unbounded sync')
            try:
                for i in range(3):start(i);call(i,'netnews.group.create',{'name':'books.open'})
                data=b'An original CC0 sample.\n'*2300
                digest='sha256:'+hashlib.sha256(data).hexdigest()
                call(0,'content.upload.begin',{'upload':'book-upload','size':len(data),'digest':digest,'mime':'text/plain'})
                for position,start_byte in enumerate(range(0,len(data),16384)):call(0,'content.upload.put',{'upload':'book-upload','position':position,'data':base64.b64encode(data[start_byte:start_byte+16384]).decode()})
                obj=call(0,'content.upload.finish',{'upload':'book-upload'})
                call(0,'library.publish',{'metadata':{'id':'open-book','work_id':'work','edition_id':'original','file_id':obj['id'],'title':'Sample','authors':['Test author'],'license':'CC0-1.0','visibility':'public'}})
                synchronize(1,0);synchronize(2,1)
                self.assertEqual(len(call(2,'library.search',{})['items']),1)
                first=call(1,'library.download',{'book':'open-book','sources':['0']});self.assertEqual(first['state'],'complete',first)
                partial=call(2,'library.download',{'book':'open-book','sources':['0'],'max_chunks':1})
                self.assertEqual(partial['received_chunks'],1)
                # The original source now has corrupted ciphertext; C rejects it and
                # takes the next verified chunk from B over the real network.
                for chunk in (root/'0'/'accounts').glob('*/chunks-content/data/*'):
                    chunk.write_bytes(b'corrupted source ciphertext')
                repaired=call(2,'library.download',{'book':'open-book','sources':['0','1'],'max_chunks':1})
                self.assertEqual(repaired['received_chunks'],2)
                self.assertTrue(repaired['failures'])
                stop(2);start(2)  # process death, retain sparse encrypted chunks
                stop(0)  # original source offline; B must serve actual cached bytes
                recovered=call(2,'library.download',{'book':'open-book','sources':['0','1']})
                self.assertEqual(recovered['state'],'complete')
                self.assertTrue(call(2,'content.object.verify',{'id':obj['id']})['verified'])
                call(1,'netnews.post',{'groups':['books.open'],'subject':'During partition','body':'Persisted while A is offline','message_id':'<partition@test.example>'})
                synchronize(2,1)
                self.assertEqual(len(call(2,'netnews.articles',{'group':'books.open'})['items']),1)
                start(0);synchronize(0,1)
                self.assertEqual(len(call(0,'netnews.articles',{'group':'books.open'})['items']),1)
                call(0,'content.withdraw',{'id':'open-book'});synchronize(1,0);synchronize(2,1)
                self.assertEqual(call(2,'library.search',{})['items'],[])
                # Replayed complete log does not reintroduce withdrawn book.
                synchronize(2,0);self.assertEqual(call(2,'library.search',{})['items'],[])
            finally:
                for i in list(processes):stop(i)


if __name__=='__main__':unittest.main()

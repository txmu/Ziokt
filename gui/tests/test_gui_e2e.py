"""Real HTTP GUI adapter regression; browser clicks run in tools/gui_browser_smoke.cjs."""
import base64
import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ci.gui_fixture import configuration
from ziokt.gateway import Gateway,Server,handler


class RealGuiIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.gateway=Gateway(configuration(self.tmp.name));self.addCleanup(self.gateway.close)
        self.server=Server(('127.0.0.1',0),handler(self.gateway));threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)

    def request(self,path,payload=None,token='gui-ci-owner-token',origin=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        headers={'Authorization':'Bearer '+token}
        if origin:headers['Origin']=origin
        if payload is not None:headers['Content-Type']='application/json'
        c.request('POST' if payload is not None else 'GET',path,json.dumps(payload) if payload is not None else None,headers)
        r=c.getresponse();status=r.status;body=json.loads(r.read());c.close();return status,body

    def call(self,name,args,confirm=True,key='gui-integration-key'):
        status,result=self.request('/api/gateway/tools/call',{'name':name,'arguments':{'params':args},'confirm':confirm,'idempotency_key':key})
        self.assertEqual(status,200,result);self.assertFalse(result['isError'],result)
        return result['structuredContent']

    def test_auth_confirmation_and_actual_encrypted_object(self):
        self.assertEqual(self.request('/api/gateway/tools',token='invalid')[0],401)
        self.assertEqual(self.request('/api/gateway/tools',origin='https://untrusted.example')[0],403)
        status,catalog=self.request('/api/gateway/tools');self.assertEqual(status,200)
        self.assertIn('safefs_object_begin',{t['name'] for t in catalog['tools']})
        self.assertEqual(self.request('/api/gateway/tools/call',{'name':'safefs_object_begin','arguments':{'params':{}},'confirm':False})[0],409)
        data=b'real GUI bytes\x00\xff'*1200;sha=lambda b:'sha256:'+hashlib.sha256(b).hexdigest()
        self.call('safefs_object_begin',{'upload':'test','size':len(data),'digest':sha(data),'ttl':3600},key='gui-begin-key-001')
        for i,start in enumerate(range(0,len(data),16384)):
            chunk=data[start:start+16384]
            self.call('safefs_object_chunk_put',{'upload':'test','position':i,'digest':sha(chunk),'data_base64':base64.b64encode(chunk).decode()},key=('gui-chunk-key-'+str(i)).ljust(16,'x'))
        receipt=self.call('safefs_object_finish',{'upload':'test'},key='gui-finish-key-01')
        output=b''
        for i in range((len(data)+16383)//16384):
            item=self.call('safefs_object_chunk_get',{'object':receipt['manifest_digest'],'position':i},confirm=False)
            output+=base64.b64decode(item['data_base64'])
        self.assertEqual(output,data);self.assertEqual(receipt['digest'],sha(data))

if __name__=='__main__':unittest.main()

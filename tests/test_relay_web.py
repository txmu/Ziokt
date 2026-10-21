"""Actual authenticated HTTP carrying real socket bytes, no native deployment claim."""
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from ziokt.relay_web import RelayService,RelayServer


class RelayWebTests(unittest.TestCase):
    def setUp(self):
        area=tempfile.TemporaryDirectory();self.addCleanup(area.cleanup)
        self.config=Path(area.name)/'relay.json';self.token='a'*48
        self.settings={'schema':'ziokt.browser-relay.v1','origins':['https://people.example'],
                       'principals':{'phone':{'token_sha256':hashlib.sha256(self.token.encode()).hexdigest()}}}
        self.save();self.streams=[]
        def connector():
            external,internal=socket.socketpair();external.settimeout(2);self.streams.append(external);return internal
        self.service=RelayService(self.config,connector)
        self.server=RelayServer(('127.0.0.1',0),self.service)
        thread=threading.Thread(target=self.server.serve_forever);thread.start()
        def cleanup():
            self.server.shutdown();self.server.server_close();thread.join();self.service.close()
            for stream in self.streams:stream.close()
        self.addCleanup(cleanup)
        self.origin='http://127.0.0.1:'+str(self.server.server_port)

    def save(self):self.config.write_text(json.dumps(self.settings));self.config.chmod(0o600)

    def request(self,operation,body,token=None,origin='https://people.example'):
        req=Request(self.origin+'/relay/v1/'+operation,json.dumps(body).encode(),
                    {'Content-Type':'application/json','Authorization':'Bearer '+(token or self.token),'Origin':origin},method='POST')
        with urlopen(req,timeout=5) as response:return json.load(response)

    def test_real_http_written_bytes_and_idempotent_open(self):
        opened=self.request('open',{});session=opened['session']
        self.assertEqual(self.request('open',{})['session'],session)
        self.assertEqual(len(self.streams),1)
        frame={'sequence':0,'kind':'data','data':'c2VjcmV0'}
        written=self.request('write',{'session':session,'frame':frame})
        self.assertEqual(self.streams[0].recv(64),b'secret')
        self.assertFalse(written['useful_work_verified'])
        self.assertTrue(self.request('write',{'session':session,'frame':frame})['duplicate'])
        self.assertEqual(self.request('close',{'session':session})['state'],'closed')

    def test_origin_token_revocation_and_session_scoping(self):
        with self.assertRaises(HTTPError) as denied:self.request('open',{},origin='https://evil.example')
        self.assertEqual(denied.exception.code,403);denied.exception.close()
        with self.assertRaises(HTTPError) as denied:self.request('open',{},token='b'*48)
        self.assertEqual(denied.exception.code,401);denied.exception.close()
        session=self.request('open',{})['session']
        with self.assertRaises(HTTPError) as denied:self.request('read',{'session':'f'*48})
        self.assertEqual(denied.exception.code,409);denied.exception.close()
        self.settings['principals']['phone']['token_sha256']=hashlib.sha256(('b'*48).encode()).hexdigest();self.save()
        with self.assertRaises(HTTPError) as denied:self.request('read',{'session':session})
        self.assertEqual(denied.exception.code,401);denied.exception.close()
        self.assertEqual(self.service.sessions,{})

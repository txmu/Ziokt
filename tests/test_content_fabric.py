"""Real filesystem and protocol regression tests; no fake network backends."""
import base64
import hashlib
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError

from ziokt.content_fabric import Fabric,isbn,merkle_verify
from ziokt.content_api import invoke
from ziokt.content_server import server,download,sync
from ziokt.netnews_nntp import server as nntp_server


def digest(data):return 'sha256:'+hashlib.sha256(data).hexdigest()


class FabricTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.fabric=Fabric(self.root/'node')
    def tearDown(self):self.fabric.close();self.temp.cleanup()
    def upload(self,data=b'Hello library',name='upload',owner='alice'):
        self.fabric.begin(owner,name,len(data),digest(data),'text/plain')
        for position,start in enumerate(range(0,len(data),16384)):self.fabric.put(owner,name,position,data[start:start+16384])
        return self.fabric.finish(owner,name)
    def book(self,obj,visibility='private',bid='book'):
        return self.fabric.create_book('alice',{'id':bid,'work_id':'work','edition_id':'edition','file_id':obj['id'],'title':'Open book','authors':['Alice'],'license':'CC0-1.0','visibility':visibility})
    def test_persistence_dedup_and_isolation(self):
        data=b'a'*20000;first=self.upload(data);second=self.upload(data,'second')
        self.assertEqual(first['id'],second['id']);self.book(first)
        self.assertEqual(len(self.fabric.search('bob')['items']),0)
        with self.assertRaises(PermissionError):self.fabric.read_chunk('bob',first['id'],0)
        self.assertEqual(self.fabric.verify_object('alice',first['id'])['size'],len(data))
        self.fabric.close();self.fabric=Fabric(self.root/'node')
        self.assertEqual(self.fabric.read_chunk('alice',first['id'],0),data[:16384])
        self.assertEqual(len(self.fabric.search('alice')['items']),1)
        self.assertFalse(self.fabric.export()['events'])
    def test_sparse_resume_proof_and_corruption(self):
        data=b'a'*16384+b'b'*19
        self.fabric.begin('alice','upload',len(data),digest(data),'text/plain')
        self.fabric.put('alice','upload',1,data[16384:])
        self.fabric.close();self.fabric=Fabric(self.root/'node')
        self.assertEqual(self.fabric.upload_status('alice','upload')['next_missing'],0)
        with self.assertRaises(Exception):self.fabric.finish('alice','upload')
        self.fabric.put('alice','upload',0,data[:16384]);obj=self.fabric.finish('alice','upload')
        merkle_verify(data[:16384],0,self.fabric.chunk_proof('alice',obj['id'],0),obj['merkle_root'])
        with self.assertRaises(ValueError):merkle_verify(b'corrupt',0,self.fabric.chunk_proof('alice',obj['id'],0),obj['merkle_root'])
        with self.fabric.store('alice') as store:
            path=next(store.data.iterdir());path.write_bytes(b'damaged')
        with self.assertRaises(Exception):self.fabric.verify_object('alice',obj['id'])
    def test_signatures_deletion_and_replay(self):
        self.fabric.create_group('alice','books.open')
        post=self.fabric.post('alice',['books.open'],'A','hello',message_id='<a@example.test>')
        self.assertTrue(self.fabric.post('alice',['books.open'],'A','hello',message_id='<a@example.test>')['duplicate'])
        other=Fabric(self.root/'other',peers={self.fabric.public:{'groups':['books.open']}})
        try:
            other.create_group('bob','books.open')
            events=self.fabric.export()['events'];self.assertEqual(other.ingest(events)['accepted'],1)
            self.assertEqual(other.ingest(events)['accepted'],0)
            self.fabric.withdraw('alice',post['id']);other.ingest(self.fabric.export()['events'])
            self.assertEqual(other.articles('bob','books.open')['items'],[])
            other.ingest(events);self.assertEqual(other.articles('bob','books.open')['items'],[])
            bad=json.loads(json.dumps(events));bad[0]['payload']['body']['body']='tampered'
            with self.assertRaises(Exception):other.ingest(bad)
        finally:other.close()
    def test_quota_isbn_and_header_injection(self):
        self.assertEqual(isbn('978-0-306-40615-7'),'9780306406157')
        with self.assertRaises(ValueError):isbn('9780306406158')
        self.fabric.create_group('alice','books.open')
        with self.assertRaises(ValueError):self.fabric.post('alice',['books.open'],'bad\r\nInjected: x','body')
        with self.assertRaises(ValueError):self.fabric.begin('alice','huge',self.fabric.quota,digest(b''))
    def test_fts_permission_filters_and_schema_migration(self):
        obj=self.upload();self.book(obj)
        self.assertEqual(len(self.fabric.search('alice','Open',filters={'author':'Alice'})['items']),1)
        self.assertEqual(self.fabric.search('bob','Open')['items'],[])
        self.assertEqual(self.fabric.search('alice','Open',filters={'author':'Other'})['items'],[])
        self.assertEqual(self.fabric.db.execute('SELECT max(version) FROM migrations').fetchone()[0],3)
    def test_http_scope_range_and_origin(self):
        obj=self.upload(b'abcdefghij');self.book(obj,'public')
        token='x'*40
        http=server(self.fabric,{'port':0,'tokens':[{'account':'alice','token':token,'scopes':['content:read','library:read']} ]})
        worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
        base='http://127.0.0.1:'+str(http.server_port)
        try:
            with urlopen(Request(base+'/objects/'+obj['id'],headers={'Authorization':'Bearer '+token,'Range':'bytes=2-5'})) as response:
                self.assertEqual(response.status,206);self.assertEqual(response.read(),b'cdef')
            with self.assertRaises(HTTPError):urlopen(Request(base+'/objects/'+obj['id']))
            with self.assertRaises(HTTPError):urlopen(Request(base+'/api',data=json.dumps({'operation':'content.withdraw','arguments':{'id':'book'}}).encode(),headers={'Authorization':'Bearer '+token}))
            with self.assertRaises(HTTPError):urlopen(Request(base+'/api',data=b'{}',headers={'Authorization':'Bearer '+token,'Origin':'https://evil.example'}))
        finally:http.shutdown();http.server_close();worker.join()
    def test_nntp_tcp(self):
        self.fabric.create_group('alice','books.open')
        token='x'*40
        srv=nntp_server(self.fabric,{'port':0,'anonymous_read':True,'allow_loopback_auth':True},[{'account':'alice','token':token,'scopes':['netnews:read','netnews:write']}])
        worker=threading.Thread(target=srv.serve_forever,daemon=True);worker.start()
        try:
            with socket.create_connection(srv.server_address,timeout=5) as sock:
                io=sock.makefile('rwb',buffering=0)
                self.assertTrue(io.readline().startswith(b'201'))
                def cmd(value):io.write(value.encode()+b'\r\n');return io.readline()
                self.assertTrue(cmd('POST').startswith(b'480'))
                self.assertTrue(cmd('AUTHINFO USER alice').startswith(b'381'))
                self.assertTrue(cmd('AUTHINFO PASS '+token).startswith(b'281'))
                self.assertTrue(cmd('POST').startswith(b'340'))
                io.write(b'From: alice\r\nNewsgroups: books.open\r\nSubject: hello\r\nMessage-ID: <n@example.test>\r\n\r\n..dot\r\nbody\r\n.\r\n')
                self.assertTrue(io.readline().startswith(b'240'))
                self.assertTrue(cmd('GROUP books.open').startswith(b'211 1 1 1'))
                self.assertTrue(cmd('ARTICLE 1').startswith(b'220 1 <n@example.test>'))
                lines=[]
                while True:
                    line=io.readline()
                    if line==b'.\r\n':break
                    lines.append(line)
                self.assertIn(b'..dot\r\n',lines)
                self.assertTrue(cmd('CHECK <x@example.test>').startswith(b'502'))
                self.assertTrue(cmd('QUIT').startswith(b'205'));io.close()
        finally:srv.shutdown();srv.server_close();worker.join()


if __name__=='__main__':unittest.main()

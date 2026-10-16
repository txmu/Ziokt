"""Native UFS, real bounded local HTTP/Digest/WebDAV and isolated filesystems."""
import concurrent.futures
import hashlib
import http.client
import importlib
import io
import json
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'companions/ufsdcpm/src'))
ufs = importlib.import_module('ufsultra')
sys.path.pop(0)


@unittest.skipUnless(os.open in os.supports_dir_fd and hasattr(os,'O_NOFOLLOW'), 'native UFS descriptor confinement unavailable on this platform')
class NativeUFSHTTP(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name); self.files = self.root/'files'; self.files.mkdir()
        (self.files/'private.txt').write_bytes(b'authenticated')
        self.password = 'test-private-password-strong'
        self.config = {'root_dir':str(self.files), 'ssl':False, 'upload':True, 'checksum':True,
            'auth':{'user':'admin','pass':self.password,'role':'admin'}, 'max_upload':1024,
            'request_timeout':2, 'compression':False, 'log_file':str(self.root/'ufs.log')}
        class Quiet(ufs.UltraHandler):
            def log_message(self, *_): pass
        self.server = ufs.UltraServer(('127.0.0.1',0), Quiet, config=self.config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(5)

    def call(self, method, path, body=None, headers=None):
        client = http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=4)
        try:
            client.request(method,path,body=body,headers=headers or {})
            reply = client.getresponse()
            return reply.status,dict(reply.getheaders()),reply.read()
        finally: client.close()

    def authorization(self, method, path, *, nonce=None, nc='00000001', username='admin', password=None, **changes):
        if nonce is None:
            status, headers, _ = self.call('GET','/private.txt')
            self.assertEqual(status,401)
            nonce = re.search(r'nonce="([^"]+)"',headers['WWW-Authenticate']).group(1)
        values = {'username':username,'realm':'UltraFileServer','nonce':nonce,'uri':path,
            'qop':'auth','nc':nc,'cnonce':'test-cnonce-1234','algorithm':'SHA-256'}
        values.update(changes)
        digest = lambda text:hashlib.sha256(text.encode()).hexdigest()
        ha1 = digest(username+':'+values['realm']+':'+(password or self.password))
        values['response'] = digest(ha1+':'+nonce+':'+nc+':'+values['cnonce']+':auth:'+digest(method+':'+path))
        return 'Digest '+', '.join(key+'="'+value+'"' for key,value in values.items())

    def authenticated(self, method, path, body=None, **headers):
        headers['Authorization'] = self.authorization(method,path)
        return self.call(method,path,body,headers)

    def test_get_head_and_api_are_authenticated_and_do_not_reveal_secrets(self):
        for method,path in [('GET','/private.txt'),('HEAD','/private.txt'),('GET','/api/config'),('PROPFIND','/')]:
            self.assertEqual(self.call(method,path)[0],401)
        self.server.config['mmap_threshold']=0
        status,_,body = self.authenticated('GET','/private.txt')
        self.assertEqual((status,body),(200,b'authenticated'))
        status,headers,body = self.authenticated('HEAD','/private.txt')
        self.assertEqual((status,body),(200,b'')); self.assertEqual(headers['Content-Length'],'13')
        status,_,body = self.authenticated('GET','/api/config')
        self.assertEqual(status,200); self.assertNotIn(self.password.encode(),body)
        self.assertNotIn(b'auth',body)
        self.server.config['compression']=True
        status,headers,body=self.authenticated('GET','/private.txt',**{'Accept-Encoding':'gzip'})
        self.assertEqual(status,200); self.assertEqual(headers['Content-Encoding'],'gzip')
        self.assertEqual(__import__('gzip').decompress(body),b'authenticated')

    def test_digest_nonce_scope_replay_expiry_and_malformed_headers(self):
        header = self.authorization('GET','/private.txt')
        self.assertEqual(self.call('GET','/private.txt',headers={'Authorization':header})[0],200)
        self.assertEqual(self.call('GET','/private.txt',headers={'Authorization':header})[0],401)
        nonce=re.search(r'nonce="([^"]+)"',header).group(1)
        changed=self.authorization('GET','/private.txt',nonce=nonce,cnonce='another-cnonce-1234')
        self.assertEqual(self.call('GET','/private.txt',headers={'Authorization':changed})[0],401)
        self.assertEqual(self.call('GET','/private.txt',headers={'Authorization':self.authorization('GET','/private.txt',algorithm='MD5')})[0],401)
        for malformed in ['Digest broken','Digest nonce="x"','Digest username="admin", username="admin"']:
            self.assertEqual(self.call('GET','/private.txt',headers={'Authorization':malformed})[0],401)
        self.assertEqual(self.call('GET','/private.txt',headers={'Authorization':self.authorization('GET','/private.txt',nonce='attacker-nonce')})[0],401)
        self.assertEqual(self.call('GET','/other',headers={'Authorization':self.authorization('GET','/private.txt')})[0],401)
        import unittest.mock
        nonce = self.server.digest.challenge()
        with unittest.mock.patch('ufs_http_security.time.time',return_value=__import__('time').time()+301):
            self.assertEqual(self.call('GET','/private.txt',headers={'Authorization':self.authorization('GET','/private.txt',nonce=nonce)})[0],401)

    def test_symlink_traversal_encoded_paths_and_special_files_are_rejected(self):
        outside = self.root/'outside.txt'; outside.write_bytes(b'outside-secret')
        (self.files/'link').symlink_to(outside)
        (self.files/'directory-link').symlink_to(self.root,target_is_directory=True)
        os.mkfifo(self.files/'pipe')
        for path in ['/../outside.txt','/%2e%2e/outside.txt','/link','/directory-link/outside.txt','/pipe','/%00file','/.hidden']:
            status,_,body = self.authenticated('GET',path)
            self.assertIn(status,(400,403,409)); self.assertNotIn(b'outside-secret',body)
        self.assertIn(self.authenticated('PUT','/link',b'overwrite')[0],(403,409))
        self.assertEqual(outside.read_bytes(),b'outside-secret')

    def test_exact_atomic_upload_empty_limits_and_truncated_body(self):
        self.assertEqual(self.authenticated('PUT','/new.txt',b'hello')[0],201)
        self.assertEqual((self.files/'new.txt').read_bytes(),b'hello')
        self.assertEqual(self.authenticated('PUT','/new.txt',b'next')[0],204)
        self.assertEqual(self.authenticated('PUT','/empty',b'')[0],201)
        self.assertEqual(self.authenticated('PUT','/too-large',b'x'*1025)[0],413)
        path = '/new.txt'; auth = self.authorization('PUT',path)
        with socket.create_connection(('127.0.0.1',self.server.server_port),timeout=4) as client:
            client.sendall(('PUT '+path+' HTTP/1.0\r\nHost: localhost\r\nAuthorization: '+auth+'\r\nContent-Length: 8\r\n\r\nabc').encode())
            client.shutdown(socket.SHUT_WR)
            self.assertIn(b'400',client.recv(4096).split(b'\r\n')[0])
        self.assertEqual((self.files/'new.txt').read_bytes(),b'next')
        self.assertEqual(list(self.files.glob('.ufs-upload-*')),[])
        self.assertIn(b'SHA256:',(self.files/'new.txt.checksum').read_bytes())

    def test_webdav_unicode_xml_depth_collection_delete_and_readonly_permissions(self):
        path = '/%E9%9B%AA%26%3C.txt'
        self.assertEqual(self.authenticated('PUT',path,b'data')[0],201)
        status,headers,body = self.authenticated('PROPFIND','/',Depth='1')
        self.assertEqual(status,207); self.assertEqual(int(headers['Content-Length']),len(body))
        parsed = ET.fromstring(body)
        self.assertIn('雪&<.txt',[e.text for e in parsed.findall('.//{DAV:}displayname')])
        self.assertEqual(self.authenticated('PROPFIND','/',Depth='infinity')[0],400)
        self.assertEqual(self.authenticated('MKCOL','/collection',b'')[0],201)
        self.assertEqual(self.authenticated('DELETE','/collection')[0],204)
        self.server.config['upload'] = False
        self.assertEqual(self.authenticated('PUT','/blocked',b'no')[0],403)
        self.assertEqual(self.authenticated('DELETE','/private.txt')[0],403)
        self.assertTrue((self.files/'private.txt').exists())

    def test_parallel_uploads_are_whole_and_request_framing_is_bounded(self):
        def upload(number): return self.authenticated('PUT','/concurrent',str(number).encode()*200)[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            self.assertTrue(all(status in (201,204) for status in executor.map(upload,range(4))))
        self.assertIn((self.files/'concurrent').read_bytes(),[str(n).encode()*200 for n in range(4)])
        auth = self.authorization('PUT','/bad')
        self.assertEqual(self.call('PUT','/bad',body=b'x',headers={'Authorization':auth,'Content-Length':'-1'})[0],400)
        self.assertEqual(self.call('PUT','/bad',body=b'x',headers={'Authorization':self.authorization('PUT','/bad'),'Transfer-Encoding':'chunked'})[0],400)

    def test_real_tls_listener_with_pinned_certificate(self):
        import ssl
        config=object.__new__(ufs.Config)
        certificate=self.root/'server.pem'
        config._Config__config={'ssl_cert':str(certificate)}
        config.generate_self_signed_cert()
        self.stop()
        class Quiet(ufs.UltraHandler):
            def log_message(self,*_): pass
        self.server=ufs.UltraServer(('127.0.0.1',0),Quiet,config={**self.config,'ssl':True,'ssl_cert':str(certificate)})
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        context=ssl.create_default_context(cafile=str(certificate))
        def request(authorization=None):
            client=http.client.HTTPSConnection('localhost',self.server.server_port,context=context,timeout=4)
            try:
                client.request('GET','/private.txt',headers={'Authorization':authorization} if authorization else {})
                reply=client.getresponse(); return reply.status,dict(reply.getheaders()),reply.read()
            finally: client.close()
        status,headers,_=request(); self.assertEqual(status,401)
        nonce=re.search(r'nonce="([^"]+)"',headers['WWW-Authenticate']).group(1)
        status,_,body=request(self.authorization('GET','/private.txt',nonce=nonce))
        self.assertEqual((status,body),(200,b'authenticated'))

    def test_browser_cross_origin_and_guest_write_permissions(self):
        self.assertEqual(self.call('POST','/api/cleanup',headers={
            'Authorization':self.authorization('POST','/api/cleanup'),'Origin':'https://attacker.invalid'})[0],403)
        self.server.accounts['admin']['role']='guest'
        self.assertEqual(self.authenticated('PUT','/guest-write',b'blocked')[0],403)
        self.assertEqual(self.authenticated('GET','/api/config')[0],403)
        self.assertEqual(self.authenticated('GET','/api/stats')[0],200)

    def test_total_request_deadline_closes_slow_incomplete_headers(self):
        self.server.config['request_total_timeout']=1
        with socket.create_connection(('127.0.0.1',self.server.server_port),timeout=3) as client:
            client.sendall(b'GET /private.txt HTTP/1.1\r\nHost:')
            self.assertEqual(client.recv(4096),b'')
        self.assertEqual((self.files/'private.txt').read_bytes(),b'authenticated')

    def test_unsafe_configuration_fails_before_listener(self):
        for config in [{**self.config,'auth':{'enabled':False}}, {**self.config,'auth':{'user':'admin','pass':'admin123','role':'admin'}}]:
            with self.assertRaises(ValueError): ufs.UltraServer(('127.0.0.1',0),ufs.UltraHandler,config=config)
        with self.assertRaises(ValueError): ufs.UltraServer(('0.0.0.0',0),ufs.UltraHandler,config=self.config)
        with self.assertRaises(ValueError):
            ufs.UltraServer(('127.0.0.1',0),ufs.UltraHandler,config={**self.config,'ssl_cert':str(self.files/'private.pem')})
        import unittest.mock
        with unittest.mock.patch.dict(os.environ,{'ZIOKT_AIRGAP':'1'}):
            with self.assertRaises(PermissionError): ufs.UltraServer(('127.0.0.1',0),ufs.UltraHandler,config=self.config)


if __name__=='__main__': unittest.main()

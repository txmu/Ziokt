import datetime,ipaddress,socket,ssl,tempfile,threading,unittest
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from ziokt.content_fabric import Fabric
from ziokt.netnews_nntp import server

class FeedTests(unittest.TestCase):
 def test_tls_feed_capabilities_stream_ihave_and_loop_rejection(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);fabric=Fabric(root/'state');fabric.create_group('upstream','books.open')
   key=rsa.generate_private_key(public_exponent=65537,key_size=2048);name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')]);now=datetime.datetime.now(datetime.timezone.utc)
   cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256())
   (root/'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM));(root/'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
   token='f'*40;srv=server(fabric,{'port':0,'tls':{'cert':str(root/'cert.pem'),'key':str(root/'key.pem')},'feed_groups':['books.open']},[{'account':'upstream','token':token,'scopes':['netnews:read','netnews:feed']}]);worker=threading.Thread(target=srv.serve_forever,daemon=True);worker.start()
   try:
    context=ssl.create_default_context(cafile=str(root/'cert.pem'))
    with context.wrap_socket(socket.create_connection(srv.server_address,timeout=5),server_hostname='localhost') as sock:
     io=sock.makefile('rwb',buffering=0);self.assertTrue(io.readline().startswith(b'201'))
     def command(line):io.write(line.encode()+b'\r\n');return io.readline()
     self.assertTrue(command('AUTHINFO USER upstream').startswith(b'381'));self.assertTrue(command('AUTHINFO PASS '+token).startswith(b'281'));self.assertTrue(command('MODE STREAM').startswith(b'203'));self.assertTrue(command('CHECK <first@upstream.test>').startswith(b'238'))
     def article(mid,path='upstream.test'):
      return f'From: author@example.test\r\nNewsgroups: books.open\r\nSubject: native feed\r\nMessage-ID: {mid}\r\nDate: Mon, 19 Oct 2026 12:00:00 +0000\r\nPath: {path}\r\n\r\nNative upstream body\r\n.\r\n'.encode()
     io.write(b'TAKETHIS <first@upstream.test>\r\n'+article('<first@upstream.test>'));self.assertTrue(io.readline().startswith(b'239 <first@upstream.test>'));self.assertTrue(command('CHECK <first@upstream.test>').startswith(b'438'))
     self.assertTrue(command('IHAVE <second@upstream.test>').startswith(b'335'));io.write(article('<second@upstream.test>'));self.assertTrue(io.readline().startswith(b'235'))
     self.assertTrue(command('IHAVE <loop@upstream.test>').startswith(b'335'));io.write(article('<loop@upstream.test>',fabric.public+'!upstream.test'));self.assertTrue(io.readline().startswith(b'437'));io.close()
    stored=fabric.articles('upstream','books.open')['items'];self.assertEqual(len(stored),2);self.assertFalse(stored[0]['provenance']['publisher_signature_verified']);self.assertEqual(stored[0]['from'],'author@example.test')
   finally:srv.shutdown();srv.server_close();worker.join();fabric.close()

if __name__=='__main__':unittest.main()

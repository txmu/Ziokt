"""Durable cross-application references and real HTTP/TCP attachment exchange."""
import hashlib,json,socket,tempfile,threading,unittest
from email.message import EmailMessage
from email import policy
from email.parser import BytesParser
from pathlib import Path
from ziokt.content_fabric import Fabric
from ziokt.content_server import server,download_attachment
from ziokt.content_api import invoke
from ziokt.netnews_nntp import server as nntp_server,wire_article

class AttachmentTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.f=Fabric(self.root/'a')
 def tearDown(self):self.f.close();self.temp.cleanup()
 def upload(self,data=b'Original CC0 attachment',owner='alice',upload='upload'):
  self.f.begin(owner,upload,len(data),'sha256:'+hashlib.sha256(data).hexdigest(),'text/plain')
  for pos,start in enumerate(range(0,len(data),16384)):self.f.put(owner,upload,pos,data[start:start+16384])
  return self.f.finish(owner,upload)
 def test_reference_permissions_withdrawal_and_shared_book_retention(self):
  obj=self.upload();self.f.create_group('alice','books.open');self.f.create_group('alice','books.private',visibility='private')
  attachment=[{'id':obj['id'],'name':'original.txt'}]
  self.f.post('alice',['books.private'],'Private','Text',message_id='<private@sample.test>',attachments=attachment)
  with self.assertRaises(PermissionError):self.f.read_chunk('bob',obj['id'],0)
  post=invoke(self.f,'alice','netnews.post',{'groups':['books.open'],'subject':'Public','body':'Original','message_id':'<public@sample.test>','attachments':attachment})
  self.assertEqual(self.f.read_chunk('bob',obj['id'],0),b'Original CC0 attachment');self.assertEqual(post['attachments'][0]['digest'],obj['digest'])
  with self.assertRaises(ValueError):self.f.release_object('alice',obj['id'])
  self.assertEqual(len(self.f.references('bob',obj['id'])['items']),1)
  self.f.create_book('alice',{'id':'book','work_id':'work','edition_id':'edition','title':'Original','license':'CC0','file_id':obj['id'],'visibility':'public'})
  self.f.withdraw('alice',post['id']);self.assertEqual(self.f.read_chunk('bob',obj['id'],0),b'Original CC0 attachment')
  self.f.withdraw('alice','book')
  with self.assertRaises(PermissionError):self.f.read_chunk('bob',obj['id'],0)
  with self.assertRaises(ValueError):self.f.release_object('alice',obj['id'])
  self.f.withdraw('alice','<private@sample.test>');self.assertTrue(self.f.release_object('alice',obj['id'])['released'])
 def test_foreign_publisher_cannot_grant_access_to_known_private_object_id(self):
  obj=self.upload();other=Fabric(self.root/'attacker')
  try:
   self.f.peers[other.public]={'groups':[]}
   with other.transaction():other._event('attacker','book','forged-book',{'title':'False claim','file_id':obj['id'],'file':{k:obj[k] for k in ('size','digest','mime','merkle_root')}},'public')
   self.f.ingest(other.export()['events'])
   with self.assertRaises(PermissionError):self.f.read_chunk('bob',obj['id'],0)
  finally:other.close()
 def test_real_http_resume_and_signed_attachment_manifest(self):
  data=b'Original content '*4000;obj=self.upload(data);self.f.create_group('alice','books.open');self.f.post('alice',['books.open'],'Object','Body',message_id='<download@sample.test>',attachments=[{'id':obj['id'],'name':'original.txt'}])
  token='t'*40;http=server(self.f,{'port':0,'tokens':[{'account':'peer','token':token,'scopes':['content:read']}]});thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start();b=Fabric(self.root/'b',peers={self.f.public:{'groups':['books.open']}})
  try:
   b.create_group('alice','books.open');b.ingest(self.f.export()['events']);peers={'a':{'url':'http://127.0.0.1:'+str(http.server_port),'token':token,'public_key':self.f.public}}
   first=download_attachment(b,'reader','<download@sample.test>',obj['id'],['a'],peers,max_chunks=1);self.assertEqual(first['received_chunks'],1);b.close();b=Fabric(self.root/'b',peers={self.f.public:{'groups':['books.open']}})
   result=download_attachment(b,'reader','<download@sample.test>',obj['id'],['a'],peers);self.assertEqual(result['state'],'complete');self.assertEqual(b.read_chunk('third-reader',obj['id'],0),data[:16384])
   self.f.withdraw('alice','<download@sample.test>');b.ingest(self.f.export()['events'])
   with self.assertRaises(PermissionError):b.read_chunk('third-reader',obj['id'],0)
  finally:b.close();http.shutdown();http.server_close();thread.join()
 def test_actual_nntp_mime_post_and_roundtrip(self):
  self.f.create_group('alice','books.open');token='t'*40;srv=nntp_server(self.f,{'port':0,'allow_loopback_auth':True},[{'account':'alice','token':token,'scopes':['netnews:read','netnews:write']}]);thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
  try:
   with socket.create_connection(srv.server_address,timeout=5) as sock:
    f=sock.makefile('rwb',buffering=0);f.readline()
    def cmd(line):f.write(line.encode()+b'\r\n');return f.readline()
    self.assertTrue(cmd('AUTHINFO USER alice').startswith(b'381'));self.assertTrue(cmd('AUTHINFO PASS '+token).startswith(b'281'))
    message=EmailMessage(policy=policy.SMTP);message['From']='alice';message['Subject']='Original attachment';message['Newsgroups']='books.open';message['Message-ID']='<mime@sample.test>';message.set_content('Original body');message.add_attachment(b'Original CC0 bytes',maintype='application',subtype='octet-stream',filename='original.bin')
    self.assertTrue(cmd('POST').startswith(b'340'));f.write(message.as_bytes()+b'.\r\n');self.assertTrue(f.readline().startswith(b'240'))
    self.assertTrue(cmd('ARTICLE <mime@sample.test>').startswith(b'220'));parts=[]
    while True:
     line=f.readline()
     if line==b'.\r\n':break
     parts.append(line[1:] if line.startswith(b'..') else line)
    received=BytesParser(policy=policy.default).parsebytes(b''.join(parts));self.assertTrue(received.is_multipart());attached=list(received.iter_attachments());self.assertEqual(attached[0].get_payload(decode=True),b'Original CC0 bytes')
    self.assertTrue(cmd('POST').startswith(b'340'));f.write(message.as_bytes()+b'.\r\n');self.assertTrue(f.readline().startswith(b'240'));self.assertEqual(len(self.f.articles('alice','books.open')['items']),1)
    message.clear_content();message.set_content('Original body');message.add_attachment(b'Conflicting private bytes',maintype='application',subtype='octet-stream',filename='different.bin')
    self.assertTrue(cmd('POST').startswith(b'340'));f.write(message.as_bytes()+b'.\r\n');self.assertTrue(f.readline().startswith(b'441'))
    self.assertEqual(self.f.db.execute('SELECT count(*) FROM objects').fetchone()[0],1);self.assertEqual(self.f.db.execute('SELECT count(*) FROM uploads').fetchone()[0],1)
  finally:srv.shutdown();srv.server_close();thread.join()
 def test_public_nntp_streams_native_attachment_larger_than_inline_budget(self):
  data=b'Original legal binary payload '*3000;obj=self.upload(data);self.f.create_group('alice','books.open');self.f.post('alice',['books.open'],'Native large','Body',message_id='<large@sample.test>',attachments=[{'id':obj['id'],'name':'large.bin'}])
  srv=nntp_server(self.f,{'port':0,'anonymous_read':True},[]);thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
  try:
   with socket.create_connection(srv.server_address,timeout=5) as sock:
    stream=sock.makefile('rwb',buffering=0);stream.readline();stream.write(b'ARTICLE <large@sample.test>\r\n');self.assertTrue(stream.readline().startswith(b'220'));lines=[]
    while True:
     line=stream.readline()
     if line==b'.\r\n':break
     self.assertTrue(line);lines.append(line[1:] if line.startswith(b'..') else line)
    message=BytesParser(policy=policy.default).parsebytes(b''.join(lines));self.assertEqual(list(message.iter_attachments())[0].get_payload(decode=True),data)
  finally:srv.shutdown();srv.server_close();thread.join()
 def test_v3_book_reference_migration_preserves_public_access(self):
  obj=self.upload();self.f.create_book('alice',{'id':'legacy','work_id':'work','edition_id':'edition','file_id':obj['id'],'title':'Original','license':'CC0','visibility':'public'})
  with self.f.transaction():self.f.db.execute('DROP TABLE content_references');self.f.db.execute('DELETE FROM migrations WHERE version=4')
  self.f.close();self.f=Fabric(self.root/'a');self.assertEqual(self.f.read_chunk('bob',obj['id'],0),b'Original CC0 attachment');self.assertEqual(len(self.f.references('bob',obj['id'])['items']),1)
 def test_large_native_attachment_is_not_eagerly_embedded(self):
  obj=self.upload(b'x'*40000);self.f.create_group('alice','books.open');article=self.f.post('alice',['books.open'],'Native','Body',attachments=[{'id':obj['id'],'name':'large.txt'}])
  wire=wire_article(article,self.f,'bob','https://read.example');self.assertIn('/objects/'+obj['id'],wire);self.assertNotIn('multipart/mixed',wire);self.assertLess(len(wire),2000)
  for name in ('../secret','a\\b','bad\nname'):
   with self.assertRaises(ValueError):self.f.post('alice',['books.open'],'Bad','Body',attachments=[{'id':obj['id'],'name':name}])

if __name__=='__main__':unittest.main()

"""Real client command exchange beyond 1,000 articles and binary posting."""
import socket,tempfile,threading,unittest
from email.message import EmailMessage
from email import policy
from email.parser import BytesParser
from ziokt.content_fabric import Fabric
from ziokt.netnews_nntp import server

class ClientTests(unittest.TestCase):
 def test_large_group_navigation_aliases_and_authorized_binary_post(self):
  with tempfile.TemporaryDirectory() as root:
   fabric=Fabric(root);fabric.create_group('alice','books.open');fabric.create_group('alice','books.private',visibility='private')
   # Real signed persistent records; reset only the fixture publisher's rate window.
   for number in range(1,1004):
    if number%50==1:
     with fabric.transaction():fabric.db.execute('DELETE FROM rates')
    fabric.post('alice',['books.open'],'Article '+str(number),'Original fixture',message_id=f'<{number}@client.test>')
   srv=server(fabric,{'port':0,'allow_loopback_auth':True,'anonymous_read':True},[{'account':'alice','token':'t'*40,'senders':['alice@example.test'],'scopes':['netnews:read','netnews:write']}]);worker=threading.Thread(target=srv.serve_forever,daemon=True);worker.start()
   try:
    with socket.create_connection(srv.server_address,timeout=10) as sock:
     io=sock.makefile('rwb',buffering=0);io.readline()
     def cmd(line):io.write(line.encode()+b'\r\n');return io.readline()
     def block():
      lines=[]
      while True:
       line=io.readline()
       if line==b'.\r\n':return lines
       self.assertTrue(line);lines.append(line[1:] if line.startswith(b'..') else line)
     self.assertEqual(cmd('GROUP books.open').split()[1:4],[b'1003',b'1',b'1003'])
     self.assertTrue(cmd('STAT 1000').startswith(b'223 1000'));self.assertTrue(cmd('NEXT').startswith(b'223 1001'));self.assertTrue(cmd('LAST').startswith(b'223 1000'))
     self.assertTrue(cmd('LISTGROUP books.open 1001-').startswith(b'211'));self.assertEqual(block(),[b'1001\r\n',b'1002\r\n',b'1003\r\n'])
     self.assertTrue(cmd('XOVER 1001-1003').startswith(b'224'));self.assertEqual(len(block()),3)
     self.assertTrue(cmd('XHDR subject 1003').startswith(b'225'));self.assertIn(b'Article 1003',b''.join(block()))
     self.assertTrue(cmd('GROUP books.private').startswith(b'411'))
     self.assertTrue(cmd('POST').startswith(b'480'));self.assertTrue(cmd('AUTHINFO USER alice').startswith(b'381'));self.assertTrue(cmd('AUTHINFO PASS '+'t'*40).startswith(b'281'))
     payload=bytes(range(256))*1024;message=EmailMessage(policy=policy.SMTP);message['From']='Alice <alice@example.test>';message['Subject']='Binary client';message['Newsgroups']='books.open';message['Message-ID']='<binary@client.test>';message.set_content('Original binary attachment');message.add_attachment(payload,maintype='application',subtype='octet-stream',filename='original.bin')
     self.assertTrue(cmd('POST').startswith(b'340'));io.write(message.as_bytes()+b'.\r\n');self.assertTrue(io.readline().startswith(b'240'))
     self.assertTrue(cmd('ARTICLE <binary@client.test>').startswith(b'220'));received=BytesParser(policy=policy.default).parsebytes(b''.join(block()));self.assertEqual(list(received.iter_attachments())[0].get_payload(decode=True),payload);self.assertEqual(str(received['From']),'Alice <alice@example.test>')
     message.replace_header('From','Mallory <mallory@example.test>');message.replace_header('Message-ID','<forged@client.test>');self.assertTrue(cmd('POST').startswith(b'340'));io.write(message.as_bytes()+b'.\r\n');self.assertTrue(io.readline().startswith(b'441'))
     io.close()
    self.assertEqual(fabric.article_numbers('reader','books.open')['count'],1004)
   finally:srv.shutdown();srv.server_close();worker.join();fabric.close()

if __name__=='__main__':unittest.main()

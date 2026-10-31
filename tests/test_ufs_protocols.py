"""Actual UFS protocol clients, account isolation and confined file operations."""
import asyncio,base64,datetime,ftplib,hashlib,http.client,io,json,os,re,socket,ssl,tempfile,unittest
from pathlib import Path
import paramiko,telnetlib3
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from ziokt.ufs_protocols import Hub


async def until(reader,text):
 value=await reader.readuntil(text.encode());return value.decode() if isinstance(value,bytes) else value


class Protocols(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.password='UFS-private-test-password-2026'
  key=rsa.generate_private_key(public_exponent=65537,key_size=2048);now=datetime.datetime.now(datetime.timezone.utc);name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
  cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(__import__('ipaddress').ip_address('127.0.0.1'))]),False).sign(key,hashes.SHA256())
  self.cert=self.root/'server.crt';self.cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM));self.key=self.root/'server.key';self.key.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));self.key.chmod(0o600)
  config={'root_dir':str(self.root/'files'),'log_file':str(self.root/'ufs.log'),'ssl':False,'host':'127.0.0.1','port':0,'upload':True,'checksum':False,'self_test':False,'max_upload':1024*1024,'auth':{'users':{user:{'password':self.password,'role':role} for user,role in [('alice','admin'),('bob','user'),('guest','guest')]}},'protocols':{label:{'port':0,'tls':label=='ftps','cert':str(self.cert),'key':str(self.key)} for label in ['ftp','ftps','sftp','gopher','telnet','nntp']}}
  self.hub=Hub(config);self.ports=await self.hub.start();self.data=b'actual native protocol bytes\0\xff'*100
  (self.hub.public.store.root/'welcome.bin').write_bytes(self.data)
 async def asyncTearDown(self):await self.hub.close();self.temp.cleanup()
 def ftp(self,label='ftp',user='alice'):
  client=ftplib.FTP_TLS(context=ssl.create_default_context(cafile=str(self.cert))) if label=='ftps' else ftplib.FTP()
  client.connect('127.0.0.1',self.ports[label]['port'],timeout=8);client.login(user,self.password)
  if label=='ftps':client.prot_p()
  return client
 def ssh(self,user='alice',password=None):
  transport=paramiko.Transport(('127.0.0.1',self.ports['sftp']['port']));hostkey=paramiko.RSAKey(filename=str(self.root/'sftp-host.key'));transport.connect(username=user,password=password or self.password,hostkey=hostkey)
  return transport,paramiko.SFTPClient.from_transport(transport)
 def http(self,user,path,method='GET',body=None):
  port=self.ports['http']['port'];client=http.client.HTTPConnection('127.0.0.1',port,timeout=8);client.request(method,path);response=client.getresponse();nonce=re.search('nonce="([^"]+)"',response.getheader('WWW-Authenticate')).group(1);response.read();client.close()
  digest=lambda value:hashlib.sha256(value.encode()).hexdigest();cnonce='actual-protocol-cnonce';realm='UltraFileServer';ha1=digest(user+':'+realm+':'+self.password);proof=digest(ha1+':'+nonce+':00000001:'+cnonce+':auth:'+digest(method+':'+path));header='Digest '+', '.join(k+'="'+v+'"' for k,v in {'username':user,'realm':realm,'nonce':nonce,'uri':path,'qop':'auth','nc':'00000001','cnonce':cnonce,'algorithm':'SHA-256','response':proof}.items())
  client=http.client.HTTPConnection('127.0.0.1',port,timeout=8);client.request(method,path,body=body,headers={'Authorization':header});r=client.getresponse();result=(r.status,r.read());client.close();return result
 async def test_ftp_ftps_sftp_http_webdav_share_scoped_storage(self):
  def clients():
   for label in ('ftp','ftps'):
    with self.ftp(label) as client:
     client.storbinary('STOR '+label+'.bin',io.BytesIO(self.data));out=io.BytesIO();client.retrbinary('RETR '+label+'.bin',out.write);self.assertEqual(out.getvalue(),self.data)
     client.rename(label+'.bin',label+'-renamed.bin');self.assertIn(label+'-renamed.bin',client.nlst())
   transport,sftp=self.ssh()
   try:
    with sftp.open('/sftp.bin','wb') as out:out.write(self.data)
    self.assertEqual(sftp.open('/ftp-renamed.bin','rb').read(),self.data);sftp.mkdir('/folder');sftp.rename('/sftp.bin','/folder/shared.bin');self.assertEqual(sftp.stat('/folder/shared.bin').st_size,len(self.data));sftp.chmod('/folder/shared.bin',0o600)
   finally:sftp.close();transport.close()
   self.assertEqual(self.http('alice','/folder/shared.bin'),(200,self.data));self.assertEqual(self.http('alice','/dav.bin','PUT',self.data)[0],201);self.assertEqual(self.http('alice','/dav.bin','PROPFIND')[0],207)
   self.assertEqual(self.http('bob','/folder/shared.bin')[0],404)
   from ziokt.ufs_protocols import status
   path=self.root/'native-config.json';settings=dict(self.hub.config,port=self.ports['http']['port']);path.write_text(json.dumps(settings));path.chmod(0o600)
   self.assertEqual(status(path)['listeners']['sftp']['port'],self.ports['sftp']['port'])
  await asyncio.to_thread(clients)
 async def test_native_integrated_system_starts_all_protocols_and_restores_storage(self):
  import importlib,signal
  module=importlib.import_module('dcpm_ufs_integration');config=dict(self.hub.config)
  await self.hub.close()
  path=self.root/'integrated.json';path.write_text(json.dumps({'storage':{'cache':str(self.root/'cache'),'ufs_root':str(self.root/'integrated-files')},'ufs':config,'logging':{'file':str(self.root/'native.log')},'p2p':{'enabled':False}}));path.chmod(0o600)
  signals={signum:signal.getsignal(signum) for signum in (signal.SIGINT,signal.SIGTERM)}
  try:
   for attempt in range(2):
    system=module.IntegratedSystem(str(path));task=asyncio.create_task(system.start())
    try:
     for _ in range(100):
      if task.done():await task
      if system.running:break
      await asyncio.sleep(.1)
     self.assertTrue(system.running);self.hub=system.protocol_hub;self.ports={'http':{'port':system.ufs_server.server_port},**self.hub.inventory}
     self.assertEqual(set(self.hub.inventory),{'ftp','ftps','sftp','gopher','telnet','nntp'})
     def client():
      with self.ftp('ftps') as ftp:
       if attempt==0:ftp.storbinary('STOR persisted.bin',io.BytesIO(self.data))
       result=io.BytesIO();ftp.retrbinary('RETR persisted.bin',result.write);self.assertEqual(result.getvalue(),self.data)
      self.assertEqual(self.http('alice','/persisted.bin'),(200,self.data))
     await asyncio.to_thread(client)
    finally:await system.stop();await asyncio.wait_for(task,5)
  finally:
   for signum,handler in signals.items():signal.signal(signum,handler)
 async def test_guest_denials_traversal_symlinks_and_no_ssh_shell(self):
  outside=self.root/'outside-secret';outside.write_bytes(b'outside must stay private');(self.hub.files['alice'].store.root/'escape').symlink_to(outside)
  def clients():
   with self.ftp(user='guest') as client:
    with self.assertRaises(ftplib.error_perm):client.storbinary('STOR denied.bin',io.BytesIO(self.data))
   with self.ftp() as client:
    for path in ('escape','../../outside-secret'):
     with self.assertRaises(ftplib.error_perm):client.retrbinary('RETR '+path,lambda data:None)
   transport,sftp=self.ssh('guest')
   try:
    with self.assertRaises(IOError):sftp.open('/denied.bin','wb')
    channel=transport.open_session()
    with self.assertRaises(paramiko.SSHException):channel.exec_command('touch '+str(self.root/'executed'))
    channel.close()
   finally:sftp.close();transport.close()
   transport,sftp=self.ssh()
   try:
    for path in ('/escape','/../../outside-secret'):
     with self.assertRaises(IOError):sftp.open(path,'rb')
   finally:sftp.close();transport.close()
   self.assertEqual(self.http('alice','/escape')[0],403);self.assertFalse((self.root/'executed').exists())
  await asyncio.to_thread(clients)
 async def test_gopher_public_menu_download_search_and_private_denial(self):
  async def query(selector):
   reader,writer=await asyncio.open_connection('127.0.0.1',self.ports['gopher']['port']);writer.write(selector.encode()+b'\r\n');await writer.drain();data=await asyncio.wait_for(reader.read(),8);writer.close();await writer.wait_closed();return data
  self.assertIn(b'welcome.bin',await query(''));self.assertEqual(await query('/welcome.bin'),self.data);self.assertIn(b'welcome.bin',await query('/search\twelcome'))
  self.assertIn(b'Request rejected',await query('/../outside'));self.assertIn(b'Request rejected',await query('/auth/not-a-valid-token/private.bin'))
 async def test_telnet_authentication_is_per_session_and_scoped_commands(self):
  async def connect(user):
   reader,writer=await telnetlib3.open_connection('127.0.0.1',self.ports['telnet']['port'],connect_maxwait=1)
   await asyncio.wait_for(until(reader,'Username: '),5);writer.write(user+'\r\n');await writer.drain();await asyncio.wait_for(until(reader,'Password: '),5);writer.write(self.password+'\r\n');await writer.drain();value=await asyncio.wait_for(until(reader,'ufs> '),5);self.assertIn('Authenticated',value);return reader,writer
  reader,writer=await connect('alice');payload=base64.b64encode(b'private terminal content').decode();writer.write('put /terminal.txt '+payload+'\r\n');await writer.drain();self.assertIn('OK',await asyncio.wait_for(until(reader,'ufs> '),5))
  other,second=await connect('bob');second.write('files\r\n');await second.drain();self.assertNotIn('terminal.txt',await asyncio.wait_for(until(other,'ufs> '),5));second.write('exit\r\n');await second.drain();second.close()
  writer.write('get /terminal.txt\r\n');await writer.drain();self.assertIn(payload,await asyncio.wait_for(until(reader,'ufs> '),5));writer.write('exit\r\n');await writer.drain();writer.close()
 async def test_private_gopher_uses_verified_tls_scoped_tokens_and_text_framing(self):
  config=dict(self.hub.config);await self.hub.close();token='f'*64
  config['protocols']={'gopher':{'port':0,'tls':True,'cert':str(self.cert),'key':str(self.key),'tokens':{'alice':token}}}
  self.hub=Hub(config,include_http=False);self.ports=await self.hub.start();(self.hub.files['alice'].store.root/'private.txt').write_bytes(b'.private line\nlast')
  context=ssl.create_default_context(cafile=str(self.cert))
  async def query(selector):
   reader,writer=await asyncio.open_connection('127.0.0.1',self.ports['gopher']['port'],ssl=context);writer.write(selector.encode()+b'\r\n');await writer.drain();body=await asyncio.wait_for(reader.read(),8);writer.close();await writer.wait_closed();return body
  self.assertEqual(await query('/auth/'+token+'/private.txt'),b'..private line\r\nlast\r\n.\r\n')
  self.assertIn(('/auth/'+token+'/private.txt').encode(),await query('/auth/'+token+'/'))
  self.assertIn(b'Request rejected',await query('/auth/'+'e'*64+'/private.txt'))
 async def test_listener_failure_requests_supervised_restart(self):
  self.assertTrue(all(item['is_listening'] for item in self.hub.snapshot().values()))
  server,_=self.hub.handles['gopher'];server.close();await server.wait_closed()
  await asyncio.wait_for(self.hub.stopping.wait(),3)
  self.assertFalse(self.hub.snapshot()['gopher']['is_listening'])
 async def test_nntp_auth_post_read_and_guest_write_denial(self):
  def client(user):
   sock=socket.create_connection(('127.0.0.1',self.ports['nntp']['port']),timeout=8);stream=sock.makefile('rwb',buffering=0);stream.readline()
   def call(text):stream.write(text.encode()+b'\r\n');return stream.readline()
   self.assertTrue(call('AUTHINFO USER '+user).startswith(b'381'));self.assertTrue(call('AUTHINFO PASS '+self.password).startswith(b'281'));return sock,stream,call
  def clients():
   sock,stream,call=client('alice')
   try:
    self.assertTrue(call('POST').startswith(b'340'));stream.write(b'From: alice\r\nNewsgroups: ufs.discuss\r\nSubject: UFS native protocol\r\nMessage-ID: <ufs-protocol@example.test>\r\n\r\nActual signed content integration.\r\n.\r\n');self.assertTrue(stream.readline().startswith(b'240'));self.assertTrue(call('GROUP ufs.discuss').startswith(b'211'));self.assertTrue(call('ARTICLE 1').startswith(b'220'))
    rows=[]
    while (line:=stream.readline())!=b'.\r\n':rows.append(line)
    self.assertIn(b'Actual signed content integration.\r\n',rows);call('QUIT')
   finally:stream.close();sock.close()
   sock,stream,call=client('guest')
   try:self.assertTrue(call('POST').startswith(b'440'));call('QUIT')
   finally:stream.close();sock.close()
  await asyncio.to_thread(clients)


if __name__=='__main__':unittest.main()

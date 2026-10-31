"""Actual public TCP UFS acceptance; credentials remain in private local descriptors."""
import argparse,asyncio,base64,datetime,ftplib,hashlib,io,json,os,pathlib,re,secrets,signal,socket,ssl,time
import paramiko,telnetlib3
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import http.client as http_client
from ziokt.ufs_protocols import Hub
P=pathlib.Path
PORTS={'http':24643,'ftp':24621,'ftps':24622,'telnet':24623,'sftp':24624,'gopher':24670,'nntp':24619}
DATA=hashlib.sha256(b'Ziokt physical UFS all protocols').digest()*4096

def write(path,data):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.write_text(json.dumps(data,indent=2) if isinstance(data,dict) else data);path.chmod(0o600)

async def serve(root,host):
 root.mkdir(parents=True,exist_ok=True,mode=0o700)
 key=rsa.generate_private_key(public_exponent=65537,key_size=2048);now=datetime.datetime.now(datetime.timezone.utc);name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,host)])
 import ipaddress
 cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=7)).add_extension(x509.BasicConstraints(ca=True,path_length=None),True).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(host)),x509.DNSName('localhost')]),False).sign(key,hashes.SHA256())
 certificate=cert.public_bytes(serialization.Encoding.PEM);secret=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
 for filename,data in [('tls.crt',certificate),('tls.key',secret),('tls-combined.pem',certificate+secret)]:write(root/filename,data.decode())
 password=secrets.token_urlsafe(40);readerpass=secrets.token_urlsafe(40)
 config={'root_dir':str(root/'served'),'public_root':str(root/'public'),'log_file':str(root/'ufs.log'),'host':'0.0.0.0','ssl':True,'ssl_cert':str(root/'tls-combined.pem'),'port':PORTS['http'],'upload':True,'checksum':False,'self_test':False,'max_upload':4*1024*1024,'ip_whitelist':['0.0.0.0/0'],'auth':{'users':{'alice':{'password':password,'role':'admin'},'reader':{'password':readerpass,'role':'guest'}}},'protocols':{name:{'port':PORTS[name],'tls':name not in {'sftp','gopher'},'cert':str(root/'tls.crt'),'key':str(root/'tls.key'),**({'passive_ports':[24800,24832],'masquerade_address':host} if name in {'ftp','ftps'} else {}),**({'hostname':host} if name=='gopher' else {})} for name in ['ftp','ftps','telnet','sftp','gopher','nntp']}}
 write(root/'server.json',config);hub=Hub(config);(hub.public.store.root/'welcome.bin').write_bytes(DATA)
 try:
  inventory=await hub.start();hostkey=paramiko.RSAKey(filename=str(root/'sftp-host.key'))
  write(root/'client.json',{'host':host,'ports':PORTS,'certificate':certificate.decode(),'host_key':hostkey.get_base64(),'username':'alice','password':password,'reader_password':readerpass})
  write(root/'ready.json',{'listeners':inventory,'status':'ready'});print(json.dumps({'status':'ready','host':host,'ports':PORTS}),flush=True)
  loop=asyncio.get_running_loop()
  for signum in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(signum,hub.stopping.set)
  await hub.stopping.wait()
 finally:await hub.close()

def context(peer,root):
 cert=root/'peer-ca.pem';write(cert,peer['certificate']);return ssl.create_default_context(cafile=str(cert))

def http(peer,ctx,method,path,body=None,user=None,password=None):
 host=peer['host'];port=peer['ports']['http'];user=user or peer['username'];password=password or peer['password']
 connection=http_client.HTTPSConnection(host,port,context=ctx,timeout=15);connection.request('GET',path);response=connection.getresponse();challenge=response.getheader('WWW-Authenticate');response.read();connection.close()
 if not challenge:raise RuntimeError('native authenticated challenge absent')
 nonce=re.search('nonce="([^"]+)"',challenge).group(1);realm=re.search('realm="([^"]+)"',challenge).group(1);cnonce=secrets.token_hex(16);h=lambda value:hashlib.sha256(value.encode()).hexdigest();ha1=h(user+':'+realm+':'+password);proof=h(ha1+':'+nonce+':00000001:'+cnonce+':auth:'+h(method+':'+path));values={'username':user,'realm':realm,'nonce':nonce,'uri':path,'qop':'auth','nc':'00000001','cnonce':cnonce,'algorithm':'SHA-256','response':proof}
 headers={'Authorization':'Digest '+', '.join(k+'="'+v+'"' for k,v in values.items())};connection=http_client.HTTPSConnection(host,port,context=ctx,timeout=15);connection.request(method,path,body=body,headers=headers);r=connection.getresponse();result=(r.status,r.read());connection.close();return result

async def probe(peer,root):
 root.mkdir(parents=True,exist_ok=True,mode=0o700);ctx=context(peer,root);report={'schema':'ziokt.ufs-crosshost.v1','target':peer['host'],'protocols':{},'bytes':len(DATA),'sha256':hashlib.sha256(DATA).hexdigest()}
 def files():
  for label in ('ftp','ftps'):
   with ftplib.FTP_TLS(context=ctx) as client:
    client.connect(peer['host'],peer['ports'][label],timeout=15);client.login(peer['username'],peer['password']);client.prot_p();client.storbinary('STOR '+label+'.bin',io.BytesIO(DATA));received=io.BytesIO();client.retrbinary('RETR '+label+'.bin',received.write);assert received.getvalue()==DATA
   assert http(peer,ctx,'GET','/'+label+'.bin')==(200,DATA);report['protocols'][label]={'status':'PASS','tls':True,'cross_protocol_https_readback':True}
  with ftplib.FTP_TLS(context=ctx) as client:
   client.connect(peer['host'],peer['ports']['ftps'],timeout=15);client.login('reader',peer['reader_password']);client.prot_p()
   try:client.storbinary('STOR denied.bin',io.BytesIO(DATA));raise AssertionError('guest write accepted')
   except ftplib.error_perm:pass
  key=paramiko.RSAKey(data=base64.b64decode(peer['host_key']));transport=paramiko.Transport((peer['host'],peer['ports']['sftp']));transport.connect(username=peer['username'],password=peer['password'],hostkey=key);sftp=paramiko.SFTPClient.from_transport(transport)
  try:
   with sftp.open('/sftp.bin','wb') as target:target.write(DATA)
   with sftp.open('/ftp.bin','rb') as source:assert source.read()==DATA
  finally:sftp.close();transport.close()
  assert http(peer,ctx,'GET','/sftp.bin')==(200,DATA);report['protocols']['sftp']={'status':'PASS','ssh_host_key_verified':True,'cross_protocol_https_readback':True}
  assert http(peer,ctx,'PUT','/webdav.bin',DATA)[0] in {200,201,204};assert http(peer,ctx,'GET','/webdav.bin')==(200,DATA);assert http(peer,ctx,'PROPFIND','/webdav.bin')[0]==207;assert http(peer,ctx,'DELETE','/webdav.bin')[0]==204
  assert http(peer,ctx,'PUT','/denied.bin',b'denied','reader',peer['reader_password'])[0]==403;report['protocols']['https-webdav']={'status':'PASS','certificate_verified':True,'guest_write_denied':True}
  raw=socket.create_connection((peer['host'],peer['ports']['gopher']),timeout=15)
  try:raw.sendall(b'/welcome.bin\r\n');received=bytearray()
  finally:pass
  while chunk:=raw.recv(65536):received.extend(chunk)
  raw.close();assert bytes(received)==DATA;report['protocols']['gopher']={'status':'PASS','public_directory_only':True}
  raw=ctx.wrap_socket(socket.create_connection((peer['host'],peer['ports']['nntp']),timeout=15),server_hostname=peer['host']);stream=raw.makefile('rwb',buffering=0)
  def line(value):stream.write(value.encode()+b'\r\n');return stream.readline()
  try:
   assert stream.readline().startswith(b'201');assert line('AUTHINFO USER '+peer['username']).startswith(b'381');assert line('AUTHINFO PASS '+peer['password']).startswith(b'281');assert line('POST').startswith(b'340')
   marker=secrets.token_hex(12);body='Public physical UFS NNTP '+marker;stream.write(('From: alice\r\nNewsgroups: ufs.discuss\r\nSubject: physical encrypted NNTP\r\nMessage-ID: <'+marker+'@ufs.example>\r\n\r\n'+body+'\r\n.\r\n').encode());assert stream.readline().startswith(b'240');assert line('GROUP ufs.discuss').startswith(b'211');assert line('ARTICLE <'+marker+'@ufs.example>').startswith(b'220');received=[]
   while (value:=stream.readline())!=b'.\r\n':received.append(value)
   assert body.encode()+b'\r\n' in received;line('QUIT')
  finally:stream.close();raw.close()
  report['protocols']['nntp']={'status':'PASS','tls':True,'authenticated_post_and_article':True}
 await asyncio.to_thread(files)
 reader,writer=await telnetlib3.open_connection(peer['host'],peer['ports']['telnet'],ssl=ctx,server_hostname=peer['host'],connect_maxwait=1)
 async def until(text):return await asyncio.wait_for(reader.readuntil(text.encode()),10)
 await until('Username: ');writer.write(peer['username']+'\r\n');await writer.drain();await until('Password: ');writer.write(peer['password']+'\r\n');await writer.drain();assert b'Authenticated' in await until('ufs> ');writer.write('put /telnet.txt '+base64.b64encode(b'actual public TLS terminal data').decode()+'\r\n');await writer.drain();assert b'OK' in await until('ufs> ');writer.write('exit\r\n');await writer.drain();writer.close()
 assert await asyncio.to_thread(http,peer,ctx,'GET','/telnet.txt')==(200,b'actual public TLS terminal data');report['protocols']['telnet']={'status':'PASS','tls':True,'cross_protocol_https_readback':True}
 report['status']='PASS';return report

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['serve','probe']);p.add_argument('--root',type=P,required=True);p.add_argument('--host');p.add_argument('--peer',type=P);p.add_argument('--output',type=P);args=p.parse_args()
 if args.action=='serve':asyncio.run(serve(args.root,args.host))
 else:
  result=asyncio.run(probe(json.loads(args.peer.read_text()),args.root));write(args.output,result);print(json.dumps(result))

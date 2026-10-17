import hashlib,http.client,io,json,os,sqlite3,tempfile,threading,time,unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ziokt.gateway import Gateway,Server,handler,verify_client,read_token
from ziokt.gateway_store import Store,byte_range,encoded

class GatewayTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.forum=self.root/'forum.db';self.dht=self.root/'dht.db'
  with sqlite3.connect(self.forum) as db:db.executescript('CREATE TABLE topics(id TEXT PRIMARY KEY,title TEXT,author TEXT,timestamp INT,signature TEXT,content_hash TEXT,attachment_hash TEXT,attachment_name TEXT,associated_group_id TEXT); CREATE TABLE posts(id TEXT PRIMARY KEY,topic_id TEXT,author TEXT,timestamp INT,signature TEXT,content_hash TEXT,attachment_hash TEXT,attachment_name TEXT);')
  with sqlite3.connect(self.dht) as db:db.execute('CREATE TABLE local_chunks(hash TEXT PRIMARY KEY,file_path TEXT,offset INT,size INT)')
  token=self.root/'token';token.write_text('a'*64);token.chmod(0o600)
  self.config={'objects':str(self.root/'objects'),'dht_db':str(self.dht),'forum_db':str(self.forum),'network':'test','admin_token':str(token)}
  self.gateway=Gateway(self.config);self.server=Server(('127.0.0.1',0),handler(self.gateway));threading.Thread(target=self.server.serve_forever,daemon=True).start()
  self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
 def request(self,method,path,data=None,headers=None):
  conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10);conn.request(method,path,data,headers or {});r=conn.getresponse();result=r.status,dict(r.getheaders()),r.read();conn.close();return result
 def signed(self,**changes):
  key=Ed25519PrivateKey.generate();v={'schema':'ziokt.forum.v3','network':'test','title':'Hello 世界','content':'content <script>','reply_to':'','timestamp':int(time.time()),'nonce':os.urandom(32).hex(),'public_key':key.public_key().public_bytes_raw().hex()};v.update(changes);v['signature']=key.sign(encoded(v)).hex();return v
 def test_signature_mutation_and_scope(self):
  v=self.signed();self.assertEqual(verify_client(v,'test'),hashlib.sha256(bytes.fromhex(v['public_key'])).hexdigest())
  for changes in [{'title':'forged'},{'network':'other'},{'timestamp':0},{'extra':1}]:
   with self.assertRaises(Exception):verify_client({**v,**changes},'test')
 def test_read_write_replay_and_rate(self):
  self.assertEqual(self.request('GET','/api/gateway/status')[0],200)
  self.assertEqual(self.request('POST','/api/gateway/forum','{"content":"forged"}',{'Content-Type':'application/json'})[0],403)
  v=self.signed();status,_,raw=self.request('POST','/api/gateway/forum',json.dumps(v),{'Content-Type':'application/json'});self.assertEqual(status,201,raw)
  for payload in [v,self.signed()]:self.assertEqual(self.request('POST','/api/gateway/forum',json.dumps(payload),{'Content-Type':'application/json'})[0],403)
  with sqlite3.connect(self.forum) as db:self.assertEqual(db.execute('SELECT author FROM topics').fetchall(),[(verify_client(v,'test'),)])
 def test_ranges_no_disk_download(self):
  data=os.urandom(2*1024*1024+37);root=self.gateway.store.publish(io.BytesIO(data),'movie');before=set((self.root/'objects').iterdir())
  for span,left,right in [('bytes=42-122',42,123),('bytes=-99',len(data)-99,len(data)),('bytes=1048570-',1048570,len(data))]:
   status,headers,raw=self.request('GET','/stream/'+root,headers={'Range':span});self.assertEqual(status,206);self.assertEqual(raw,data[left:right]);self.assertIn('Content-Range',headers)
  status,headers,_=self.request('GET','/stream/'+root,headers={'Range':'bytes=999999999-'});self.assertEqual(status,416);self.assertEqual(headers['Content-Range'],'bytes */'+str(len(data)))
  self.assertEqual(self.request('HEAD','/stream/'+root)[0],200);self.assertEqual(self.request('GET','/stream/'+root,headers={'If-None-Match':'"'+root+'"'})[0],304);self.assertEqual(before,set((self.root/'objects').iterdir()))
 def test_merkle_subtree_range(self):
  store=self.gateway.store;refs=[];expected=b''
  for i in range(3):
   data=bytes([i])*17;expected+=data;leaf={'hash':store.put(data),'size':17,'tree':False};child=store.put(encoded({'schema':'ziokt.manifest.v2','size':17,'children':[leaf]}));refs.append({'hash':child,'size':17,'tree':True})
  root=store.put(encoded({'schema':'ziokt.manifest.v2','size':51,'children':refs}));self.assertEqual(b''.join(store.stream(store.manifest(root),12,40)),expected[12:41])
 def test_bad_peer_retry_without_cache(self):
  import http.server
  data=b'correct object';digest=hashlib.sha256(data).hexdigest();calls=[]
  class Peer(http.server.BaseHTTPRequestHandler):
   def do_GET(inner):
    calls.append(inner.server.server_port);body=b'bad' if inner.server.bad else data;inner.send_response(200);inner.send_header('Content-Length',str(len(body)));inner.end_headers();inner.wfile.write(body)
   def log_message(*_):pass
  origins=[]
  for bad in [True,False]:
   peer=http.server.ThreadingHTTPServer(('127.0.0.1',0),Peer);peer.bad=bad;threading.Thread(target=peer.serve_forever,daemon=True).start();self.addCleanup(peer.server_close);self.addCleanup(peer.shutdown);origins.append('http://127.0.0.1:'+str(peer.server_port))
  store=Store(self.root/'remote',peers=origins);self.assertEqual(store.get(digest),data);self.assertEqual(len(calls),2);self.assertEqual(list((self.root/'remote').iterdir()),[])
 def test_empty_and_permissions(self):
  store=self.gateway.store;root=store.publish(io.BytesIO(b''));self.assertEqual(self.request('GET','/stream/'+root)[2],b'');path=Path(self.config['admin_token']);path.chmod(0o644)
  with self.assertRaises(ValueError):read_token(path)
 def test_invalid_range_and_manifest(self):
  for value in ['bytes=-0','bytes=3-2','bytes=0-1,3-4','bytes=-','junk']:
   with self.assertRaises(ValueError):byte_range(value,10)
  store=self.gateway.store;root=store.put(encoded({'schema':'ziokt.manifest.v2','size':100,'children':[]}))
  with self.assertRaises(ValueError):store.manifest(root)

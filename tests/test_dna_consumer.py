"""Real RNA signatures, durable queue and real native Corium inventory RPC."""
import copy,hashlib,json,time
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from test_native_integration import NativeFixture
from ziokt.dna_consumer import Consumer
from ziokt.dna_protocol import rna_sign
from ziokt.protocol import encoded

class ConsumerTests(NativeFixture):
 def setUp(self):
  super().setUp();self.key=ec.generate_private_key(ec.SECP256K1());self.pem=self.key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n');self.sender=hashlib.sha256(self.pem.encode()).hexdigest()
  self.fpath=self.base/'federation.json';self.fpath.write_bytes(encoded(self.federation));self.fpath.chmod(0o600)
  self.config={'schema':'ziokt.dna-consumer.v1','enabled':True,'state':str(self.base/'consumer'),'listen':'127.0.0.1','port':18889,'chain':'a'*64,'policy':'b'*64,'senders':{self.sender:{'public_key':self.pem,'components':['corium']}},'targets':{'corium':{'federation':str(self.fpath),'provider':'corium-local','actions':['status.get']}}}
  self.path=self.base/'consumer.json';self.save();self.consumer=Consumer(self.path)
 def save(self):self.path.write_bytes(encoded(self.config));self.path.chmod(0o600)
 def frame(self,sequence=1,component='corium'):
  command={'schema':'ziokt.dna-command.v1','component':component,'operation':'status.get','resource':'','arguments':{},'expected_revision':None}
  return rna_sign(self.key,'a'*64,'b'*64,self.sender,sequence,int(time.time()),encoded(command))
 def test_signed_queue_restart_native_dispatch_and_duplicate(self):
  frame=self.frame();first=self.consumer.enqueue(frame);self.assertEqual(first['state'],'queued');self.assertTrue(self.consumer.enqueue(frame)['duplicate'])
  restarted=Consumer(self.path);result=restarted.step();self.assertEqual(result['state'],'completed_read',result);self.assertIsNone(restarted.step())
  with restarted.db() as db:self.assertIn('native_status',json.loads(db.execute('SELECT result FROM jobs').fetchone()[0]))
 def test_tamper_domain_replay_and_component_denied(self):
  frame=self.frame();bad=copy.deepcopy(frame);bad['header']['chain']='f'*64
  with self.assertRaises(ValueError):self.consumer.enqueue(bad)
  with self.assertRaises(PermissionError):self.consumer.enqueue(self.frame(component='unassigned'))
  self.consumer.enqueue(frame)
  changed=self.frame()
  with self.assertRaises(Exception):self.consumer.enqueue(changed)
 def test_revocation_prevents_queued_execution(self):
  self.consumer.enqueue(self.frame());self.config['enabled']=False;self.save();result=self.consumer.step();self.assertEqual(result['state'],'rejected')
 def test_expired_and_modified_queue_never_execute(self):
  from unittest.mock import patch
  frame=self.frame();self.consumer.enqueue(frame)
  with patch('ziokt.dna_consumer.time.time',return_value=frame['header']['expires_at']+1):self.assertEqual(self.consumer.step()['state'],'rejected')
  frame=self.frame(2);self.consumer.enqueue(frame)
  with self.consumer.db() as db:db.execute("UPDATE jobs SET command=? WHERE sequence=2",(encoded({'bad':'command'}),))
  self.assertEqual(self.consumer.step()['state'],'rejected')
 def test_confirmed_source_replays_reads_and_halts_writes_after_reorg(self):
  import sqlite3
  source=self.base/'native-chain.db';frame=self.frame()
  with sqlite3.connect(source) as db:
   db.executescript('CREATE TABLE blocks(height INTEGER PRIMARY KEY,hash TEXT,transactions TEXT);CREATE TABLE transactions(hash TEXT,type TEXT,data TEXT,block_height INTEGER);CREATE TABLE block_work(hash TEXT,proof TEXT);')
   db.executemany('INSERT INTO blocks VALUES(?,?,?)',[(0,'c'*64,'[]'),(1,'d'*64,json.dumps(['e'*64])),(2,'f'*64,'[]')])
   db.executemany('INSERT INTO block_work VALUES(?,?)',[(x,json.dumps({'schema':'corium.dna-work.v1','recovery':'a'*64,'policy':'b'*64})) for x in ['d'*64,'f'*64]])
   db.execute('INSERT INTO transactions VALUES(?,?,?,1)',('e'*64,'ziokt_content',json.dumps({'content_type':'application/vnd.ziokt.rna+json','text':json.dumps(frame)})))
  self.config['chain_source']={'database':str(source),'genesis':'c'*64,'confirmations':1,'start_height':1};self.save()
  self.assertEqual(self.consumer.poll_chain(),1);self.assertEqual(self.consumer.step()['state'],'completed_read');self.assertEqual(self.consumer.poll_chain(),0)
  with sqlite3.connect(source) as db:db.execute('UPDATE blocks SET hash=? WHERE height=1',('0'*64,))
  with sqlite3.connect(source) as db:db.execute('UPDATE block_work SET hash=? WHERE hash=?',('0'*64,'d'*64))
  self.assertEqual(self.consumer.poll_chain(),1);self.assertIsNone(self.consumer.step())
  with self.consumer.db() as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)
   self.assertEqual(db.execute('SELECT hash FROM chain_cursor WHERE slot=1').fetchone()[0],'0'*64)
  self.config['targets']['corium']['actions'].append('content.publish');self.save()
  with sqlite3.connect(source) as db:db.execute('UPDATE blocks SET hash=? WHERE height=1',('1'*64,))
  with self.assertRaises(PermissionError):self.consumer.poll_chain()
 def test_primary_source_uses_same_consumer_without_dna_domain_confusion(self):
  import sqlite3
  from ziokt.dna_consumer import primary_domain
  source=self.base/'primary-chain.db';genesis='c'*64
  self.config['chain']=primary_domain('my-business',genesis)
  command={'schema':'ziokt.dna-command.v1','component':'corium','operation':'status.get','resource':'','arguments':{},'expected_revision':None}
  frame=rna_sign(self.key,self.config['chain'],self.config['policy'],self.sender,1,int(time.time()),encoded(command))
  with sqlite3.connect(source) as db:
   db.executescript('CREATE TABLE blocks(height INTEGER PRIMARY KEY,hash TEXT,transactions TEXT);CREATE TABLE transactions(hash TEXT,type TEXT,data TEXT,block_height INTEGER);CREATE TABLE block_work(hash TEXT,proof TEXT);')
   db.executemany('INSERT INTO blocks VALUES(?,?,?)',[(0,genesis,'[]'),(1,'d'*64,json.dumps(['e'*64])),(2,'f'*64,'[]')])
   db.execute('INSERT INTO block_work VALUES(?,?)',('d'*64,json.dumps({'schema':'corium.native-block-work.v2','policy':'b'*64})))
   db.execute('INSERT INTO transactions VALUES(?,?,?,1)',('e'*64,'ziokt_content',json.dumps({'content_type':'application/vnd.ziokt.rna+json','text':json.dumps(frame)})))
  self.config['chain_source']={'database':str(source),'genesis':genesis,'confirmations':1,'start_height':1,'role':'primary','network_id':'my-business'};self.save()
  self.assertEqual(self.consumer.poll_chain(),1);self.assertEqual(self.consumer.step()['state'],'completed_read')
  self.assertNotEqual(primary_domain('other-business',genesis),self.config['chain'])
  self.config['chain_source']['network_id']='other-business';self.save()
  with self.assertRaises(ValueError):self.consumer.settings()

 def test_installer_can_replace_readonly_runtime_without_rotating_credentials(self):
  import sqlite3,subprocess,sys
  from pathlib import Path
  source=self.base/'install-chain.db'
  with sqlite3.connect(source) as db:
   db.executescript('CREATE TABLE blocks(height INTEGER,hash TEXT);CREATE TABLE block_work(hash TEXT,proof TEXT);')
   db.executemany('INSERT INTO blocks VALUES(?,?)',[(0,'c'*64),(1,'d'*64)])
   db.execute('INSERT INTO block_work VALUES(?,?)',('d'*64,json.dumps({'schema':'corium.dna-work.v1','recovery':'a'*64,'policy':'b'*64})))
  root=self.base/'installation';tool=Path(__file__).resolve().parents[1]/'tools/deploy_dna_consumer.py'
  command=[sys.executable,str(tool),'--root',str(root),'--federation',str(self.fpath),'--chain-database',str(source)]
  subprocess.run(command,check=True,capture_output=True)
  key=(root/'producer.pem').read_bytes();config=(root/'consumer.json').read_bytes()
  (root/'runtime/ziokt/dna_consumer.py').chmod(0o444)
  subprocess.run(command,check=True,capture_output=True)
  self.assertEqual((root/'producer.pem').read_bytes(),key);self.assertEqual((root/'consumer.json').read_bytes(),config)
  self.assertEqual((root/'runtime/ziokt/dna_consumer.py').stat().st_mode&0o777,0o600)

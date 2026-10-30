"""Opt-in RNA consumer with persistent replay state and native execution gates.

RNA acceptance, native commitment and application readiness are distinct states.
No shell command, package installation or caller-selected provider is accepted.
"""
import argparse,hashlib,http.server,json,re,sqlite3,threading,time
from pathlib import Path
from contextlib import contextmanager,closing
from .protocol import encoded,secure_read,strict_json,ProtocolError
from .dna_protocol import rna_open
from cryptography.exceptions import InvalidSignature
from .client import NativeClient
from .config import load

ACTIONS={'status.get','content.publish','wiki.create','artifact.stage'}

def primary_domain(network,genesis):
 if not isinstance(network,str) or re.fullmatch('[A-Za-z0-9_-]{1,64}',network) is None:raise ValueError('pinned primary network required')
 return hashlib.sha256(b'Ziokt/NativeBusinessChain/v1\0'+encoded({'network':network,'genesis':genesis})).hexdigest()

class Consumer:
 def __init__(self,path):
  self.path=Path(path);config=self.settings();root=Path(config['state'])
  if not root.is_absolute() or root.is_symlink():raise ValueError('private absolute consumer state required')
  root.mkdir(parents=True,mode=0o700,exist_ok=True);root.chmod(0o700);self.dbpath=root/'consumer.sqlite'
  if self.dbpath.is_symlink():raise ValueError('consumer database symlink')
  self.lock=threading.RLock();self.stop=threading.Event()
  with self.db() as db:db.executescript('''CREATE TABLE IF NOT EXISTS sequences(sender TEXT PRIMARY KEY,sequence INTEGER);
  CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,sender TEXT,sequence INTEGER,frame BLOB,command BLOB,state TEXT,result BLOB,error TEXT,attempts INTEGER,next_at INTEGER,UNIQUE(sender,sequence));''')
  self.dbpath.chmod(0o600)
  with self.db() as db:db.execute('CREATE TABLE IF NOT EXISTS chain_cursor(slot INTEGER PRIMARY KEY,height INTEGER,hash TEXT)')
 @contextmanager
 def db(self):
  with closing(sqlite3.connect(self.dbpath,timeout=10)) as connection:
   with connection:yield connection
 def settings(self):
  c=strict_json(secure_read(self.path,65536))
  if not isinstance(c,dict) or set(c)-{'chain_source'}!={'schema','enabled','state','listen','port','chain','policy','senders','targets'} or c['schema']!='ziokt.dna-consumer.v1' or type(c['enabled'])is not bool or c['listen']!='127.0.0.1' or type(c['port'])is not int or not 1024<=c['port']<=65535:raise ValueError('exact loopback consumer configuration required')
  if not isinstance(c['senders'],dict) or not 1<=len(c['senders'])<=32 or not isinstance(c['targets'],dict) or not 1<=len(c['targets'])<=16:raise ValueError('bounded pinned producers and consumers required')
  for value in (c['chain'],c['policy'],*c['senders']):
   if not isinstance(value,str) or re.fullmatch('[a-f0-9]{64}',value) is None:raise ValueError('pinned domain digest required')
  for producer in c['senders'].values():
   if not isinstance(producer,dict) or set(producer)!={'public_key','components'} or not isinstance(producer['public_key'],str) or not isinstance(producer['components'],list) or not producer['components'] or any(not isinstance(x,str) or x not in c['targets'] for x in producer['components']):raise ValueError('explicit producer delegation required')
  for target in c['targets'].values():
   if not isinstance(target,dict) or set(target)!={'federation','provider','actions'} or not isinstance(target['actions'],list) or any(not isinstance(x,str) or x not in ACTIONS for x in target['actions']) or not isinstance(target['federation'],str) or not Path(target['federation']).is_absolute() or not isinstance(target['provider'],str):raise ValueError('explicit native action allowlist required')
  if 'chain_source' in c:
   source=c['chain_source']
   if not isinstance(source,dict) or set(source)-{'role','network_id'}!={'database','genesis','confirmations','start_height'} or not isinstance(source['database'],str) or not Path(source['database']).is_absolute() or not isinstance(source['genesis'],str) or re.fullmatch('[a-f0-9]{64}',source['genesis']) is None or type(source['confirmations']) is not int or not 1<=source['confirmations']<=100 or type(source['start_height']) is not int or source['start_height']<1:raise ValueError('pinned confirmed native chain source required')
   if source.get('role','dna') not in {'primary','dna'}:raise ValueError('explicit primary or DNA source role required')
   if source.get('role')=='primary' and primary_domain(source.get('network_id'),source['genesis'])!=c['chain']:raise ValueError('primary chain domain mismatch')
  return c
 def authorize(self,c,sender,command):
  if c['enabled'] is not True:raise PermissionError('consumer disabled')
  if not isinstance(command,dict) or set(command)!={'schema','component','operation','resource','arguments','expected_revision'} or command['schema']!='ziokt.dna-command.v1':raise ValueError('exact DNA consumer command required')
  target=c['targets'].get(command['component']);producer=c['senders'].get(sender)
  if not target or not producer or set(producer)!={'public_key','components'} or command['component'] not in producer['components'] or command['operation'] not in target['actions']:raise PermissionError('producer/target/action not authorized')
  if not isinstance(command['resource'],str) or len(command['resource'])>300 or not isinstance(command['arguments'],dict) or len(encoded(command['arguments']))>4096:raise ValueError('bounded native command required')
  if command['operation']=='status.get' and (command['resource'] or command['arguments'] or command['expected_revision'] is not None):raise ValueError('status.get has no execution arguments')
  return target
 def enqueue(self,frame):
  if len(encoded(frame))>16384:raise ValueError('RNA frame budget')
  c=self.settings();sender=frame.get('header',{}).get('sender');producer=c['senders'].get(sender)
  if not producer:raise PermissionError('unrecognized RNA sender')
  id=hashlib.sha256(b'Ziokt/DNAConsumer/frame/v1\n'+encoded(frame)).hexdigest()
  with self.lock,self.db() as db:
   db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT state FROM jobs WHERE id=?',(id,)).fetchone()
   if old:return {'id':id,'state':old[0],'duplicate':True,'application_ready':False}
   seq=db.execute('SELECT sequence FROM sequences WHERE sender=?',(sender,)).fetchone()
   payload=rna_open(frame,producer['public_key'],c['chain'],c['policy'],sender,seq[0] if seq else 0,int(time.time()))
   command=strict_json(payload,8192);self.authorize(c,sender,command)
   if db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]>=4096:raise RuntimeError('consumer journal quota; archive before resuming')
   sequence=frame['header']['sequence'];db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,\'queued\',NULL,\'\',0,0)',(id,sender,sequence,encoded(frame),encoded(command)));db.execute('INSERT OR REPLACE INTO sequences VALUES(?,?)',(sender,sequence))
  return {'id':id,'state':'queued','duplicate':False,'application_ready':False}
 def step(self):
  with self.lock,self.db() as db:row=db.execute("SELECT id,sender,command,attempts,frame,state FROM jobs WHERE state IN ('queued','dispatching','retry','unknown') AND next_at<=? ORDER BY rowid LIMIT 1",(int(time.time()),)).fetchone()
  if row is None:return None
  id,sender,raw,attempts,frame_raw,previous_state=row;command=strict_json(raw,8192)
  native_started=False
  try:
   c=self.settings();target=self.authorize(c,sender,command)
   frame=strict_json(frame_raw,16384);header=frame['header'];now=int(time.time())
   if hashlib.sha256(b'Ziokt/DNAConsumer/frame/v1\n'+encoded(frame)).hexdigest()!=id:raise PermissionError('stored frame integrity')
   payload=rna_open(frame,c['senders'][sender]['public_key'],c['chain'],c['policy'],sender,0,header['issued_at'])
   if payload!=encoded(command):raise PermissionError('stored command integrity')
   expired=not header['issued_at']<=now<=header['expires_at']
   if expired and previous_state in {'queued','retry'}:raise PermissionError('RNA expired before dispatch')
   federation=load(target['federation']);provider=next((p for p in federation['providers'] if p['provider_id']==target['provider']),None)
   if federation.get('enabled') is not True or provider is None:raise PermissionError('native target disabled')
   client=NativeClient(federation['federation_id'],provider)
   with self.db() as db:db.execute("UPDATE jobs SET state='dispatching' WHERE id=?",(id,))
   if command['operation']=='status.get':result={'native_status':client.call('status.get',{}),'application_ready':False};state='completed_read'
   else:
    native_started=True
    operation='dna-'+id[:56]
    try:result=client.call('operation.reconcile',{'operation_id':operation})
    except ProtocolError as error:
     if error.code!='OPERATION_NOT_FOUND':raise
     if expired:raise PermissionError('expired unexecuted command')
     result=client.call('operation.prepare',{'operation_id':operation,'action':command['operation'],'resource':command['resource'],'arguments':command['arguments'],'expected_revision':command['expected_revision']})
    if result['state']=='prepared' and expired:raise PermissionError('expired prepared command')
    if result['state']=='prepared':result=client.call('operation.commit',{'operation_id':operation,'plan_digest':result['plan_digest']})
    state='native_committed' if result['state']=='committed' else 'unknown' if result['state']=='unknown' else 'rejected'
   if len(encoded(result))>65536:raise ValueError('native receipt budget')
   with self.db() as db:db.execute('UPDATE jobs SET state=?,result=?,error=\'\',next_at=? WHERE id=?',(state,encoded(result),int(time.time())+30,id))
   return {'id':id,'state':state,'application_ready':False}
  except Exception as error:
   state=('unknown' if native_started or previous_state in {'dispatching','unknown'} else 'rejected') if isinstance(error,(PermissionError,ValueError,InvalidSignature)) else ('unknown' if native_started or previous_state in {'dispatching','unknown'} else 'retry');attempts+=1
   with self.db() as db:db.execute('UPDATE jobs SET state=?,error=?,attempts=?,next_at=? WHERE id=?',(state,getattr(error,'code',type(error).__name__),attempts,int(time.time())+min(3600,15*2**min(attempts,8)),id))
   return {'id':id,'state':state,'error':getattr(error,'code',type(error).__name__),'application_ready':False}
 def poll_chain(self):
  """Consume confirmed native-validated content; halt on a consumed-chain reorg.

  The local Corium database is the validation boundary, never a remote SQL feed.
  Every RNA frame still needs its own pinned sender signature and live delegation.
  """
  c=self.settings();source=c.get('chain_source')
  if not source or not c['enabled']:return 0
  path=Path(source['database'])
  if path.is_symlink() or not path.is_file():raise ValueError('native chain database unavailable')
  with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)) as chain:
   chain.execute('BEGIN')
   if chain.execute('SELECT hash FROM blocks WHERE height=0').fetchone()!=(source['genesis'],):raise PermissionError('chain genesis mismatch')
   tip=chain.execute('SELECT MAX(height) FROM blocks').fetchone()[0]
   with self.db() as db:cursor=db.execute('SELECT height,hash FROM chain_cursor WHERE slot=1').fetchone()
   if cursor and chain.execute('SELECT hash FROM blocks WHERE height=?',(cursor[0],)).fetchone()!=(cursor[1],):raise PermissionError('consumed chain reorganized; operator review required')
   height=cursor[0]+1 if cursor else source['start_height'];count=0
   for h in range(height,min(tip-source['confirmations']+1,height+16)):
    block=chain.execute('SELECT hash,transactions FROM blocks WHERE height=?',(h,)).fetchone()
    if block is None:raise ValueError('native chain gap')
    proof_row=chain.execute('SELECT proof FROM block_work WHERE hash=?',(block[0],)).fetchone()
    proof=strict_json(proof_row[0].encode(),65536) if proof_row else {}
    if source.get('role','dna')=='dna':
     if proof.get('schema')!='corium.dna-work.v1' or proof.get('recovery')!=c['chain'] or proof.get('policy')!=c['policy']:raise PermissionError('native DNA identity or policy changed')
    elif proof.get('schema')!='corium.native-block-work.v2' or proof.get('policy')!=c['policy'] or primary_domain(source['network_id'],source['genesis'])!=c['chain']:
     raise PermissionError('native primary identity or policy changed')
    listed=strict_json(block[1].encode(),1048576)
    rows=chain.execute("SELECT hash,data FROM transactions WHERE block_height=? AND type='ziokt_content' ORDER BY hash",(h,)).fetchall()
    for txid,data in rows:
     if txid not in listed:raise ValueError('transaction not committed by block')
     value=strict_json(data.encode(),65536)
     if value.get('content_type')!='application/vnd.ziokt.rna+json':continue
     try:self.enqueue(strict_json(value['text'].encode(),16384));count+=1
     except (ValueError,PermissionError,KeyError,TypeError,InvalidSignature):pass # Untrusted content cannot stall later valid commands.
    with self.db() as db:db.execute('INSERT OR REPLACE INTO chain_cursor VALUES(1,?,?)',(h,block[0]))
   return count
 def run(self):
  while not self.stop.wait(1):
   try:self.poll_chain();self.step()
   except Exception as error:
    # Fail closed: a source failure never dispatches pending chain commands.
    print(json.dumps({'consumer_error':type(error).__name__}),flush=True)

def server(consumer):
 c=consumer.settings()
 class Handler(http.server.BaseHTTPRequestHandler):
  def setup(self):super().setup();self.connection.settimeout(5)
  def log_message(self,*args):pass
  def reply(self,status,value):
   raw=encoded(value);self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
  def do_GET(self):
   if self.path!='/status':return self.reply(404,{'error':'NOT_FOUND'})
   with consumer.db() as db:counts=dict(db.execute('SELECT state,count(*) FROM jobs GROUP BY state'))
   self.reply(200,{'schema':'ziokt.dna-consumer-status.v1','enabled':consumer.settings()['enabled'],'jobs':counts,'application_readiness':'not_inferred'})
  def do_POST(self):
   if self.path!='/rna' or self.headers.get('Origin') or self.headers.get('Transfer-Encoding'):return self.reply(403,{'error':'REJECTED'})
   try:
    n=int(self.headers.get('Content-Length','0'))
    if not 1<=n<=16384 or self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError()
    self.reply(202,consumer.enqueue(strict_json(self.rfile.read(n),16384)))
   except Exception:self.reply(400,{'error':'RNA_REJECTED'})
 return http.server.HTTPServer((c['listen'],c['port']),Handler)

def main():
 import signal
 parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--once',action='store_true');args=parser.parse_args();consumer=Consumer(args.config)
 if args.once:print(json.dumps(consumer.step()));return
 http=server(consumer);thread=threading.Thread(target=consumer.run,daemon=True);thread.start()
 try:http.serve_forever()
 finally:consumer.stop.set();http.server_close();thread.join(35)
if __name__=='__main__':main()

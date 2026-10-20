"""Native Mailbox v2 through actual ETP engines and authorized Noise peers.

Reuses the CI-built gateway. No raw replica UDP runner or mocked transport.
"""
import base64,json,os,select,socket,subprocess,sys,tempfile,time
from pathlib import Path
from blake3 import blake3
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat,PrivateFormat,NoEncryption

def public(key):return key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)

def main():
 binary=str(Path(sys.argv[1]).resolve());copies=int(sys.argv[2])
 if copies not in (1,3,5):raise ValueError('replica mode')
 processes={};sequence=0;logs={}
 with tempfile.TemporaryDirectory(prefix='ziokt-native-mailbox-mesh-') as directory:
  root=Path(directory);addresses=[];configs=[]
  transport=[X25519PrivateKey.generate() for _ in range(copies)];signers=[Ed25519PrivateKey.generate() for _ in range(copies)]
  recipient=Ed25519PrivateKey.generate();owner=blake3(public(recipient)).digest()
  nonce=os.urandom(12);plaintext=b'Native encrypted mailbox mesh integration fixture';ciphertext=nonce+AESGCM(os.urandom(32)).encrypt(nonce,plaintext,b'Ziokt/mesh/CI')
  mid=owner+blake3(ciphertext).digest()
  for _ in range(copies):
   with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
    sock.bind(('127.0.0.1',0));addresses.append('127.0.0.1:'+str(sock.getsockname()[1]))
  for i in range(copies):
   config={'bind':addresses[i],'private_key':transport[i].private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption()).hex(),'peers':{addresses[j]:public(transport[j]).hex() for j in range(copies) if i!=j},'mailbox':{'database':str(root/('mailbox-'+str(i))),'replication':{'copies':copies,'signing_key':signers[i].private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption()).hex(),'peers':{addresses[j]:public(signers[j]).hex() for j in range(copies) if i!=j}}}}
   path=root/(str(i)+'.json');path.write_text(json.dumps(config));path.chmod(0o600);configs.append(path)
  def call(i,method,params):
   nonlocal sequence
   sequence+=1;proc=processes[i];proc.stdin.write(json.dumps({'id':sequence,'method':method,'params':params})+'\n');proc.stdin.flush()
   if not select.select([proc.stdout],[],[],15)[0]:raise AssertionError(('native response timeout',i,method))
   line=proc.stdout.readline()
   if not line:raise AssertionError(('native gateway exited',i,proc.poll()))
   result=json.loads(line)
   if result['id']!=sequence:raise AssertionError('native response correlation')
   return result
  def start(i):
   log=open(root/(str(i)+'.log'),'ab');logs[i]=log
   processes[i]=subprocess.Popen([binary,str(configs[i])],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,env={**os.environ,'TOKIO_WORKER_THREADS':'2'})
   result=call(i,'etp.mailbox.status',{})
   assert result['ok'] and result['result']['native_store']=='opened',result
   assert result['result']['copies_required']==copies
  def stop(i):
   proc=processes.pop(i,None)
   if proc:
    proc.terminate();proc.wait(timeout=10);proc.stdin.close();proc.stdout.close();logs.pop(i).close()
  def packet(i,op,body=b'',key=recipient):
   if op==1:data=bytes([2,op])+owner+body
   else:
    header=public(key)+int(time.time()).to_bytes(8,'big')+os.urandom(16)
    data=bytes([2,op])+header+key.sign(b'ETP_MAILBOX_V2\0'+bytes([op])+header+body)+body
   result=call(i,'etp.mailbox.request',{'frame_base64':base64.b64encode(data).decode()})
   return base64.b64decode(result['result']['frame_base64']) if result['ok'] else result
  def confirmed():
   deadline=time.monotonic()+70
   while time.monotonic()<deadline:
    result=packet(0,6,mid)
    if result==bytes([2,5,0,copies,copies]):return
    time.sleep(.5)
   raise AssertionError(('encrypted mesh durable replication not confirmed',result))
  try:
   for i in range(copies):start(i)
   deposited=packet(0,1,ciphertext);assert isinstance(deposited,bytes)
   confirmed()
   for i in range(copies):
    fetched=packet(i,2);assert isinstance(fetched,bytes) and fetched[2]==1 and ciphertext in fetched
    assert plaintext not in fetched
   assert isinstance(packet(0,6,mid,key=Ed25519PrivateKey.generate()),dict),'foreign recipient proof accepted'
   if copies>1:stop(copies-1)
   deleted=packet(0,4,mid);assert isinstance(deleted,bytes)
   if copies>1:
    assert deleted[2]==1,'offline replica falsely confirmed deletion'
    start(copies-1)
   confirmed()
   for i in range(copies):
    assert packet(i,2)[2]==0
    stop(i);start(i);assert packet(i,2)[2]==0
   confirmed();assert isinstance(packet(0,1,ciphertext),dict),'retained tombstone did not prevent resurrection'
   stats=[]
   for i in range(copies):
    result=call(i,'etp.stats',{});assert result['ok'];stats.append(result['result']['native'])
   print(json.dumps({'schema':'ziokt.mailbox-mesh-evidence.v1','copies':copies,'independent_native_engines':copies,'transport':'ETP authorized Noise sessions, composite flavor stream 4','durable_replica_confirmation':True,'recipient_proof_rejection':True,'offline_delete_rejoin':True,'crash_recovery':True,'resurrection_rejected':True,'native_stats':stats,'status':'passed'}))
  except BaseException:
   for i in list(processes):stop(i)
   for path in sorted(root.glob('*.log')):print('native mesh diagnostic '+path.name+': '+path.read_text(errors='replace')[-3000:],file=sys.stderr)
   raise
  finally:
   for i in list(processes):stop(i)

if __name__=='__main__':main()

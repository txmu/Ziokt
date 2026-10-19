"""Run native Mailbox v2 replica mode in separate UDP processes (CI only)."""
import base64,json,os,select,socket,subprocess,sys,tempfile,time
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat


def main():
 binary=str(Path(sys.argv[1]).resolve());copies=int(sys.argv[2]);processes={}
 with tempfile.TemporaryDirectory() as temp:
  root=Path(temp);addresses=[];keys=[];public=[];configs=[]
  for i in range(copies):
   with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:sock.bind(('127.0.0.1',0));addresses.append('127.0.0.1:'+str(sock.getsockname()[1]))
   key=os.urandom(32);keys.append(key.hex());public.append(Ed25519PrivateKey.from_private_bytes(key).public_key().public_bytes(Encoding.Raw,PublicFormat.Raw).hex())
  for i in range(copies):
   path=root/(str(i)+'.json');path.write_text(json.dumps({'database':str(root/str(i)),'bind':addresses[i],'copies':copies,'key':keys[i],'peers':{public[j]:addresses[j] for j in range(copies) if i!=j}}));path.chmod(0o600);configs.append(path)
  def start(i):
   proc=subprocess.Popen([binary,str(configs[i])],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);processes[i]=proc
   if not select.select([proc.stdout],[],[],10)[0]:raise AssertionError('native node startup timeout')
   line=proc.stdout.readline()
   if not line:raise AssertionError(proc.stderr.read())
   assert json.loads(line)['ready']
  def stop(i):
   proc=processes.pop(i,None)
   if proc:proc.terminate();proc.wait(timeout=5);proc.stdin.close();proc.stdout.close();proc.stderr.close()
  ciphertext=base64.b64encode(b'opaque encrypted test envelope').decode()
  def call(i,op):
   proc=processes[i];proc.stdin.write(json.dumps({'operation':op,'ciphertext':ciphertext})+'\n');proc.stdin.flush()
   if not select.select([proc.stdout],[],[],5)[0]:raise AssertionError('native mailbox response timeout')
   result=json.loads(proc.stdout.readline());return base64.b64decode(result['response']) if 'response' in result else result
  def wait_full():
   until=time.monotonic()+15
   while time.monotonic()<until:
    result=call(0,'status')
    if isinstance(result,bytes) and result[:3]==bytes([2,5,0]) and result[3:]==bytes([copies,copies]):return
    time.sleep(.1)
   raise AssertionError(('durable replicas not confirmed',result))
  try:
   for i in range(copies):start(i)
   deposited=call(0,'deposit');assert isinstance(deposited,bytes)
   wait_full()
   for i in range(copies):assert call(i,'fetch')[2]==1
   if copies>1:
    stop(copies-1)
   deleted=call(0,'delete');assert isinstance(deleted,bytes)
   if copies>1:
    assert deleted[2]==1  # must not claim all replicas while peer is offline
    start(copies-1)
   wait_full()
   for i in range(copies):
    assert call(i,'fetch')[2]==0
    stop(i);start(i)
    assert call(i,'fetch')[2]==0
   assert isinstance(call(0,'deposit'),dict)  # tombstone blocks stale re-deposit
   print(json.dumps({'copies':copies,'independent_processes':copies,'network':'UDP','durable_receipts':True,'offline_delete_rejoin':True,'restart_recovery':True,'status':'passed'}))
  except BaseException:
   for i,proc in list(processes.items()):
    proc.terminate();proc.wait(timeout=5)
    print('native diagnostic '+str(i)+': '+proc.stderr.read()[-4000:],file=sys.stderr)
   raise
  finally:
   for i in list(processes):stop(i)

if __name__=='__main__':main()

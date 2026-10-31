"""Real native UDP engines under deterministic kernel packet loss; no transport substitutes."""
import base64,hashlib,json,os,secrets,shutil,socket,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from ziokt.etp import EtpGateway
binary=Path(sys.argv[1]).resolve();chain='ZIOKT_UDP_'+str(os.getpid());workers=[];rules=[]
def iptables(*args):subprocess.run(['sudo','iptables',*map(str,args)],check=True,stdout=subprocess.DEVNULL)
with tempfile.TemporaryDirectory(prefix='ziokt-native-udp-loss-')as temporary:
 root=Path(temporary);installed=root/'gateway';shutil.copyfile(binary,installed);installed.chmod(0o700);digest='sha256:'+hashlib.sha256(installed.read_bytes()).hexdigest()
 reservations=[socket.socket(socket.AF_INET,socket.SOCK_DGRAM)for _ in range(3)]
 for s in reservations:s.bind(('127.0.0.1',0))
 ports=[s.getsockname()[1]for s in reservations];addresses=['127.0.0.1:'+str(p)for p in ports]
 for s in reservations:s.close()
 keys=[X25519PrivateKey.generate()for _ in ports]
 created=False;results=[]
 try:
  for i in range(3):
   cfg=root/(str(i)+'.json');cfg.write_text(json.dumps({'bind':addresses[i],'transport':'udp','private_key':keys[i].private_bytes_raw().hex(),'peers':{a:keys[j].public_key().public_bytes_raw().hex()for j,a in enumerate(addresses)if j!=i},'relay':True}));cfg.chmod(0o600)
   worker=EtpGateway(installed,digest,cfg);workers.append(worker);worker.call('etp.stats',{})
  iptables('-N',chain);created=True
  # Drop every eighth full onion fragment, leaving control traffic and unrelated jobs alone.
  iptables('-A',chain,'-m','length','--length','1000:1200','-m','statistic','--mode','nth','--every','8','--packet','0','-j','DROP')
  for source in [0,2]:
   rule=['-p','udp','--sport',str(ports[source]),'--dport',str(ports[1]),'-j',chain];iptables('-I','OUTPUT',*rule);rules.append(rule)
  cipher=AESGCM(AESGCM.generate_key(bit_length=256))
  for source,dest,size in [(0,2,16384),(2,0,65536)]:
   plain=secrets.token_bytes(size-28);nonce=secrets.token_bytes(12);sealed=nonce+cipher.encrypt(nonce,plain,b'ziokt-udp-kernel-loss-v1')
   ack=workers[source].call('etp.onion.send',{'hops':[addresses[1],addresses[dest]],'ciphertext':base64.b64encode(sealed).decode()});assert ack['accepted']and not ack['delivery_confirmed']
   value=workers[dest].call('etp.receive',{});assert value['ciphertext']is not None,'loss recovery failed'
   received=b''.join(base64.b64decode(part)for part in value['ciphertext']);assert received==sealed;assert cipher.decrypt(received[:12],received[12:],b'ziokt-udp-kernel-loss-v1')==plain
   assert workers[dest].call('etp.receive',{})['ciphertext']is None,'duplicate application delivery'
   results.append({'sealed_bytes':size,'plaintext_sha256':hashlib.sha256(plain).hexdigest(),'authenticated_delivery':True,'duplicate_delivery':False})
  counters=subprocess.check_output(['sudo','iptables','-L',chain,'-v','-n','-x'],text=True);assert any(int(line.split()[0])>0 for line in counters.splitlines()if 'DROP'in line),'fault rule did not drop actual datagrams'
  print(json.dumps({'schema':'ziokt.native-udp-loss-regression.v1','native_binary':digest,'actual_kernel_udp':True,'fault':'every eighth full onion datagram dropped by kernel','native_engines':3,'hops':2,'results':results}))
 finally:
  for rule in reversed(rules):iptables('-D','OUTPUT',*rule)
  if created:iptables('-F',chain);iptables('-X',chain)
  for worker in workers:worker.close()

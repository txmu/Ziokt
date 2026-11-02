"""Build a signed observer's graph from current native authenticated probes."""
import hashlib,sqlite3,subprocess,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

def build_snapshot(root, chain_root, native_source, network='ziokt-main'):
 root,chain_root,native_source=map(Path,(root,chain_root,native_source))
 identity=hashlib.sha256((chain_root/'etc/corix/networks'/network/'identity.key.pub').read_text().rstrip('\n').encode()).hexdigest()
 now=int(time.time());nodes=[{'id':identity,'kind':'local-validator','state':'configured','seen_at':now}];edges=[]
 path=chain_root/'var/lib/corix/p2p/dht.db'
 with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
  peers=db.execute('SELECT id,address_type,address,port,last_seen FROM nodes ORDER BY last_seen DESC LIMIT 16').fetchall()
 script='export CORIUM_ROOT="$2" CORIUM_NETWORK_ID_OVERRIDE="$3"; source "$1"; load_config || exit; P2P_MESSAGE_TIMEOUT=2; _dht_send_message_direct "$4" PING observer-live'
 candidates=[]
 for peer,kind,address,port,seen in peers:
  if peer==identity or len(peer)!=64 or not port:continue
  forms={f'{kind}:{address}:{port}',f'{kind}:[{address}]:{port}'}
  if peer in {hashlib.sha256(s.encode()).hexdigest() for s in forms}:continue
  candidates.append(peer)
 def probe(peer):
  try:
   p=subprocess.run(['bash','-c',script,'observer-live',str(native_source),str(chain_root),network,peer],capture_output=True,text=True,timeout=8)
   return p.returncode==0 and p.stdout.strip().splitlines()[-1:]==['PONG:'+peer]
  except (OSError,subprocess.TimeoutExpired):return False
 with ThreadPoolExecutor(max_workers=4) as pool:
  verified_peers=list(pool.map(probe,candidates))
 for peer,verified in zip(candidates,verified_peers):
  if verified:
   nodes.append({'id':peer,'kind':'peer','state':'connected','seen_at':now});edges.append({'source':identity,'target':peer,'relation':'peer','state':'connected'})
 return {'observed_at':now,'nodes':nodes,'edges':edges}

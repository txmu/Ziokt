#!/usr/bin/env python3
"""Probe explicitly approved native peers; publish bounded live topology.

Uses Corium's existing signed transport and pinned peer TLS configuration.
No discovery, port scan, inbound listener or consensus operation is performed.
"""
import argparse,hashlib,ipaddress,json,os,re,secrets,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.protocol import encoded,secure_read,strict_json

def collect(path):
 c=strict_json(secure_read(Path(path),16384))
 if not isinstance(c,dict) or not ({'schema','source','source_sha256','root','network','snapshot','evidence','local_id'} <= set(c)) or c['schema']!='ziokt.native-topology-probe.v1':
  raise ValueError('exact approved peer probe configuration required')
 if not ({'peer'} <= set(c) or {'peers'} <= set(c)) or set(c)-{'schema','source','source_sha256','root','network','snapshot','evidence','local_id','peer','peers'}:
  raise ValueError('approved peer or peers required')
 for name in ('source','root','snapshot','evidence'):
  if not isinstance(c[name],str) or not Path(c[name]).is_absolute() or Path(c[name]).is_symlink():raise ValueError('regular absolute paths required')
 if not isinstance(c['network'],str) or re.fullmatch('[A-Za-z0-9_-]{1,64}',c['network']) is None:raise ValueError('native network required')
 if re.fullmatch('[a-f0-9]{64}',c['local_id']) is None or re.fullmatch('[a-f0-9]{64}',c['source_sha256']) is None:raise ValueError('pinned digest required')
 raw_peers = c['peers'] if 'peers' in c else [c['peer']]
 if not isinstance(raw_peers,list) or not raw_peers or len(raw_peers)>32:raise ValueError('valid approved peers list required')
 peers=[]
 for peer in raw_peers:
  if not isinstance(peer,dict) or set(peer)!={'id','host','port'} or type(peer['port'])is not int or not 1<=peer['port']<=65535:raise ValueError('explicitly approved native peer required')
  if re.fullmatch('[a-f0-9]{64}',peer['id']) is None:raise ValueError('pinned digest required')
  ipaddress.ip_address(peer['host'])
  peers.append(peer)
 if hashlib.sha256(secure_read(Path(c['source']),8*1024*1024,private=None)).hexdigest()!=c['source_sha256']:raise ValueError('native source changed; review before probing')
 now=int(time.time())
 nodes=[{'id':c['local_id'],'kind':'local-validator','state':'configured','seen_at':now}]
 edges=[]
 evidence_peers=[]
 for peer in peers:
  challenge=secrets.token_hex(32);at=int(time.time());response='';error=None
  try:
   result=subprocess.run(['bash','-c','source "$1"; load_config; dht_send_message "$2" "$3" PING "$4"','ziokt-approved-peer-probe',c['source'],peer['host'],str(peer['port']),challenge],env=dict(os.environ,CORIUM_ROOT=c['root'],CORIUM_NETWORK_ID_OVERRIDE=c['network']),capture_output=True,timeout=45)
   response=result.stdout.decode('utf-8','strict').strip()
   if result.returncode or response!='PONG:'+peer['id']:raise ValueError('native response did not match pinned peer')
  except (OSError,ValueError,subprocess.SubprocessError) as e:error=type(e).__name__
  p_now=int(time.time())
  state='native-rpc-responded' if error is None else 'unreachable'
  nodes.append({'id':peer['id'],'kind':'independent-validator','state':state,'address':peer['host']+':'+str(peer['port']),'seen_at':p_now})
  edges.append({'source':c['local_id'],'target':peer['id'],'relation':'native-public-rpc','state':state})
  evidence_peers.append({'peer':peer['id'],'host':peer['host'],'port':peer['port'],'started_at':at,'sampled_at':p_now,'challenge_sha256':hashlib.sha256(challenge.encode()).hexdigest(),'response_sha256':hashlib.sha256(response.encode()).hexdigest(),'state':state,'error':error})
 snapshot_now=int(time.time())
 for n in nodes:
  if n['id']==c['local_id']:
   n['seen_at']=snapshot_now
 snapshot={'schema':'ziokt.p2p-snapshot.v1','component':'corium','observed_at':snapshot_now,'nodes':nodes,'edges':edges}
 evidence={'schema':'ziokt.native-topology-probe-result.v1','sampled_at':snapshot_now,'network':c['network'],'native_source_sha256':c['source_sha256'],'peers':evidence_peers,'state':'native-rpc-responded' if any(p['state']=='native-rpc-responded' for p in evidence_peers) else 'unreachable'}
 if 'peer' in c and not 'peers' in c:
  evidence['peer']=peers[0]['id']
  evidence['challenge_sha256']=evidence_peers[0]['challenge_sha256']
  evidence['response_sha256']=evidence_peers[0]['response_sha256']
  evidence['error']=evidence_peers[0]['error']
  evidence['started_at']=evidence_peers[0]['started_at']
 for name,value in [('snapshot',snapshot),('evidence',evidence)]:
  p=Path(c[name]);p.parent.mkdir(mode=0o700,parents=True,exist_ok=True);tmp=p.with_name(p.name+'.'+secrets.token_hex(8)+'.new');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'wb') as out:out.write(encoded(value));out.flush();os.fsync(out.fileno())
  tmp.replace(p)
 return evidence
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args();print(json.dumps(collect(a.config),sort_keys=True))

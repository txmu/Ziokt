#!/usr/bin/env python3
"""Probe one explicitly approved native peer; publish bounded live topology.

Uses Corium's existing signed transport and pinned peer TLS configuration.
No discovery, port scan, inbound listener or consensus operation is performed.
"""
import argparse,hashlib,ipaddress,json,os,re,secrets,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.protocol import encoded,secure_read,strict_json

def collect(path):
 c=strict_json(secure_read(Path(path),16384))
 if not isinstance(c,dict) or set(c)!={'schema','source','source_sha256','root','network','snapshot','evidence','local_id','peer'} or c['schema']!='ziokt.native-topology-probe.v1':raise ValueError('exact approved peer probe configuration required')
 for name in ('source','root','snapshot','evidence'):
  if not isinstance(c[name],str) or not Path(c[name]).is_absolute() or Path(c[name]).is_symlink():raise ValueError('regular absolute paths required')
 if not isinstance(c['network'],str) or re.fullmatch('[A-Za-z0-9_-]{1,64}',c['network']) is None:raise ValueError('native network required')
 peer=c['peer']
 if not isinstance(peer,dict) or set(peer)!={'id','host','port'} or type(peer['port'])is not int or not 1<=peer['port']<=65535:raise ValueError('one explicitly approved native peer required')
 for value in (c['local_id'],peer['id'],c['source_sha256']):
  if not isinstance(value,str) or re.fullmatch('[a-f0-9]{64}',value) is None:raise ValueError('pinned digest required')
 ipaddress.ip_address(peer['host'])
 if hashlib.sha256(secure_read(Path(c['source']),8*1024*1024,private=None)).hexdigest()!=c['source_sha256']:raise ValueError('native source changed; review before probing')
 challenge=secrets.token_hex(32);at=int(time.time());response='';error=None
 try:
  result=subprocess.run(['bash','-c','source "$1"; load_config; dht_send_message "$2" "$3" PING "$4"','ziokt-approved-peer-probe',c['source'],peer['host'],str(peer['port']),challenge],env=dict(os.environ,CORIUM_ROOT=c['root'],CORIUM_NETWORK_ID_OVERRIDE=c['network']),capture_output=True,timeout=45)
  response=result.stdout.decode('utf-8','strict').strip()
  if result.returncode or response!='PONG:'+peer['id']:raise ValueError('native response did not match pinned peer')
 except (OSError,ValueError,subprocess.SubprocessError) as e:error=type(e).__name__
 now=int(time.time());state='native-rpc-responded' if error is None else 'unreachable'
 snapshot={'schema':'ziokt.p2p-snapshot.v1','component':'corium','observed_at':now,'nodes':[{'id':c['local_id'],'kind':'local-validator','state':'configured','seen_at':now},{'id':peer['id'],'kind':'independent-validator','state':state,'address':peer['host']+':'+str(peer['port']),'seen_at':now}],'edges':[{'source':c['local_id'],'target':peer['id'],'relation':'native-public-rpc','state':state}]}
 evidence={'schema':'ziokt.native-topology-probe-result.v1','sampled_at':now,'started_at':at,'peer':peer['id'],'network':c['network'],'native_source_sha256':c['source_sha256'],'challenge_sha256':hashlib.sha256(challenge.encode()).hexdigest(),'response_sha256':hashlib.sha256(response.encode()).hexdigest(),'state':state,'error':error,'application_delivery':'not_assessed'}
 for name,value in [('snapshot',snapshot),('evidence',evidence)]:
  p=Path(c[name]);p.parent.mkdir(mode=0o700,parents=True,exist_ok=True);tmp=p.with_name(p.name+'.'+secrets.token_hex(8)+'.new');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'wb') as out:out.write(encoded(value));out.flush();os.fsync(out.fileno())
  tmp.replace(p)
 return evidence
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args();print(json.dumps(collect(a.config),sort_keys=True))

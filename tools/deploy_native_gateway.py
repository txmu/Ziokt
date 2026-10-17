#!/usr/bin/env python3
"""Deploy reviewed interpreted gateway sources and update native digest pins.

No compiler, package download, firewall change, or credential printing.
"""
import argparse,datetime,hashlib,json,os,shutil,subprocess,sys,time,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.gateway_store import database


def deploy(root,corix):
 root=Path(root).resolve();corix=Path(corix).resolve();repo=Path(__file__).resolve().parents[1]
 subprocess.run(['bash','-n',str(corix)],check=True)
 timestamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 backup=root/'private-bootstrap-backup'/('gateway-'+timestamp);backup.mkdir(mode=0o700,parents=True)
 for rel in ['config/federation.json','config/runtime-digests.json','config/Caddyfile','config/gateway.json','bin/corix_v108.sh']:
  source=root/rel
  if source.exists():shutil.copy2(source,backup/source.name)
 config=json.loads((root/'config/gateway.json').read_text())
 for name,path in [('forum',config['forum_db']),('dht',config['dht_db'])]:
  with database(path) as source, database(backup/(name+'.db')) as destination:source.backup(destination)
 target=root/'bin/corix_v108.sh';temporary=target.with_suffix('.new');shutil.copyfile(corix,temporary);temporary.chmod(0o755);temporary.replace(target)
 digest=hashlib.sha256(target.read_bytes()).hexdigest()
 federation=root/'config/federation.json';value=json.loads(federation.read_text())
 for provider in value['providers']:
  if provider['native_project']=='corium':provider['entrypoint_digest']='sha256:'+digest
 temporary=federation.with_suffix('.new');temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.chmod(0o600);temporary.replace(federation)
 digests=root/'config/runtime-digests.json';value=json.loads(digests.read_text())
 for name in value['digests']:
  if name.endswith('corix_v108.sh'):value['digests'][name]=digest
 value['updated']=timestamp;digests.write_text(json.dumps(value,indent=2)+'\n');digests.chmod(0o600)
 subprocess.run([sys.executable,'-m','ziokt','gateway','bootstrap','--root',str(root),'--state-root',config['state_root'],'--corix',str(target),'--network',config['network'],'--publish','--install'],cwd=repo,check=True)
 services=['ziokt-corium-p2p','ziokt-corium-consensus','ziokt-corium-relayer','ziokt-gateway']
 if (root/'mcp/mcp.json').is_file():services.append('ziokt-mcp')
 subprocess.run(['sudo','systemctl','restart',*services],check=True)
 deadline=time.monotonic()+30
 while True:
  try:
   with urllib.request.urlopen('http://127.0.0.1:'+str(config.get('port',8185))+'/api/gateway/status',timeout=3) as response:status=json.load(response)
   break
  except OSError:
   if time.monotonic()>deadline:raise
   time.sleep(.5)
 receipt={'schema':'ziokt.gateway-deployment.v1','at':timestamp,'corix_sha256':digest,'backup':str(backup),'status':status,'local_native_compilation':False}
 path=root/'config/gateway-deployment-receipt.json';path.write_text(json.dumps(receipt,indent=2)+'\n');path.chmod(0o600)
 return receipt

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--corix',type=Path,required=True);a=p.parse_args();print(json.dumps(deploy(a.root,a.corix)))

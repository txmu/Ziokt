#!/usr/bin/env python3
"""Deploy reviewed interpreted gateway sources and update native digest pins.

No compiler, package download, firewall change, or credential printing.
"""
import argparse,datetime,hashlib,json,os,re,shutil,subprocess,sys,time,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.gateway_store import database


def deploy(root,corix):
 root=Path(root).resolve();corix=Path(corix).resolve();repo=Path(__file__).resolve().parents[1]
 subprocess.run(['bash','-n',str(corix)],check=True)
 config=json.loads((root/'config/gateway.json').read_text())
 units=config.get('service_units')
 roles={'p2p','consensus','relayer','gateway','mcp','telegram'}
 if not isinstance(units,dict) or set(units)!=roles or len(set(units.values()))!=len(roles) or any(not isinstance(v,str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',v) for v in units.values()):raise ValueError('explicit distinct service_units required for all native roles')
 # Validate before copying sources or changing digest pins. Malformed hold
 # evidence must fail deployment, rather than implicitly resume consensus.
 from ziokt.assurance import public_hold
 hold_path=root/'config/consensus-safety-hold.json'
 hold=public_hold({'consensus_safety_hold':str(hold_path)}) if hold_path.exists() else None
 held=bool(hold and hold['active'])
 guard_source=corix.with_name('consensus_hold.py')
 guard_override=Path('/etc/systemd/system')/(units['consensus']+'.service.d')/'80-provenance-hold.conf'
 if guard_override.exists() and not guard_override.read_text().startswith('# Managed Ziokt provenance hold\n'):
  raise ValueError('Existing consensus hold override needs explicit reconciliation')
 if Path(config['corix']).resolve() != (root/'bin/corix_v108.sh').resolve():
  raise ValueError('gateway source path differs from the deployment target')
 services=[units[role] for role in ('p2p','consensus','relayer','gateway')]
 if (root/'mcp/mcp.json').is_file():services.append(units['mcp'])
 if subprocess.run(['systemctl','is-active','--quiet',units['telegram']],capture_output=True).returncode==0:services.append(units['telegram'])
 control=['systemctl'] if os.geteuid()==0 else ['sudo','-n','systemctl']
 if os.geteuid()!=0:
  # Fail before changing source/configuration when this account cannot restart
  # the exact units. Never leave digest pins half-updated after sudo rejection.
  subprocess.run(['sudo','-n','-l','--','systemctl','restart',*services],check=True,capture_output=True)
 timestamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 backup=root/'private-bootstrap-backup'/('gateway-'+timestamp);backup.mkdir(mode=0o700,parents=True)
 for rel in ['config/federation.json','config/runtime-digests.json','config/Caddyfile','config/gateway.json','bin/corix_v108.sh']:
  source=root/rel
  if source.exists():
   shutil.copy2(source,backup/source.name);(backup/source.name).chmod(0o600)
 if guard_override.exists():shutil.copy2(guard_override,backup/'consensus-hold.override')
 chain=Path(config['state_root'])/'var/lib/corix/networks'/config['network']/'blockchain/chain.db'
 for name,path in [('forum',config['forum_db']),('dht',config['dht_db']),('chain',chain)]:
  if not Path(path).is_file():raise ValueError('existing native database required for backup')
  with database(path) as source, database(backup/(name+'.db')) as destination:source.backup(destination)
 target=root/'bin/corix_v108.sh';temporary=target.with_suffix('.new');shutil.copyfile(corix,temporary);temporary.chmod(0o755);temporary.replace(target)
 # A service restart or reboot must also respect the hold, independently of
 # the deployment process that originally paused consensus.
 if guard_source.is_file():
  guard_target=root/'bin/consensus_hold.py';temporary=guard_target.with_suffix('.new');shutil.copyfile(guard_source,temporary);temporary.chmod(0o755);temporary.replace(guard_target)
  def unit_arg(path):return '"'+str(path).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
  override=backup/'consensus-hold.new'
  override.write_text('# Managed Ziokt provenance hold\n[Service]\nExecCondition=/usr/bin/python3 '+unit_arg(guard_target)+' '+unit_arg(hold_path)+'\n')
  install=[] if os.geteuid()==0 else ['sudo','-n']
  subprocess.run([*install,'install','-d',str(guard_override.parent)],check=True)
  subprocess.run([*install,'install','-m','0644',str(override),str(guard_override)],check=True)
  subprocess.run([*control,'daemon-reload'],check=True)
 digest=hashlib.sha256(target.read_bytes()).hexdigest()
 federation=root/'config/federation.json';value=json.loads(federation.read_text())
 for provider in value['providers']:
  if provider['native_project']=='corium':provider['entrypoint_digest']='sha256:'+digest
 temporary=federation.with_suffix('.new');temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.chmod(0o600);temporary.replace(federation)
 config['corix_digest']='sha256:'+digest
 gateway=root/'config/gateway.json';temporary=gateway.with_suffix('.new');temporary.write_text(json.dumps(config,indent=2)+'\n');temporary.chmod(0o600);temporary.replace(gateway)
 digests=root/'config/runtime-digests.json';value=json.loads(digests.read_text())
 for name in value['digests']:
  if name.endswith('corix_v108.sh'):value['digests'][name]=digest
 value['updated']=timestamp;temporary=digests.with_suffix('.new');temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.chmod(0o600);temporary.replace(digests)
 # Updating interpreted sources must preserve existing NNS publication, DNS
 # settings, identities and unit definitions. Initial bootstrap is separate.
 # In particular, never manufacture optimistic NNS rows during an upgrade.
 # A release must not restart mining after a history/provenance safety hold.
 restart_services=[name for name in services if not (held and name==units['consensus'])]
 if held:
  subprocess.run([*control,'stop',units['consensus']],check=True)
  subprocess.run([*control,'reset-failed',units['consensus']],check=True)
 subprocess.run([*control,'restart',*restart_services],check=True)
 deadline=time.monotonic()+30
 while True:
  try:
   with urllib.request.urlopen('http://127.0.0.1:'+str(config.get('port',8185))+'/api/gateway/status',timeout=3) as response:status=json.load(response)
   break
  except OSError:
   if time.monotonic()>deadline:raise
   time.sleep(.5)
 receipt={'schema':'ziokt.gateway-deployment.v1','at':timestamp,'corix_sha256':digest,'backup':str(backup),'status':status,'local_native_compilation':False,'consensus_safety_hold':held}
 path=root/'config/gateway-deployment-receipt.json';path.write_text(json.dumps(receipt,indent=2)+'\n');path.chmod(0o600)
 return receipt

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--corix',type=Path,required=True);a=p.parse_args();print(json.dumps(deploy(a.root,a.corix)))

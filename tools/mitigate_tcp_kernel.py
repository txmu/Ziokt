#!/usr/bin/env python3
"""Apply reversible Linux TCP mitigation while installing a patched kernel.

This is a mitigation for CVE-2026-98432, not a kernel patch or vulnerability test.
"""
import argparse,json,os,shutil,subprocess,time
from pathlib import Path

TABLE='ziokt_tcp_options_guard'
UNIT='ziokt-tcp-kernel-guard.service'
RULES='''delete table inet ziokt_tcp_options_guard
add table inet ziokt_tcp_options_guard
add chain inet ziokt_tcp_options_guard prerouting { type filter hook prerouting priority -310; policy accept; }
add rule inet ziokt_tcp_options_guard prerouting ip protocol tcp ip hdrlength > 5 counter drop comment "Ziokt CVE-2026-98432 interim mitigation"
'''

def run(*args,check=True):return subprocess.run(args,check=check,capture_output=True,text=True)
def status():
 nft=shutil.which('nft');result=run(nft,'list','table','inet',TABLE,check=False)if nft else None
 filtered=bool(result and result.returncode==0 and 'hdrlength > 5'in result.stdout and 'drop'in result.stdout and 'CVE-2026-98432 interim mitigation'in result.stdout)
 return {'kernel':os.uname().release,'mptcp_enabled':Path('/proc/sys/net/mptcp/enabled').read_text().strip(),'tcp_options_filter_active':filtered,'kernel_patch_verified':False}

def apply(area):
 if os.geteuid()!=0:raise SystemExit('Run this deployment operation as root')
 nft=shutil.which('nft');assert nft and shutil.which('systemctl')and shutil.which('sysctl')
 area.mkdir(parents=True,exist_ok=True,mode=0o700);backup=area/'before.json'
 config=Path('/etc/ziokt/cve-2026-98432.nft');unit=Path('/etc/systemd/system')/UNIT;sysctl=Path('/etc/sysctl.d/90-ziokt-cve-2026-98432.conf')
 if backup.exists():
  assert status()['tcp_options_filter_active'],'existing mitigation needs inspection before reinstall'
  print(json.dumps(status()));return
 existing=run(nft,'list','table','inet',TABLE,check=False);assert existing.returncode!=0,'refuse to overwrite an existing firewall table'
 assert not any(p.exists()for p in [config,unit,sysctl]),'refuse to overwrite existing deployment files'
 previous=status();backup.write_text(json.dumps(previous,indent=2)+'\n');backup.chmod(0o600)
 config.parent.mkdir(parents=True,exist_ok=True,mode=0o755);config.write_text(RULES);config.chmod(0o600)
 unit.write_text('[Unit]\nDescription=Ziokt temporary TCP kernel vulnerability mitigation\nDefaultDependencies=no\nAfter=local-fs.target\nBefore=network-pre.target\nWants=network-pre.target\n[Service]\nType=oneshot\nRemainAfterExit=yes\nExecStartPre='+nft+' add table inet '+TABLE+'\nExecStart='+nft+' -f '+str(config)+'\nExecStop='+nft+' delete table inet '+TABLE+'\n[Install]\nWantedBy=multi-user.target\n')
 sysctl.write_text('# CVE-2026-98432 mitigation; patched kernel remains required.\nnet.mptcp.enabled = 0\n')
 try:
  run(nft,'add','table','inet',TABLE)
  run(nft,'--check','-f',str(config))
  run('systemctl','daemon-reload');run('systemctl','enable','--now',UNIT)
  run('sysctl','-w','net.mptcp.enabled=0')
 except BaseException:
  run('systemctl','disable','--now',UNIT,check=False);run(nft,'delete','table','inet',TABLE,check=False)
  for path in [config,unit,sysctl]:path.unlink(missing_ok=True)
  run('systemctl','daemon-reload');run('sysctl','-w','net.mptcp.enabled='+previous['mptcp_enabled']);backup.unlink(missing_ok=True)
  raise
 result=status();result.update({'applied_at':int(time.time()),'rollback':'python3 '+str(Path(__file__).resolve())+' rollback --state '+str(area),'existing_firewall_tables_changed':False});(area/'applied.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

def rollback(area):
 previous=json.loads((area/'before.json').read_text());nft=shutil.which('nft')
 run('systemctl','disable','--now',UNIT,check=False);run(nft,'delete','table','inet',TABLE,check=False)
 for path in ['/etc/ziokt/cve-2026-98432.nft','/etc/systemd/system/'+UNIT,'/etc/sysctl.d/90-ziokt-cve-2026-98432.conf']:Path(path).unlink(missing_ok=True)
 run('systemctl','daemon-reload');run('sysctl','-w','net.mptcp.enabled='+previous['mptcp_enabled']);print(json.dumps(status()))

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['status','apply','rollback']);parser.add_argument('--state',type=Path,default=Path('/var/lib/ziokt/tcp-kernel-mitigation'));args=parser.parse_args()
 if args.action=='status':print(json.dumps(status()))
 elif args.action=='apply':apply(args.state)
 else:rollback(args.state)

if __name__=='__main__':main()

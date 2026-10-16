"""Create an owner-private standalone or Ziokt-backed WATChat/SIM gateway.

No listener, package installation, DNS changes or existing-data overwrite.
"""
import argparse,json,secrets,sys
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.community import RIGHTS,create_policy
from ziokt.security import sign
from ziokt.protocol import encoded

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--origin',required=True);p.add_argument('--port',type=int,required=True);p.add_argument('--application',choices=['watchat','sim-manager'],required=True);p.add_argument('--standalone',action='store_true');p.add_argument('--python',default=sys.executable);p.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[1]);a=p.parse_args()
 u=urlsplit(a.origin)
 if u.scheme!='https' or not u.netloc or u.username or u.password or u.path or u.query or u.fragment or not 1024<=a.port<=65535:p.error('exact HTTPS origin and unprivileged port required')
 root=a.root
 if not root.is_absolute() or root.resolve()!=root or root.exists():p.error('new absolute private directory required; existing state is never overwritten')
 root.mkdir(mode=0o700,parents=True)
 def write(name,data):
  path=root/name
  with path.open('xb') as f:f.write(data)
  path.chmod(0o600)
 private=secrets.token_bytes(32);public=sign({},private,'test')['public_key']
 env={'PORT':str(a.port),'DATA_DIR':str(root/'data'),'WATCHAT_ORIGIN':a.origin,'ADMIN_PASSWORD':secrets.token_urlsafe(24),'ZIOKT_PYTHON':a.python,'ZIOKT_PROJECT_ROOT':str(a.project_root)}
 if a.standalone:env['ZIOKT_STANDALONE']='1'
 else:
  policy=create_policy(private,'web-'+secrets.token_hex(8),{public:sorted(RIGHTS)},privacy='private')
  (root/'vault').mkdir(mode=0o700)
  write('policy.json',encoded(policy))
  for name in ['signing','community','application']:write(name+'.key',private if name=='signing' else secrets.token_bytes(32))
  config={'schema':'ziokt.companion-bridge.v1','application':a.application,'community_root':str(root/'community'),'owner':public,'policy':str(root/'policy.json'),'signing_key':str(root/'signing.key'),'encryption_key':str(root/'community.key'),'application_key':str(root/'application.key'),'vault_root':str(root/'vault')}
  if a.application=='watchat':
   (root/'data').mkdir(mode=0o700);(root/'data/inbox').mkdir(mode=0o700);config['inbox']=str(root/'data/inbox')
  write('bridge.json',encoded(config));env['ZIOKT_BRIDGE_CONFIG' if a.application=='watchat' else 'SIM_BRIDGE_CONFIG']=str(root/'bridge.json')
 # JSON quoting is also valid systemd EnvironmentFile quoting; reject linebreaks.
 if any('\n' in v or '\r' in v or '\x00' in v for v in env.values()):p.error('single-line environment values required')
 write('service.env',('\n'.join(k+'='+json.dumps(v,ensure_ascii=False) for k,v in env.items())+'\n').encode())
 print(json.dumps({'private_config':str(root),'application':a.application,'mode':'standalone' if a.standalone else 'federated','origin':a.origin,'credentials_file':str(root/'service.env')},ensure_ascii=False))
if __name__=='__main__':main()

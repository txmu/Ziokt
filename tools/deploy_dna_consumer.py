#!/usr/bin/env python3
"""Install a loopback-only, status-only DNA consumer for existing native providers.

Run as the service account. Prints a reviewable unit; does not enable it itself.
Producer signing keys stay on their originating host, never in the source package.
"""
import argparse,hashlib,json,os,shutil,sqlite3,sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ziokt.protocol import encoded,secure_read,strict_json
from ziokt.config import fingerprint,load
from ziokt.dna_consumer import primary_domain

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--federation',required=True);p.add_argument('--chain-database',required=True);p.add_argument('--port',type=int);p.add_argument('--chain-role',choices=['primary','dna'],default='dna');p.add_argument('--network-id');p.add_argument('--provider-id');p.add_argument('--refresh-chain-domain',action='store_true');args=p.parse_args()
 args.port=args.port or (8189 if args.chain_role=='dna' else 8190)
 root=Path(args.root).absolute();root.mkdir(mode=0o700,parents=True,exist_ok=True);root.chmod(0o700)
 source=root/'runtime'
 if source.is_symlink():raise ValueError('runtime symlink denied')
 stamp=str(__import__('time').time_ns());stage=root/('.runtime-'+stamp);stage.mkdir(mode=0o700)
 try:
  shutil.copytree(ROOT/'ziokt',stage/'ziokt',copy_function=shutil.copyfile,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  for item in stage.rglob('*'):item.chmod(0o700 if item.is_dir() else 0o600)
  previous=root/('runtime.previous-'+stamp)
  if source.exists():source.rename(previous)
  try:stage.rename(source)
  except BaseException:
   if previous.exists():previous.rename(source)
   raise
 finally:
  if stage.exists():shutil.rmtree(stage)
 federation=load(args.federation)
 for provider in federation['providers']:
  path=Path(provider['root'])/('corix_v108.sh' if provider['native_project']=='corium' else 'CLI/shadow6.py')
  provider['entrypoint_digest']=fingerprint(path)
 fpath=root/'federation.json';fpath.write_bytes(encoded(federation));fpath.chmod(0o600)
 keypath=root/'producer.pem'
 if not keypath.exists():
  key=ec.generate_private_key(ec.SECP256K1());fd=os.open(keypath,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'wb') as out:out.write(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
 key=serialization.load_pem_private_key(secure_read(keypath,4096),None);pem=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n');sender=hashlib.sha256(pem.encode()).hexdigest()
 database=Path(args.chain_database).absolute()
 with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
  genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0];height=db.execute('SELECT MAX(height) FROM blocks').fetchone()[0]
  row=db.execute('SELECT w.proof FROM block_work w JOIN blocks b ON b.hash=w.hash ORDER BY b.height DESC LIMIT 1').fetchone()
  proof=json.loads(row[0]) if row else {}
  legacy=not proof
  if args.chain_role=='dna' and not legacy:
   if proof.get('schema')!='corium.dna-work.v1':raise ValueError('native DNA chain proof required')
   chain=proof['recovery']
  else:
   if not legacy and proof.get('schema')!='corium.native-block-work.v2':raise ValueError('native primary chain proof required')
   chain=primary_domain(args.network_id,genesis)
  policy=proof['policy'] if not legacy else hashlib.sha256(b'Corium/native-pos/v108').hexdigest()
 if args.provider_id and not any(v['provider_id']==args.provider_id and v['native_project']=='corium' for v in federation['providers']):raise ValueError('selected Corium provider required')
 targets={v['native_project']:{'federation':str(fpath),'provider':v['provider_id'],'actions':['status.get']} for v in federation['providers'] if not args.provider_id or v['native_project']!='corium' or v['provider_id']==args.provider_id}
 configpath=root/'consumer.json'
 if not configpath.exists():
  config={'schema':'ziokt.dna-consumer.v1','enabled':True,'state':str(root/'state'),'listen':'127.0.0.1','port':args.port,'chain':chain,'policy':policy,'senders':{sender:{'public_key':pem,'components':list(targets)}},'targets':targets,'chain_source':{'database':str(database),'genesis':genesis,'confirmations':1,'start_height':height+1}}
  if args.chain_role=='primary' or legacy:config['chain_source'].update(role='primary',network_id=args.network_id)
  if legacy:config['chain_source']['protocol']='native-pos-v108'
  configpath.write_bytes(encoded(config));configpath.chmod(0o600)
 user=__import__('pwd').getpwuid(os.getuid()).pw_name
 unitname='ziokt-'+args.chain_role+'-consumer' if args.chain_role=='primary' else 'ziokt-dna-consumer'
 unit=f'''[Unit]
Description=Ziokt authenticated DNA native consumer
After=network-online.target
[Service]
User={user}
WorkingDirectory={source}
ExecStart={sys.executable} -m ziokt.dna_consumer --config {configpath}
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
MemoryMax=256M
[Install]
WantedBy=multi-user.target
'''
 (root/(unitname+'.service')).write_text(unit)
 config=strict_json(secure_read(configpath,65536))
 if args.refresh_chain_domain and (config['chain']!=chain or config['policy']!=policy):
  if any(t['actions']!=['status.get'] for t in config['targets'].values()):raise ValueError('review outstanding writes before domain migration')
  backup=root/('consumer-before-domain-'+str(__import__('time').time_ns())+'.json');backup.write_bytes(encoded(config));backup.chmod(0o600)
  config.update(chain=chain,policy=policy);configpath.write_bytes(encoded(config));configpath.chmod(0o600)
 print(json.dumps({'root':str(root),'components':list(targets),'actions':['status.get'],'chain_start_height':config['chain_source']['start_height'],'unit':str(root/(unitname+'.service')),'enabled_in_systemd':False}))
if __name__=='__main__':main()

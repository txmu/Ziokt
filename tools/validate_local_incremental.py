#!/usr/bin/env python3
"""Exercise a local owner's checkpoint plus real native incremental blocks.

This isolated experiment does not prove trustless admission of a new node and
does not start a validator or replace any production database.
"""
import argparse,hashlib,json,os,resource,shutil,sqlite3,subprocess,sys,time
from contextlib import closing
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from ziokt.checkpoint_capture import capture_pair,native
from ziokt.checkpoint_format import canonical
from ziokt.checkpoint_restore import materialize_local
from ziokt.checkpoint_store import CheckpointStore

def tip(path,height=None):
 with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10))as db:
  if height is None:return db.execute('SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
  row=db.execute('SELECT hash FROM blocks WHERE height=?',(height,)).fetchone();return row[0]if row else None

def main():
 os.umask(0o077)
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--node-root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--timeout',type=int,default=900);args=parser.parse_args()
 root=args.node_root.resolve();out=args.output.absolute();out.mkdir(parents=True,mode=0o700,exist_ok=False)
 config=json.loads((root/'acceptance/checkpoints/capture-config.json').read_text());source=Path(config['native_source']);config['native_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
 began=time.monotonic();usage_before=resource.getrusage(resource.RUSAGE_CHILDREN)
 captured=capture_pair(config,out/'store');policy=json.loads((Path(captured['store'])/'local-policy.json').read_text())
 store=CheckpointStore(captured['store'],policy['expected'],{role:set(ids)for role,ids in policy['local_owners'].items()});checkpoint=store.current();restored=out/'restored';materialize_local(store,restored)
 identities={};live_paths={}
 for role,spec in config['chains'].items():
  live=Path(spec['root']);network=spec['network_id'];etc=live/'etc/corix/networks'/network;chain=checkpoint.manifest['chains'][role]
  owner=hashlib.sha256((etc/'identity.key.pub').read_text().rstrip('\n').encode()).hexdigest();assert owner in policy['local_owners'][role]
  sandbox=out/'nodes'/role;sandbox_etc=sandbox/'etc/corix/networks'/network;sandbox_etc.mkdir(parents=True,mode=0o700)
  for name in ['corix.conf','genesis.json','recovery.json','recovery-state.json']:
   source_file=etc/name
   if source_file.is_file():shutil.copyfile(source_file,sandbox_etc/name)
  key=ec.generate_private_key(ec.SECP256K1());private=sandbox_etc/'identity.key';private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));private.chmod(0o600)
  public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n');(sandbox_etc/'identity.key.pub').write_text(public+'\n');identities[role]=hashlib.sha256(public.encode()).hexdigest();assert identities[role]!=owner
  target=sandbox/'var/lib/corix/networks'/network
  for subdir,name in [('blockchain','chain.db'),('forum','forum.db')]:
   directory=target/subdir;directory.mkdir(parents=True,mode=0o700);os.rename(restored/role/name,directory/name)
  cache=sandbox/'var/lib/corix/p2p/peer_certs';cache.mkdir(parents=True,mode=0o700)
  port=441 if role=='primary'else 78
  shutil.copyfile(etc/'tls.crt',cache/('127.0.0.1_'+str(port)+'.pem'))
  live_paths[role]=live/'var/lib/corix/networks'/network/'blockchain/chain.db'
 print(json.dumps({'event':'checkpoint-ready','snapshot_hash':captured['snapshot_hash'],'start':captured['chains'],'fresh_client_identities':identities,'trust':'local owner checkpoint; not independently verified historical execution'}),flush=True)
 results={};deadline=time.monotonic()+args.timeout
 for role,spec in config['chains'].items():
  chain=checkpoint.manifest['chains'][role];path=live_paths[role]
  while time.monotonic()<deadline:
   if tip(path,chain['height'])!=chain['block_hash']:raise RuntimeError(role+' local checkpoint was reorganized before validation')
   head=tip(path)
   if head[0]>chain['height']:break
   time.sleep(5)
  else:raise TimeoutError(role+' native chain did not produce a subsequent block')
  if head[0]-chain['height']>32:raise RuntimeError('incremental experiment block budget exceeded')
  sandbox=out/'nodes'/role;port=441 if role=='primary'else 78;owner=next(iter(policy['local_owners'][role]));log=out/(role+'-native-incremental.log')
  script='''set -e
export CORIUM_ROOT="$2" CORIUM_NETWORK_ID_OVERRIDE="$3"
source "$1"
load_config
P2P_MESSAGE_TIMEOUT=5
mkdir -p "$P2P_DIR" "$BUILD_TMP_DIR_BASE" "$INSTALLED_DB"
_init_dht_db
dht_add_node "$4" ipv4 127.0.0.1 "$5"
_blockchain_reorganize_to "$6" 127.0.0.1 "$5"
'''
  tick=time.monotonic()
  with log.open('w')as stream:subprocess.run(['bash','-c',script,'local-incremental',str(source),str(sandbox),spec['network_id'],owner,str(port),head[1]],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=300)
  text=log.read_text();assert 'Common ancestor found): '+chain['block_hash'][:16] in text
  assert 'Verifying block signature' in text and 'All validations passed' in text
  assert '正在回滚本地无效的区块'not in text and 'Rebuilding derived'not in text
  stage_chain=sandbox/'var/lib/corix/networks'/spec['network_id']/'blockchain/chain.db';assert tip(stage_chain)==head
  # Compare only when the live chain is at the identical head.
  assert tip(path)==head,'live chain advanced before the identical-head comparison'
  live_state=canonical(native(source,spec['root'],spec['network_id'],'_internal_semantic_state'))
  stage_state=canonical(native(source,sandbox,spec['network_id'],'_internal_semantic_state'))
  assert live_state==stage_state,'native semantic state mismatch'
  results[role]={'start_height':chain['height'],'end_height':head[0],'end_hash':head[1],'native_signatures_and_consensus':'validated by original native incremental verifier','native_semantic_state_equal':True,'full_history_replays':0,'incremental_seconds':time.monotonic()-tick}
  print(json.dumps({'event':'role-complete','role':role,**results[role]}),flush=True)
 usage=resource.getrusage(resource.RUSAGE_CHILDREN);report={'schema':'ziokt.local-checkpoint-incremental-experiment.v1','snapshot_hash':captured['snapshot_hash'],'roles':results,'fresh_client_identities':identities,'wall_seconds':time.monotonic()-began,'child_cpu_user_seconds':usage.ru_utime-usage_before.ru_utime,'child_cpu_system_seconds':usage.ru_stime-usage_before.ru_stime,'max_child_rss_kib':usage.ru_maxrss,'disk_bytes':sum(p.stat().st_size for p in out.rglob('*')if p.is_file()),'local_owner_checkpoint_trust':True,'ordinary_new_node_trustless_admission_verified':False,'production_databases_switched':False}
 (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)

if __name__=='__main__':main()

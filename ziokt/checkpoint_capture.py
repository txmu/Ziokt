"""Capture owner-local dual-chain checkpoints from existing native validated state."""
import contextlib,hashlib,json,sqlite3,subprocess,time
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from .checkpoint_format import canonical,chunk_bytes,digest,require,seal,hexid
from .checkpoint_consumer import capture as capture_consumer
from .checkpoint_store import CheckpointStore,export_bundle,write_new

def native(source,root,network,operation):
 # All caller data is passed as argv; the command text is fixed.
 script='export CORIUM_ROOT="$2" CORIUM_NETWORK_ID_OVERRIDE="$3"; source "$1"; load_config || exit; '+operation
 result=subprocess.run(['bash','-c',script,'checkpoint-capture',str(source),str(root),network],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
 return json.loads(result.stdout)

def capture_pair(config,store_root,*,bundle=None):
 require(config['schema']=='ziokt.local-checkpoint-capture.v1'and set(config['chains'])=={'primary','dna'},'both local native chains required')
 source=Path(config['native_source']);require(source.is_absolute()and source.is_file()and not source.is_symlink(),'pinned native source required')
 sha=hashlib.sha256(source.read_bytes()).hexdigest();require(sha==hexid(config['native_sha256']),'native source digest differs')
 paths=[];specs={}
 for role,spec in config['chains'].items():
  root=Path(spec['root']);network=spec['network_id'];require(root.is_absolute()and not root.is_symlink(),'local native root required')
  require(type(network)is str and 1<=len(network)<=64 and all(c.isalnum()or c in '_-' for c in network),'bounded native network required')
  base=root/'var/lib/corix/networks'/network;chain=base/'blockchain/chain.db';application=base/'forum/forum.db'
  consumers=spec.get('consumers',[]);require(len(consumers)<=2,'at most two local consumer journals per chain')
  paths.extend([chain,application]+[Path(c['database'])for c in consumers]);specs[role]=(root,network,chain,consumers)
 require(len(set(map(str,paths)))==len(paths),'independent native databases required')
 for path in paths:require(path.is_absolute()and path.is_file()and not path.is_symlink(),'existing local database required')
 chains={};keys={};objects={}
 # One attached SQLite transaction reserves all chain/application/consumer
 # databases against writers. Native readers see the same committed state.
 # No native database is copied or imported by this operation.
 with contextlib.closing(sqlite3.connect(':memory:',timeout=10))as barrier:
  for i,path in enumerate(sorted(paths)):barrier.execute('ATTACH DATABASE ? AS db'+str(i),(str(path),))
  barrier.execute('BEGIN IMMEDIATE')
  try:
   for role,(root,network,chain_path,consumers)in specs.items():
    with contextlib.closing(sqlite3.connect(chain_path.as_uri()+'?mode=ro',uri=True))as db:
     height,block_hash=db.execute('SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1').fetchone();genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
     proof=db.execute('SELECT proof FROM block_work WHERE hash=?',(block_hash,)).fetchone();version=json.loads(proof[0])['schema']if proof else 'native-pos-v108'
    state=native(source,root,network,'_internal_semantic_state')
    schemas={}
    for label,path in [('chain',chain_path),('application',chain_path.parent.parent/'forum/forum.db')]:
     with contextlib.closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True))as schema_db:
      schemas[label]={kind:{name:sql for name,sql in schema_db.execute('SELECT name,sql FROM sqlite_master WHERE type=? AND sql IS NOT NULL AND name NOT LIKE ? ORDER BY name',(sql_type,'sqlite_%'))}for kind,sql_type in [('tables','table'),('indexes','index')]}
    schema_descriptor,parts=chunk_bytes(canonical(schemas));objects.update(parts)
    prefix='h=$(db_query_static "$BLOCKCHAIN_DB" "SELECT COALESCE(MAX(height),0) FROM blocks;"); '
    meta=native(source,root,network,prefix+'_corium_work_consensus cooperative-state "$BLOCKCHAIN_DB" "$CORIUM_NETWORK_ID" "$((h+1))"')
    mode=native(source,root,network,prefix+'_corium_work_consensus mode "$BLOCKCHAIN_DB" "$CORIUM_NETWORK_ID" "$((h+1))"')
    descriptor,parts=chunk_bytes(canonical(state));objects.update(parts)
    identity_path=root/'etc/corix/networks'/network/'identity.key';require(identity_path.is_file()and not identity_path.is_symlink(),'existing independent native identity required')
    key=serialization.load_pem_private_key(identity_path.read_bytes(),password=None);keys[role]=key
    public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n');owner=digest(public.encode())
    journals=[]
    for consumer in consumers:
     journal,parts=capture_consumer(consumer['database'],consumer['id'],owner,meta['state']['chain']);journals.append(journal);objects.update(parts)
    chains[role]={'network_id':network,'genesis_hash':genesis,'chain_id':meta['state']['chain'],'height':height,'block_hash':block_hash,'consensus_rules':{'version':version,'policy_hash':mode['policy']},'verifier_sha256':sha,'state_root':descriptor['sha256'],'state':descriptor,'database_schema':schema_descriptor,'consumer_state':journals}
  finally:barrier.rollback()
 manifest=seal(chains,keys,int(time.time()));expected={role:{k:c[k]for k in ['network_id','genesis_hash','chain_id','verifier_sha256','consensus_rules']}for role,c in chains.items()};signers={role:{manifest['signatures'][role]['identity']}for role in chains}
 # Different verifier/policy contexts retain independent local generations.
 context={'expected':expected,'local_owners':{role:sorted(ids)for role,ids in signers.items()}}
 directory=Path(store_root)/digest(canonical(context));store=CheckpointStore(directory,expected,signers)
 policy=directory/'local-policy.json'
 if not policy.exists():write_new(policy,canonical(context))
 else:require(policy.read_bytes()==canonical(context),'local checkpoint policy changed')
 result=store.publish(manifest,objects)
 if bundle is not None:export_bundle(bundle,manifest,objects)
 return {'schema':'ziokt.local-checkpoint-capture-result.v1','snapshot_hash':manifest['snapshot_hash'],'store':str(directory),'verification_level':result.verification_level,'chains':{role:{k:c[k]for k in ['network_id','height','block_hash','state_root']}for role,c in chains.items()},'consumer_journals':sum(len(c['consumer_state'])for c in chains.values()),'native_databases_modified':False}

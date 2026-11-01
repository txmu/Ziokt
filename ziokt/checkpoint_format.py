"""Versioned snapshot commitments. Signatures authenticate sources, not historical validity."""
import hashlib,json,re
from dataclasses import dataclass
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature

SCHEMA='ziokt.dual-state-checkpoint.v1'
DOMAIN=b'Ziokt/state-checkpoint/v1\0'
CHUNK=262144
MAX_BYTES=64*1024*1024
HEX=re.compile(r'^[a-f0-9]{64}$')
class CheckpointError(ValueError):pass

def require(condition,message):
 if not condition:raise CheckpointError(message)
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def digest(data):return hashlib.sha256(data).hexdigest()
def integer(value,minimum=0,maximum=(1<<53)-1):require(type(value)is int and minimum<=value<=maximum,'bounded integer required');return value
def hexid(value):require(type(value)is str and HEX.fullmatch(value),'32-byte commitment required');return value

def merkle(leaves):
 """Domain-separated count-bound tree; no duplicate-last-leaf ambiguity."""
 values=[hashlib.sha256(b'\0'+bytes.fromhex(hexid(v))).digest()for v in leaves]
 count=len(values)
 if not values:values=[hashlib.sha256(b'empty').digest()]
 while len(values)>1:
  values=[hashlib.sha256(b'\1'+values[i]+(values[i+1]if i+1<len(values)else hashlib.sha256(b'missing').digest())).digest()for i in range(0,len(values),2)]
 return digest(b'\2'+count.to_bytes(8,'big')+values[0])

def chunk_bytes(data):
 require(type(data)is bytes and len(data)<=MAX_BYTES,'snapshot byte budget exceeded')
 objects={};parts=[]
 for offset in range(0,len(data),CHUNK):
  part=data[offset:offset+CHUNK];identity=digest(part);objects[identity]=part;parts.append({'sha256':identity,'bytes':len(part)})
 return {'bytes':len(data),'sha256':digest(data),'chunks':parts,'chunk_root':merkle([p['sha256']for p in parts])},objects

def assemble(descriptor,read):
 require(type(descriptor)is dict and set(descriptor)=={'bytes','sha256','chunks','chunk_root'},'exact object descriptor required')
 size=integer(descriptor['bytes'],0,MAX_BYTES);hexid(descriptor['sha256']);hexid(descriptor['chunk_root']);parts=descriptor['chunks']
 require(type(parts)is list and len(parts)==(size+CHUNK-1)//CHUNK,'exact chunk count required')
 output=bytearray();leaves=[]
 for index,part in enumerate(parts):
  require(type(part)is dict and set(part)=={'sha256','bytes'},'exact chunk descriptor required');identity=hexid(part['sha256']);length=integer(part['bytes'],1,CHUNK)
  require(length==min(CHUNK,size-index*CHUNK),'canonical chunk layout required');data=read(identity)
  require(type(data)is bytes and len(data)==length and digest(data)==identity,'chunk missing or corrupt');output.extend(data);leaves.append(identity)
 require(len(output)==size and digest(output)==descriptor['sha256'] and merkle(leaves)==descriptor['chunk_root'],'snapshot content commitment differs');return bytes(output)

def chain_commitment(chain):
 require(type(chain)is dict and set(chain)=={'network_id','genesis_hash','chain_id','height','block_hash','consensus_rules','verifier_sha256','state_root','state','database_schema','consumer_state'},'exact chain checkpoint fields required')
 require(type(chain['network_id'])is str and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',chain['network_id']),'network domain required')
 for name in ['genesis_hash','chain_id','block_hash','verifier_sha256','state_root']:hexid(chain[name])
 integer(chain['height']);require(type(chain['consensus_rules'])is dict and set(chain['consensus_rules'])=={'version','policy_hash'},'versioned consensus policy required');require(type(chain['consensus_rules']['version'])is str and 1<=len(chain['consensus_rules']['version'])<=128,'bounded consensus version required');hexid(chain['consensus_rules']['policy_hash'])
 require(chain['state_root']==chain['state']['sha256'],'state commitment differs')
 consumers=chain['consumer_state'];require(type(consumers)is list and len(consumers)<=32,'consumer snapshot budget')
 for consumer in consumers:
  require(type(consumer)is dict and set(consumer)=={'id','owner_identity','cursor','canonical_hash','receipts_root','state'},'identity-bound consumer state required')
  require(type(consumer['id'])is str and re.fullmatch('[A-Za-z0-9_-]{1,64}',consumer['id']),'consumer identity required');hexid(consumer['owner_identity']);integer(consumer['cursor'],0,chain['height']);hexid(consumer['canonical_hash']);hexid(consumer['receipts_root'])
 return digest(DOMAIN+b'chain\0'+canonical(chain))

def native_state(data,chain):
 def unique(pairs):
  result={}
  for key,value in pairs:
   require(key not in result,'duplicate native state field');result[key]=value
  return result
 state=json.loads(data.decode('utf-8'),object_pairs_hook=unique,parse_constant=lambda _:require(False,'nonfinite native state'))
 require(canonical(state)==data,'canonical native state encoding required')
 require(type(state)is dict and set(state)in ({'chain','application'},{'chain','application','_custom_schemas'}),'native semantic state required')
 require(type(state['chain'])is dict and type(state['application'])is dict,'native state sections required')
 blocks=state['chain'].get('blocks');require(type(blocks)is list and len(blocks)==chain['height']+1,'snapshot height and historical index differ')
 ordered=sorted(blocks,key=lambda block:integer(block['height']))
 for height,block in enumerate(ordered):
  require(block['height']==height,'noncontiguous native history index');hexid(block['hash'])
  if height:require(block['previous_hash']==ordered[height-1]['hash'],'native history linkage differs')
 require(ordered[0]['hash']==chain['genesis_hash']and ordered[-1]['hash']==chain['block_hash'],'independent genesis or checkpoint anchor differs')
 # This is structural validation only. Existing native signatures/work/transition
 # rules still require strict replay or a separately implemented validity proof.
 return state

def unsigned(manifest):return {k:v for k,v in manifest.items()if k not in {'snapshot_hash','signatures'}}
def manifest_hash(manifest):return digest(DOMAIN+canonical(unsigned(manifest)))

def seal(chains,keys,created_at,scope='local-checkpoint'):
 require(set(chains)=={'primary','dna'} and set(keys)=={'primary','dna'},'both independent chains required')
 roots={role:chain_commitment(c)for role,c in chains.items()};require(chains['primary']['network_id']!=chains['dna']['network_id']and chains['primary']['chain_id']!=chains['dna']['chain_id'],'chain domains must differ')
 require(scope in {'local-checkpoint','explicit-signer-bootstrap'},'historical validity proof is not implemented by a source signature')
 manifest={'schema':SCHEMA,'created_at':integer(created_at),'scope':scope,'chains':chains,'pair_commitment':digest(DOMAIN+b'pair\0'+canonical(roots)),'verification':'source-authenticated-state; historical-validity-not-implied'}
 manifest['snapshot_hash']=manifest_hash(manifest);manifest['signatures']={}
 for role,key in keys.items():
  require(isinstance(key,ec.EllipticCurvePrivateKey)and isinstance(key.curve,ec.SECP256K1),'native secp256k1 signer required')
  public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n');message=DOMAIN+role.encode()+bytes.fromhex(manifest['snapshot_hash'])
  manifest['signatures'][role]={'public_key':public,'identity':digest(public.encode()),'signature':key.sign(message,ec.ECDSA(hashes.SHA256())).hex()}
 return manifest

@dataclass(frozen=True)
class VerifiedCheckpoint:
 manifest:dict
 states:dict
 verification_level:str


def verify(manifest,expected,signers,read,*,allow_bootstrap=False):
 try:return _verify(manifest,expected,signers,read,allow_bootstrap=allow_bootstrap)
 except CheckpointError:raise
 except (InvalidSignature,ValueError,TypeError,KeyError,IndexError,AttributeError,OverflowError,UnicodeError)as error:
  raise CheckpointError('invalid checkpoint encoding, structure or signature')from error

def _verify(manifest,expected,signers,read,*,allow_bootstrap=False):
 require(type(manifest)is dict and set(manifest)=={'schema','created_at','scope','chains','pair_commitment','verification','snapshot_hash','signatures'},'exact versioned snapshot manifest required')
 require(manifest['schema']==SCHEMA,'incompatible checkpoint version');integer(manifest['created_at']);require(manifest['scope']in {'local-checkpoint','explicit-signer-bootstrap'},'unsupported checkpoint proof class')
 require(manifest['scope']=='local-checkpoint'or allow_bootstrap,'explicit bootstrap trust consent required')
 require(manifest['verification']=='source-authenticated-state; historical-validity-not-implied','source signature cannot claim historical validity');require(manifest_hash(manifest)==hexid(manifest['snapshot_hash']),'snapshot manifest commitment differs')
 require(set(manifest['chains'])==set(expected)==set(signers)==set(manifest['signatures'])=={'primary','dna'},'complete expected dual-chain domains required')
 roots={};states={}
 for role,chain in manifest['chains'].items():
  roots[role]=chain_commitment(chain);policy=expected[role]
  require(type(policy)is dict and set(policy)=={'network_id','genesis_hash','chain_id','verifier_sha256','consensus_rules'},'independent network and verifier expectations required')
  require(all(chain[k]==v for k,v in policy.items()),'network, genesis, chain or verifier policy mismatch')
  proof=manifest['signatures'][role];require(type(proof)is dict and set(proof)=={'public_key','identity','signature'},'exact source proof required');identity=hexid(proof['identity']);require(identity in signers[role],'snapshot signer is not independently trusted')
  public=proof['public_key'];require(type(public)is str and len(public)<=2048 and digest(public.encode())==identity,'source identity differs');key=serialization.load_pem_public_key(public.encode());require(isinstance(key,ec.EllipticCurvePublicKey)and isinstance(key.curve,ec.SECP256K1),'native source key required')
  signature=proof['signature'];require(type(signature)is str and re.fullmatch('[a-f0-9]{16,144}',signature),'bounded native signature required');key.verify(bytes.fromhex(signature),DOMAIN+role.encode()+bytes.fromhex(manifest['snapshot_hash']),ec.ECDSA(hashes.SHA256()))
  states[role]=assemble(chain['state'],read);state=native_state(states[role],chain)
  schema_raw=assemble(chain['database_schema'],read);schemas=json.loads(schema_raw)
  require(canonical(schemas)==schema_raw and type(schemas)is dict and set(schemas)=={'chain','application'},'complete canonical native database schemas required')
  for label,tables in state.items():
   if label=='_custom_schemas':continue
   require(type(schemas[label])is dict and set(schemas[label])=={'tables','indexes'},'native schema sections required')
   require(set(tables)<=set(schemas[label]['tables']),'snapshot table has no committed native schema')
  consumers=chain['consumer_state']
  require(len({c['id']for c in consumers})==len(consumers),'duplicate consumer snapshot')
  require(not consumers or manifest['scope']=='local-checkpoint','private consumer journals cannot enter remote bootstrap')
  blocks={b['height']:b['hash']for b in state['chain']['blocks']}
  for consumer in consumers:
   require(consumer['owner_identity']==identity,'consumer journal belongs to another local identity')
   require(blocks.get(consumer['cursor'])==consumer['canonical_hash'],'consumer cursor is not on the checkpoint branch')
   from .checkpoint_consumer import validate_payload
   # Retain orphaned historical receipts as local audit/idempotency records.
   # They do not establish a canonical cursor or authorize another dispatch.
   validate_payload(assemble(consumer['state'],read),consumer,chain['chain_id'])
 require(manifest['chains']['primary']['network_id']!=manifest['chains']['dna']['network_id']and manifest['chains']['primary']['chain_id']!=manifest['chains']['dna']['chain_id'],'independent domains required')
 require(manifest['pair_commitment']==digest(DOMAIN+b'pair\0'+canonical(roots)),'paired snapshot commitment differs')
 return VerifiedCheckpoint(manifest,states,'local-authenticated-checkpoint'if manifest['scope']=='local-checkpoint'else 'explicitly-trusted-bootstrap')

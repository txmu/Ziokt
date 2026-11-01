import copy,hashlib,unittest
from cryptography.hazmat.primitives.asymmetric import ec
from ziokt.checkpoint_format import *
class CheckpointTests(unittest.TestCase):
 def setUp(self):
  self.keys={role:ec.generate_private_key(ec.SECP256K1())for role in ['primary','dna']};self.objects={};self.chains={}
  for role,letter in [('primary','a'),('dna','b')]:
   genesis=digest((role+'genesis').encode());block=digest((role+'block').encode());state={'chain':{'blocks':[{'height':0,'hash':genesis,'previous_hash':'0'*64},{'height':1,'hash':block,'previous_hash':genesis}],'transactions':[]},'application':{}}
   descriptor,objects=chunk_bytes(canonical(state));self.objects.update(objects)
   schemas={'chain':{'tables':{'blocks':'CREATE TABLE blocks(height INTEGER,hash TEXT,previous_hash TEXT)','transactions':'CREATE TABLE transactions(hash TEXT)'},'indexes':{}},'application':{'tables':{},'indexes':{}}};schema_descriptor,parts=chunk_bytes(canonical(schemas));self.objects.update(parts)
   self.chains[role]={'network_id':role+'-test','genesis_hash':genesis,'chain_id':letter*64,'height':1,'block_hash':block,'consensus_rules':{'version':'native-test-v1','policy_hash':'c'*64},'verifier_sha256':'d'*64,'state_root':descriptor['sha256'],'state':descriptor,'database_schema':schema_descriptor,'consumer_state':[]}
  self.manifest=seal(self.chains,self.keys,1);self.expected={role:{k:c[k]for k in ['network_id','genesis_hash','chain_id','verifier_sha256','consensus_rules']}for role,c in self.chains.items()};self.signers={role:{proof['identity']}for role,proof in self.manifest['signatures'].items()}
 def verify(self,manifest=None,**kwargs):return verify(manifest or self.manifest,self.expected,self.signers,self.objects.__getitem__,**kwargs)
 def test_local_checkpoint_and_scope_cannot_claim_validity(self):
  value=self.verify();self.assertEqual(value.verification_level,'local-authenticated-checkpoint')
  with self.assertRaises(CheckpointError):seal(self.chains,self.keys,1,'native-validity-proof')
 def test_chunks_and_count_bound_tree_detect_tampering_and_ambiguous_padding(self):
  descriptor,objects=chunk_bytes(b'abc'*(CHUNK//2));self.assertEqual(assemble(descriptor,objects.__getitem__),b'abc'*(CHUNK//2))
  objects[descriptor['chunks'][0]['sha256']]=b'bad'
  with self.assertRaises(CheckpointError):assemble(descriptor,objects.__getitem__)
  self.assertNotEqual(merkle(['a'*64]),merkle(['a'*64,'a'*64]))
 def test_manifest_change_and_cross_chain_replacement_fail_before_import(self):
  for edit in ['height','source','chain']:
   value=copy.deepcopy(self.manifest)
   if edit=='height':value['chains']['primary']['height']=2
   elif edit=='source':value['chains']['primary']['verifier_sha256']='f'*64
   else:value['chains']['primary']=value['chains']['dna']
   with self.assertRaises(CheckpointError):self.verify(value)
 def test_signed_wrong_height_and_foreign_policy_are_rejected(self):
  chains=copy.deepcopy(self.chains);chains['primary']['height']=2
  with self.assertRaises(CheckpointError):self.verify(seal(chains,self.keys,1))
  self.expected['dna']['genesis_hash']='e'*64
  with self.assertRaises(CheckpointError):self.verify()
 def test_self_asserted_signer_and_unknown_version_are_not_trusted(self):
  self.signers['primary']={'0'*64}
  with self.assertRaises(CheckpointError):self.verify()
  value=copy.deepcopy(self.manifest);value['schema']='ziokt.dual-state-checkpoint.v99'
  with self.assertRaises(CheckpointError):self.verify(value)
 def test_remote_bootstrap_requires_explicit_trust_and_never_claims_full_validation(self):
  value=seal(self.chains,self.keys,1,'explicit-signer-bootstrap')
  with self.assertRaises(CheckpointError):self.verify(value)
  self.assertEqual(self.verify(value,allow_bootstrap=True).verification_level,'explicitly-trusted-bootstrap')
 def test_malformed_and_invalid_signature_errors_have_one_fail_closed_interface(self):
  for field,replacement in [('chains',None),('signatures',[]),('snapshot_hash',17)]:
   value=copy.deepcopy(self.manifest);value[field]=replacement
   with self.assertRaises(CheckpointError):self.verify(value)
  value=copy.deepcopy(self.manifest);value['signatures']['primary']['signature']='00'*32
  with self.assertRaises(CheckpointError):self.verify(value)

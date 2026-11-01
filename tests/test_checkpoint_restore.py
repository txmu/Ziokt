import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
import test_checkpoint_format as fixtures
from ziokt.checkpoint_format import canonical,chunk_bytes,seal,CheckpointError
from ziokt.checkpoint_store import CheckpointStore
from ziokt.checkpoint_restore import materialize_local

class LocalMaterializationTests(unittest.TestCase):
 def setUp(self):
  fixtures.CheckpointTests.setUp(self);self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.store=CheckpointStore(self.root/'cache',self.expected,self.signers)
 def test_empty_directory_gets_both_native_histories_without_replay(self):
  self.store.publish(self.manifest,self.objects);result=materialize_local(self.store,self.root/'restored')
  self.assertEqual(result['full_history_replays'],0);self.assertFalse(result['production_databases_switched'])
  for role,chain in self.chains.items():
   with sqlite3.connect(self.root/'restored'/role/'chain.db')as db:
    self.assertEqual(db.execute('SELECT height,hash FROM blocks ORDER BY height').fetchall(),[(0,chain['genesis_hash']),(1,chain['block_hash'])])
 def test_schema_failure_never_publishes_partial_pair(self):
  chains=copy.deepcopy(self.chains);schema={'chain':{'tables':{'blocks':'CREATE TABLE blocks(height INTEGER,hash TEXT,previous_hash TEXT)','transactions':'CREATE TABLE different(hash TEXT)'},'indexes':{}},'application':{'tables':{},'indexes':{}}}
  descriptor,parts=chunk_bytes(canonical(schema));self.objects.update(parts);chains['dna']['database_schema']=descriptor
  self.store.publish(seal(chains,self.keys,2),self.objects)
  with self.assertRaises(CheckpointError):materialize_local(self.store,self.root/'failed')
  self.assertFalse((self.root/'failed').exists());self.assertEqual(list(self.root.glob('.restore-*')),[])
 def test_existing_valid_data_cannot_be_overwritten(self):
  self.store.publish(self.manifest,self.objects);target=self.root/'existing';target.mkdir();(target/'keep').write_text('valid data')
  with self.assertRaises(CheckpointError):materialize_local(self.store,target)
  self.assertEqual((target/'keep').read_text(),'valid data')
 def test_bootstrap_checkpoint_materialization_with_consent(self):
  bootstrap_manifest=seal(self.chains,self.keys,1,'explicit-signer-bootstrap')
  self.store.publish(bootstrap_manifest,self.objects,allow_bootstrap=True)
  with self.assertRaises(CheckpointError):materialize_local(self.store,self.root/'restored-disallowed')
  result=materialize_local(self.store,self.root/'restored-allowed',allow_bootstrap=True)
  self.assertEqual(result['verification_level'],'explicitly-trusted-bootstrap')
  for role,chain in self.chains.items():
   with sqlite3.connect(self.root/'restored-allowed'/role/'chain.db')as db:
    self.assertEqual(db.execute('SELECT height,hash FROM blocks ORDER BY height').fetchall(),[(0,chain['genesis_hash']),(1,chain['block_hash'])])

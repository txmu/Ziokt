"""Real RNA signatures, SQLite journals, native receipts and restore rejection."""
import copy,unittest
import test_checkpoint_format as checkpoints
import test_dna_consumer as consumers
from ziokt.checkpoint_format import CheckpointError,canonical,seal,verify
from ziokt.checkpoint_consumer import capture,guard_existing,validate_payload


class ConsumerCheckpointTests(unittest.TestCase):
 def setUp(self):
  checkpoints.CheckpointTests.setUp(self)
  self.fixture=consumers.ConsumerTests('test_signed_queue_restart_native_dispatch_and_duplicate')
  self.addCleanup(self.fixture.doCleanups);self.fixture.setUp()
  self.fixture.consumer.enqueue(self.fixture.frame())
  result=self.fixture.consumer.step();self.assertEqual(result['state'],'completed_read',result)
  self.owner=self.manifest['signatures']['primary']['identity']
  self.block=self.chains['primary']['block_hash']
  with self.fixture.consumer.db()as db:db.execute('INSERT INTO chain_cursor VALUES(1,1,?)',(self.block,))
  self.descriptor,self.consumer_objects=capture(self.fixture.consumer.dbpath,'primary-apps',self.owner,self.chains['primary']['chain_id'])
  self.objects.update(self.consumer_objects)
  self.raw=b''.join(self.consumer_objects[c['sha256']]for c in self.descriptor['state']['chunks'])
  self.payload=validate_payload(self.raw,self.descriptor,self.chains['primary']['chain_id'])
 def test_real_native_receipt_and_watermark_are_committed_in_local_dual_checkpoint(self):
  self.chains['primary']['consumer_state']=[self.descriptor]
  value=verify(seal(self.chains,self.keys,2),self.expected,self.signers,self.objects.__getitem__)
  self.assertEqual(value.manifest['chains']['primary']['consumer_state'][0]['receipts_root'],self.descriptor['receipts_root'])
  job=self.payload['tables']['jobs'][0];self.assertEqual(job['state'],'completed_read');self.assertIn('native_status',bytes.fromhex(job['result']['$blob']).decode())
  guard_existing(self.payload,copy.deepcopy(self.payload))
 def test_foreign_owner_cursor_and_duplicate_journal_are_rejected_even_when_resigned(self):
  for change in ['owner','cursor','duplicate']:
   chains=copy.deepcopy(self.chains);descriptor=copy.deepcopy(self.descriptor)
   if change=='owner':descriptor['owner_identity']='f'*64
   elif change=='cursor':descriptor['canonical_hash']='e'*64
   chains['primary']['consumer_state']=[descriptor]* (2 if change=='duplicate' else 1)
   with self.assertRaises(CheckpointError):verify(seal(chains,self.keys,2),self.expected,self.signers,self.objects.__getitem__)
 def test_private_receipts_cannot_be_distributed_in_remote_bootstrap(self):
  self.chains['primary']['consumer_state']=[self.descriptor]
  with self.assertRaises(CheckpointError):verify(seal(self.chains,self.keys,2,'explicit-signer-bootstrap'),self.expected,self.signers,self.objects.__getitem__,allow_bootstrap=True)
 def test_rollback_cannot_erase_receipts_uncertain_effects_or_sequence_watermarks(self):
  for change in ['forget','queued','receipt','watermark']:
   restored=copy.deepcopy(self.payload)
   if change=='forget':restored['tables']['jobs']=[]
   elif change=='queued':restored['tables']['jobs'][0]['state']='queued'
   elif change=='receipt':restored['tables']['jobs'][0]['result']=None
   else:restored['tables']['sequences'][0]['sequence']=0
   with self.assertRaises(CheckpointError):guard_existing(self.payload,restored)
  uncertain=copy.deepcopy(self.payload);uncertain['tables']['jobs'][0]['state']='unknown'
  with self.assertRaises(CheckpointError):guard_existing(uncertain,self.payload)

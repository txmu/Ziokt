import copy,json,tempfile,threading,unittest,zipfile,os
from pathlib import Path
import test_checkpoint_format as fixtures
from ziokt.checkpoint_format import *
from ziokt.checkpoint_store import CheckpointStore,export_bundle
class CheckpointStoreTests(unittest.TestCase):
 def setUp(self):
  fixtures.CheckpointTests.setUp(self);self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.store=CheckpointStore(self.root/'store',self.expected,self.signers)
 def test_real_generation_switch_and_explicit_rollback(self):
  first=self.store.publish(self.manifest,self.objects);next_manifest=seal(self.chains,self.keys,2);second=self.store.publish(next_manifest,self.objects)
  self.assertEqual(self.store.current().manifest['snapshot_hash'],second.manifest['snapshot_hash'])
  self.store.activate(first.manifest['snapshot_hash']);self.assertEqual(self.store.current().manifest['snapshot_hash'],first.manifest['snapshot_hash'])
 def test_corrupt_bundle_never_switches_current_generation(self):
  self.store.publish(self.manifest,self.objects);before=(self.store.root/'current').readlink();objects=dict(self.objects);objects[next(iter(objects))]=b'corrupt'
  with self.assertRaises(CheckpointError):self.store.publish(seal(self.chains,self.keys,2),objects)
  self.assertEqual((self.store.root/'current').readlink(),before);self.store.current()
 def test_archive_path_escape_and_duplicate_member_rejected_without_extraction(self):
  self.store.publish(self.manifest,self.objects);before=(self.store.root/'current').readlink()
  for name in ['../escape','objects/../../escape','/tmp/escape']:
   bundle=self.root/'bad.zip'
   with zipfile.ZipFile(bundle,'w')as z:z.writestr('manifest.json',canonical(self.manifest));z.writestr(name,b'bad')
   with self.assertRaises(CheckpointError):self.store.import_bundle(bundle)
   self.assertEqual((self.store.root/'current').readlink(),before)
  self.assertFalse((self.root/'escape').exists())
 def test_real_chunk_bundle_round_trip_and_rechecked_disk_corruption(self):
  bundle=self.root/'valid.zip';export_bundle(bundle,self.manifest,self.objects);result=self.store.import_bundle(bundle);self.assertEqual(result.states['dna'],verify(self.manifest,self.expected,self.signers,self.objects.__getitem__).states['dna'])
  chunk=next((self.store.generations/result.manifest['snapshot_hash']/'objects').iterdir());chunk.write_bytes(b'changed')
  with self.assertRaises(CheckpointError):self.store.current()
 def test_concurrent_readers_observe_complete_pair_generations(self):
  self.store.publish(self.manifest,self.objects);errors=[];stop=threading.Event()
  def reader():
   while not stop.is_set():
    try:
     value=self.store.current();self.assertEqual(set(value.states),{'primary','dna'});self.assertEqual(value.states['primary'],verify(self.manifest,self.expected,self.signers,self.objects.__getitem__).states['primary'])
    except BaseException as error:errors.append(error);break
  worker=threading.Thread(target=reader);worker.start()
  try:
   for at in range(2,8):self.store.publish(seal(self.chains,self.keys,at),self.objects)
  finally:stop.set();worker.join(5)
  self.assertEqual(errors,[]);self.assertFalse(worker.is_alive())
 def test_symlinked_generation_and_fifo_manifest_fail_without_reading_targets(self):
  result=self.store.publish(self.manifest,self.objects);generation=self.store.generations/result.manifest['snapshot_hash']
  moved=generation.with_name('retained');generation.rename(moved);generation.symlink_to(moved.name,target_is_directory=True)
  with self.assertRaises(CheckpointError):self.store.current()
  generation.unlink();moved.rename(generation);manifest=generation/'manifest.json';manifest.unlink();os.mkfifo(manifest,0o600)
  with self.assertRaises(CheckpointError):self.store.current()

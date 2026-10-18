"""Real SafeFS ciphertext and durable SQLite; no storage mocks."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ziokt.chunkstore import ChunkStore, CHUNK_BYTES
from ziokt.protocol import ProtocolError
from ziokt.safefs import Vault


def sha(data):return 'sha256:'+hashlib.sha256(data).hexdigest()


class ChunkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.key=b'k'*32
        self.store=self.open();self.addCleanup(lambda:self.store.close())

    def open(self,**limits):return ChunkStore(Vault(self.root,'ufs',self.key),**limits)

    def upload(self,name,data):
        self.store.begin(name,len(data),sha(data),3600)
        for pos,offset in enumerate(range(0,len(data),CHUNK_BYTES)):
            chunk=data[offset:offset+CHUNK_BYTES];self.store.put(name,pos,sha(chunk),chunk)
        return self.store.finish(name)

    def test_restart_duplicate_integrity_and_dedup_gc(self):
        chunk=os.urandom(CHUNK_BYTES);data=chunk*2+b'tail'
        self.store.begin('resume',len(data),sha(data),3600)
        self.store.put('resume',0,sha(chunk),chunk);self.store.close();self.store=self.open()
        self.assertEqual(self.store.status('resume')['next_missing'],1)
        self.store.put('resume',0,sha(chunk),chunk)
        with self.assertRaises(ProtocolError):self.store.finish('resume')
        other=b'x'*CHUNK_BYTES
        with self.assertRaises(ProtocolError):self.store.put('resume',0,sha(other),other)
        for pos,part in ((1,chunk),(2,b'tail')):self.store.put('resume',pos,sha(part),part)
        ref=self.store.finish('resume');self.assertFalse(ref['execution_authorized'])
        self.assertEqual(b''.join(self.store.stream(ref['manifest_digest'])),data)
        self.assertEqual(self.store.finish('resume'),ref)
        self.assertEqual(len(list(self.store.data.iterdir())),2)
        self.assertEqual(self.store.gc()['live_chunks'],2)
        self.assertFalse(any(chunk in p.read_bytes() for p in self.store.data.iterdir()))
        self.store.release(ref['manifest_digest'],'resume');self.assertEqual(self.store.gc()['removed_chunks'],2)
        self.assertEqual(list(self.store.data.iterdir()),[])

    def test_corruption_full_hash_incomplete_scope_and_quota(self):
        with self.assertRaises(ProtocolError):self.store.begin('large',513*1024*1024,sha(b''),3600)
        self.store.begin('bad',4,sha(b'good'),3600)
        self.store.put('bad',0,sha(b'evil'),b'evil')
        with self.assertRaises(ProtocolError) as e:self.store.finish('bad')
        self.assertEqual(e.exception.code,'OBJECT_INTEGRITY')
        self.store.abort('bad');self.store.gc()
        ref=self.upload('small',b'hello')
        other=ChunkStore(Vault(self.root,'dcpm',self.key))
        try:
            with self.assertRaises(ProtocolError):other.reference(ref['manifest_digest'])
        finally:other.close()
        path=next(self.store.data.iterdir());path.write_bytes(b'corrupt')
        with self.assertRaises(ProtocolError):self.store.read(ref['manifest_digest'],0)
        limited=self.open(disk_bytes=1)
        try:
            with self.assertRaises(ProtocolError) as e:limited.begin('quota',1,sha(b'x'),1)
            self.assertEqual(e.exception.code,'STORAGE_QUOTA')
        finally:limited.close()

    def test_expiry_empty_limits_and_cross_process_resume(self):
        empty=self.upload('empty',b'');self.assertEqual(list(self.store.stream(empty['manifest_digest'])),[])
        chunk=b'a'*CHUNK_BYTES;self.store.begin('child',len(chunk),sha(chunk),3600)
        code='''from pathlib import Path
from ziokt.chunkstore import ChunkStore
from ziokt.safefs import Vault
import hashlib,sys
s=ChunkStore(Vault(Path(sys.argv[1]),'ufs',b'k'*32))
b=b'a'*16384
s.put('child',0,'sha256:'+hashlib.sha256(b).hexdigest(),b)
s.close()
'''
        subprocess.run([sys.executable,'-c',code,str(self.root)],check=True,timeout=10)
        self.assertEqual(self.store.status('child')['next_missing'],1)
        self.store.finish('child')
        self.store.begin('expired',1,sha(b'x'),1)
        with self.store.db:self.store.db.execute("UPDATE uploads SET expires=0 WHERE id='expired'")
        with self.assertRaises(ProtocolError) as e:self.store.put('expired',0,sha(b'x'),b'x')
        self.assertEqual(e.exception.code,'UPLOAD_EXPIRED')
        self.store.gc()


@unittest.skipUnless(os.environ.get('ZIOKT_LARGE_OBJECT_MIB'),'CI/manual large-object tier')
class LargeChunkTests(unittest.TestCase):
    def test_streamed_large_resume_with_memory_budget(self):
        import tracemalloc
        size=int(os.environ['ZIOKT_LARGE_OBJECT_MIB'])*1024*1024
        # Deterministic distinct chunks avoid testing only a single dedup block.
        def block(i):return hashlib.shake_256(str(i).encode()).digest(CHUNK_BYTES)
        count=size//CHUNK_BYTES;full=hashlib.sha256()
        for i in range(count):full.update(block(i))
        with tempfile.TemporaryDirectory() as root:
            key=b'z'*32;s=ChunkStore(Vault(Path(root),'ufs',key));tracemalloc.start()
            try:
                s.begin('large',size,'sha256:'+full.hexdigest(),3600)
                for i in range(count):
                    if i==count//2:
                        s.close();s=ChunkStore(Vault(Path(root),'ufs',key))
                        self.assertEqual(s.status('large')['next_missing'],i)
                    part=block(i);s.put('large',i,sha(part),part)
                ref=s.finish('large');length=0
                for part in s.stream(ref['manifest_digest']):length+=len(part)
                self.assertEqual(length,size)
                from ziokt.ufsdcpm import reference_package,verify_reference_package,MAX_REFERENCE_FILE
                from ziokt.security import sign
                if size<=MAX_REFERENCE_FILE:
                    public=sign({},key,'test')['public_key']
                    package=reference_package(s,'large','1.0.0',{'payload':ref['manifest_digest']},[],key)
                    self.assertEqual(verify_reference_package(s,package,public)['content_bytes'],size)
                else:
                    with self.assertRaises(ProtocolError):reference_package(s,'large','1.0.0',{'payload':ref['manifest_digest']},[],key)
                self.assertLess(tracemalloc.get_traced_memory()[1],48*1024*1024)
            finally:s.close();tracemalloc.stop()


if __name__=='__main__':unittest.main()

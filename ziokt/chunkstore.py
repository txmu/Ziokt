"""Scoped resumable objects over existing SafeFS AEAD chunks.

Payload bytes are encrypted; the private journal stores hashes and progress.
References confer no authority; the caller must still
enter through its configured application bridge. No compression or execution.
"""
import hashlib
import hmac
import os
from pathlib import Path
import sqlite3
import time

from .protocol import ProtocolError, encoded, identifier, secure_read
from .safefs import Vault, _private_dir
from .cli import write_binary_exclusive

CHUNK_BYTES = 16384
MAX_OBJECT_BYTES = 512 * 1024 * 1024
DISK_BYTES = 2 * 1024 * 1024 * 1024
MAX_UPLOADS = 16


def digest(value):
    if not isinstance(value, str) or len(value) != 71 or not value.startswith('sha256:') or any(c not in '0123456789abcdef' for c in value[7:]):
        raise ProtocolError('INVALID_OBJECT', 'sha256 reference required')
    return value


from ._verified_guards import within_budget


class ChunkStore:
    def __init__(self, vault, *, max_object=MAX_OBJECT_BYTES, disk_bytes=DISK_BYTES):
        self.vault = vault
        self.root = _private_dir(vault.root / ('chunks-' + vault.scope))
        self.data = _private_dir(self.root / 'data')
        self.max_object, self.disk_bytes = max_object, disk_bytes
        path = self.root / 'index.sqlite'
        if path.is_symlink():
            raise ProtocolError('UNSAFE_FILE', 'chunk journal cannot be a symlink')
        self.db = sqlite3.connect(path, timeout=15)
        self.db.execute('PRAGMA synchronous=FULL')
        os.chmod(path, 0o600)
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY,total INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY,size INTEGER,digest TEXT,expires INTEGER,state TEXT,object TEXT);
          CREATE TABLE IF NOT EXISTS chunks(tag TEXT PRIMARY KEY,digest TEXT,size INTEGER,sealed_size INTEGER);
          CREATE TABLE IF NOT EXISTS parts(upload TEXT,position INTEGER,tag TEXT,PRIMARY KEY(upload,position));
          CREATE TABLE IF NOT EXISTS objects(id TEXT PRIMARY KEY,size INTEGER,digest TEXT);
          CREATE TABLE IF NOT EXISTS pins(holder TEXT,object TEXT,PRIMARY KEY(holder,object));
          CREATE TABLE IF NOT EXISTS members(object TEXT,position INTEGER,tag TEXT,PRIMARY KEY(object,position));
        ''')
        with self.db:
            self._lock()
            if self.db.execute('SELECT total FROM usage WHERE id=1').fetchone() is None:
                self.db.execute('INSERT INTO usage SELECT 1,coalesce(sum(sealed_size),0) FROM chunks')

    def close(self):
        self.db.close()

    def _sync_data(self):
        if os.name=='posix':
            descriptor=os.open(self.data,os.O_RDONLY|getattr(os,'O_DIRECTORY',0)|getattr(os,'O_NOFOLLOW',0))
            try:os.fsync(descriptor)
            finally:os.close(descriptor)

    def _lock(self):
        self.db.execute('BEGIN IMMEDIATE')

    def _upload(self, upload, live=True):
        identifier(upload, 'upload')
        row = self.db.execute('SELECT size,digest,expires,state,object FROM uploads WHERE id=?', (upload,)).fetchone()
        if row is None:
            raise ProtocolError('UPLOAD_NOT_FOUND', 'upload is not in this application scope')
        if live and ((row[2] <= int(time.time()) and row[3] == 'uploading') or row[3] == 'aborted'):
            raise ProtocolError('UPLOAD_EXPIRED', 'upload expired or was cancelled')
        return row

    def begin(self, upload, size, sha256, ttl):
        identifier(upload, 'upload'); digest(sha256)
        if type(size) is not int or not 0 <= size <= self.max_object or type(ttl) is not int or not 1 <= ttl <= 86400:
            raise ProtocolError('OBJECT_LIMIT', 'bounded object length and upload lifetime required')
        with self.db:
            self._lock()
            old = self.db.execute('SELECT size,digest FROM uploads WHERE id=?', (upload,)).fetchone()
            if old:
                if old != (size, sha256):
                    raise ProtocolError('IDEMPOTENCY_CONFLICT', 'upload identity already describes another object')
                self._upload(upload)
            else:
                if self.db.execute('SELECT count(*) FROM uploads').fetchone()[0]>=4096:
                    raise ProtocolError('REFERENCE_LIMIT','release completed leases and collect expired uploads before creating more')
                if self.db.execute("SELECT count(*) FROM uploads WHERE expires>? AND state='uploading'", (int(time.time()),)).fetchone()[0] >= MAX_UPLOADS:
                    raise ProtocolError('UPLOAD_LIMIT', 'too many active uploads')
                # Reserve worst-case SafeFS padding before accepting bytes.
                reserve = self.db.execute("SELECT coalesce(sum(((size+16383)/16384)*32768),0) FROM uploads WHERE state='uploading' AND expires>?", (int(time.time()),)).fetchone()[0]
                used = self.db.execute('SELECT total FROM usage WHERE id=1').fetchone()[0]
                if not within_budget(self.disk_bytes,used+reserve,((size+CHUNK_BYTES-1)//CHUNK_BYTES)*32768):
                    raise ProtocolError('STORAGE_QUOTA', 'insufficient application storage reservation')
                self.db.execute("INSERT INTO uploads VALUES(?,?,?,?,'uploading',NULL)", (upload,size,sha256,int(time.time())+ttl))
        return self.status(upload)

    def status(self, upload):
        size, sha256, expires, state, obj = self._upload(upload, live=False)
        # Ranges stay bounded even for fragmented hundreds-of-MiB transfers.
        positions = {r[0] for r in self.db.execute('SELECT position FROM parts WHERE upload=?', (upload,))}
        count = (size+CHUNK_BYTES-1)//CHUNK_BYTES
        first = next((i for i in range(count) if i not in positions), count)
        return {'schema':'ziokt.upload.v1','upload':upload,'size':size,'digest':sha256,'expires':expires,
                'state':state,'expired':state=='uploading' and expires<=int(time.time()),'chunk_bytes':CHUNK_BYTES,
                'received_chunks':count if state=='complete' else len(positions),'total_chunks':count,'next_missing':count if state=='complete' else first,'object':obj}

    def put(self, upload, position, sha256, data):
        digest(sha256)
        if not isinstance(data, bytes) or not 1 <= len(data) <= CHUNK_BYTES or 'sha256:'+hashlib.sha256(data).hexdigest() != sha256:
            raise ProtocolError('CHUNK_INTEGRITY', 'bounded chunk and matching digest required')
        with self.db:
            self._lock()
            size, _, _, state, _ = self._upload(upload)
            if state != 'uploading' or type(position) is not int or position < 0 or position*CHUNK_BYTES >= size or len(data) != min(CHUNK_BYTES,size-position*CHUNK_BYTES):
                raise ProtocolError('INVALID_CHUNK', 'exact position and chunk length required for active upload')
            tag = hmac.new(self.vault.key, (self.vault.scope+'\0'+sha256).encode(), hashlib.sha256).hexdigest()
            prior = self.db.execute('SELECT tag FROM parts WHERE upload=? AND position=?', (upload,position)).fetchone()
            if prior and prior[0] != tag:
                raise ProtocolError('IDEMPOTENCY_CONFLICT', 'chunk position already contains other bytes')
            if prior is None and self.db.execute('SELECT count(*) FROM parts').fetchone()[0]>=131072:
                raise ProtocolError('OBJECT_METADATA_QUOTA','collect completed/expired upload parts before adding more')
            stored = self.db.execute('SELECT digest FROM chunks WHERE tag=?', (tag,)).fetchone()
            if stored is None:
                sealed = self.vault.seal('chunk',data)
                used = self.db.execute('SELECT total FROM usage WHERE id=1').fetchone()[0]
                if not within_budget(self.disk_bytes,used,len(sealed)):
                    raise ProtocolError('STORAGE_QUOTA', 'application ciphertext quota exhausted')
                path = self.data/tag
                if not path.exists():
                    write_binary_exclusive(path,sealed)
                else:
                    # Crash between durable object creation and journal commit.
                    if self.vault.open(secure_read(path,32768))[1] != data:
                        raise ProtocolError('CHUNK_INTEGRITY','uncommitted chunk is corrupt')
                self._sync_data()
                self.db.execute('INSERT INTO chunks VALUES(?,?,?,?)',(tag,sha256,len(data),len(sealed)))
                self.db.execute('UPDATE usage SET total=total+? WHERE id=1',(len(sealed),))
            self.db.execute('INSERT OR IGNORE INTO parts VALUES(?,?,?)',(upload,position,tag))
        return {'schema':'ziokt.chunk-receipt.v1','upload':upload,'position':position,'digest':sha256,'stored':True,'duplicate':prior is not None}

    def _read(self, tag):
        row = self.db.execute('SELECT digest,size FROM chunks WHERE tag=?',(tag,)).fetchone()
        if row is None:
            raise ProtocolError('OBJECT_UNAVAILABLE','chunk is missing')
        data = self.vault.open(secure_read(self.data/tag,32768))[1]
        if len(data) != row[1] or 'sha256:'+hashlib.sha256(data).hexdigest() != row[0]:
            raise ProtocolError('CHUNK_INTEGRITY','stored chunk failed verification')
        return data

    def finish(self, upload):
        with self.db:
            self._lock()
            size, expected, _, state, obj = self._upload(upload)
            if state == 'complete':
                return {**self.reference(obj),'lease':upload}
            rows = self.db.execute('SELECT position,tag FROM parts WHERE upload=? ORDER BY position',(upload,)).fetchall()
            if [r[0] for r in rows] != list(range((size+CHUNK_BYTES-1)//CHUNK_BYTES)):
                raise ProtocolError('UPLOAD_INCOMPLETE','all chunks must be durably received')
            full = hashlib.sha256()
            for _, tag in rows:
                full.update(self._read(tag))
            if 'sha256:'+full.hexdigest() != expected:
                raise ProtocolError('OBJECT_INTEGRITY','full object digest rejected')
            # The ordered hash list is an equivalent verifiable chunk manifest.
            manifest = {'schema':'ziokt.chunk-manifest.v1','size':size,'digest':expected,
                        'chunks':[self.db.execute('SELECT digest FROM chunks WHERE tag=?',(tag,)).fetchone()[0] for _,tag in rows]}
            obj = 'sha256:'+hashlib.sha256(encoded(manifest)).hexdigest()
            self.db.execute('INSERT OR IGNORE INTO objects VALUES(?,?,?)',(obj,size,expected))
            self.db.executemany('INSERT OR IGNORE INTO members VALUES(?,?,?)',[(obj,i,tag) for i,tag in rows])
            self.db.execute("UPDATE uploads SET state='complete',object=? WHERE id=?",(obj,upload))
        return {**self.reference(obj),'lease':upload}

    def reference(self, obj):
        digest(obj)
        row = self.db.execute('SELECT size,digest FROM objects WHERE id=?',(obj,)).fetchone()
        if row is None:
            raise ProtocolError('OBJECT_UNAVAILABLE','verified object is not in this application scope')
        return {'schema':'ziokt.object-reference.v1','type':'opaque','source':self.vault.scope,
                'manifest_digest':obj,'digest':row[1],'length':row[0],'encoding':'identity',
                'access':'application-scoped','version':1,'lifetime':'until-explicit-release','relations':[],
                'verification':'full-sha256-and-aead','execution_authorized':False,
                'reference_count':self.db.execute("SELECT count(*) FROM uploads WHERE object=? AND state='complete'",(obj,)).fetchone()[0]+self.db.execute('SELECT count(*) FROM pins WHERE object=?',(obj,)).fetchone()[0]}

    def read(self, obj, position):
        self.reference(obj)
        if type(position) is not int or position < 0:
            raise ProtocolError('INVALID_CHUNK','nonnegative chunk index required')
        row = self.db.execute('SELECT tag FROM members WHERE object=? AND position=?',(obj,position)).fetchone()
        if row is None:
            raise ProtocolError('CHUNK_NOT_FOUND','chunk position is not in the verified manifest')
        return self._read(row[0])

    def stream(self, obj):
        # Hold the same writer lease used by GC until the consumer closes the
        # generator. Never assemble a full object in memory.
        with self.db:
            self._lock()
            ref = self.reference(obj); full = hashlib.sha256(); length = 0
            for (tag,) in self.db.execute('SELECT tag FROM members WHERE object=? ORDER BY position',(obj,)).fetchall():
                data = self._read(tag); full.update(data); length += len(data)
                yield data
            if length != ref['length'] or 'sha256:'+full.hexdigest() != ref['digest']:
                raise ProtocolError('OBJECT_INTEGRITY','stream does not match verified object')

    def abort(self, upload):
        with self.db:
            self._lock(); row = self._upload(upload,live=False)
            if row[3] == 'complete':
                raise ProtocolError('UPLOAD_COMPLETE','release verified object separately')
            self.db.execute("UPDATE uploads SET state='aborted' WHERE id=?",(upload,))
            self.db.execute('DELETE FROM parts WHERE upload=?',(upload,))
        return self.status(upload)

    def release(self, obj, upload):
        with self.db:
            self._lock(); digest(obj)
            row=self._upload(upload,live=False)
            if row[3]=='aborted' and row[4]==obj:
                return {'released':obj,'lease':upload,'duplicate':True}
            if row[3]!='complete' or row[4]!=obj:
                raise ProtocolError('INVALID_OBJECT','lease does not retain this object')
            self.db.execute('DELETE FROM parts WHERE upload=?',(upload,))
            self.db.execute("UPDATE uploads SET state='aborted' WHERE id=?",(upload,))
            if not self.db.execute("SELECT object FROM uploads WHERE object=? AND state='complete' UNION SELECT object FROM pins WHERE object=?",(obj,obj)).fetchone():
                self.db.execute('DELETE FROM members WHERE object=?',(obj,))
                self.db.execute('DELETE FROM objects WHERE id=?',(obj,))
        return {'released':obj,'lease':upload,'duplicate':False}

    def pin(self, holder, objects):
        digest(holder)
        with self.db:
            self._lock()
            objects=set(objects)
            existing={row[0] for row in self.db.execute('SELECT object FROM pins WHERE holder=?',(holder,))}
            if self.db.execute('SELECT count(*) FROM pins').fetchone()[0]+len(objects-existing)>4096:
                raise ProtocolError('REFERENCE_LIMIT','application package reference budget exhausted')
            for obj in objects:
                self.reference(obj)
                self.db.execute('INSERT OR IGNORE INTO pins VALUES(?,?)',(holder,obj))

    def unpin(self, holder):
        digest(holder)
        with self.db:
            self._lock()
            objects=[row[0] for row in self.db.execute('SELECT object FROM pins WHERE holder=?',(holder,))]
            self.db.execute('DELETE FROM pins WHERE holder=?',(holder,))
            for obj in objects:
                if not self.db.execute("SELECT object FROM uploads WHERE object=? AND state='complete' UNION SELECT object FROM pins WHERE object=?",(obj,obj)).fetchone():
                    self.db.execute('DELETE FROM members WHERE object=?',(obj,))
                    self.db.execute('DELETE FROM objects WHERE id=?',(obj,))
        return {'released_holder':holder,'objects':len(objects)}

    def gc(self):
        with self.db:
            self._lock()
            self.db.execute("DELETE FROM parts WHERE upload IN (SELECT id FROM uploads WHERE expires<=? OR state!='uploading')",(int(time.time()),))
            live = {r[0] for r in self.db.execute('SELECT tag FROM members UNION SELECT tag FROM parts')}
            removed = 0
            for path in self.data.iterdir():
                if path.name not in live:
                    path.unlink(); removed += 1
            self._sync_data()
            self.db.execute('DELETE FROM chunks WHERE tag NOT IN (SELECT tag FROM members UNION SELECT tag FROM parts)')
            self.db.execute('UPDATE usage SET total=(SELECT coalesce(sum(sealed_size),0) FROM chunks) WHERE id=1')
            self.db.execute("DELETE FROM uploads WHERE (expires<=? AND state='uploading') OR state='aborted'",(int(time.time()),))
        return {'schema':'ziokt.chunk-gc.v1','removed_chunks':removed,'live_chunks':len(live)}

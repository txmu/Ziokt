"""Bounded CDC/Merkle objects and ordered, verified multi-peer streaming.

SHA-256 remains the native Corium object address. No temporary download files.
"""
from contextlib import contextmanager, closing
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import urllib.request

MIN_CHUNK, AVG_CHUNK, MAX_CHUNK = 1 << 20, 4 << 20, 8 << 20
FANOUT = 128
GEAR = [int.from_bytes(hashlib.sha256(bytes([i])).digest()[:8], 'big') for i in range(256)]


@contextmanager
def database(path, **kwargs):
    with closing(sqlite3.connect(path, **kwargs)) as connection:
        with connection:
            yield connection


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def digest_ok(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def chunks(source):
    """Normalized gear CDC: skip minimum, stricter cut before the target size."""
    buffer = bytearray()
    rolling = 0
    while data := source.read(65536):
        for byte in data:
            buffer.append(byte)
            length = len(buffer)
            if length < MIN_CHUNK:
                continue
            rolling = ((rolling << 1) + GEAR[byte]) & ((1 << 64) - 1)
            mask = (1 << (23 if length < AVG_CHUNK else 21)) - 1
            if not rolling & mask or length == MAX_CHUNK:
                yield bytes(buffer)
                buffer.clear()
                rolling = 0
    if buffer:
        yield bytes(buffer)


class Store:
    def __init__(self, directory, database=None, peers=(), fetchers=()):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = database
        self.peers = tuple(peers[:16])
        if any(not re.fullmatch(r'https?://[A-Za-z0-9.\[\]:-]+', p) for p in self.peers):
            raise ValueError('invalid configured peer origin')
        self.scores = {}
        self.fetchers = tuple(fetchers)

    def put(self, data):
        if len(data) > MAX_CHUNK:
            raise ValueError('object too large')
        digest = hashlib.sha256(data).hexdigest()
        path = self.directory / digest
        # Repeated content is idempotent; objects are installed atomically.
        import tempfile
        fd, temporary = tempfile.mkstemp(dir=self.directory, prefix='.object-')
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(data)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        if self.database:
            with database(self.database, timeout=10) as db:
                db.execute('INSERT OR REPLACE INTO local_chunks(hash,file_path,offset,size) VALUES (?,?,0,?)',
                           (digest, str(path), len(data)))
        return digest

    def get(self, digest):
        if not digest_ok(digest): raise ValueError('invalid object address')
        try:
            with (self.directory / digest).open('rb') as source:
                data = source.read(MAX_CHUNK + 1)
            if len(data) <= MAX_CHUNK and hashlib.sha256(data).hexdigest() == digest:
                return data
        except OSError:
            pass
        # Bad/missing objects retry another peer. Downloads stay in memory.
        for peer in sorted(self.peers, key=lambda p: self.scores.get(p, 1)):
            started = time.monotonic()
            try:
                request = urllib.request.Request(peer + '/chunk/' + digest, headers={'Accept-Encoding': 'identity'})
                # Disable environment proxy inheritance; configured peers are operator-owned.
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
                with opener.open(request, timeout=8) as response:
                    data = response.read(MAX_CHUNK + 1)
                if len(data) > MAX_CHUNK or hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError('corrupt peer object')
                self.scores[peer] = time.monotonic() - started
                return data
            except (OSError, ValueError):
                self.scores[peer] = 1000 + self.scores.get(peer, 1)
        for fetch in self.fetchers:
            try:
                data=fetch(digest)
                if len(data)<=MAX_CHUNK and hashlib.sha256(data).hexdigest()==digest:return data
            except (OSError,ValueError):pass
        raise FileNotFoundError(digest)

    def publish(self, source, name='file', mime='application/octet-stream'):
        # O(fanout * tree depth) metadata, even for very large inputs.
        levels = [[]]
        def add(ref, level=0):
            if level == len(levels): levels.append([])
            levels[level].append(ref)
            if len(levels[level]) == FANOUT:
                group = levels[level]; levels[level] = []
                raw = encoded({'schema': 'ziokt.manifest.v2', 'size': sum(r['size'] for r in group), 'children': group})
                add({'hash': self.put(raw), 'size': sum(r['size'] for r in group), 'tree': True}, level + 1)
        total = 0
        for data in chunks(source):
            add({'hash': self.put(data), 'size': len(data), 'tree': False})
            total += len(data)
        for level in range(len(levels)):
            if levels[level] and level + 1 < len(levels):
                group = levels[level]; levels[level] = []
                add({'hash': self.put(encoded({'schema': 'ziokt.manifest.v2', 'size': sum(r['size'] for r in group), 'children': group})),
                     'size': sum(r['size'] for r in group), 'tree': True}, level + 1)
        root = {'schema': 'ziokt.manifest.v2', 'size': total, 'name': Path(name).name[:255],
                'mime': mime, 'children': levels[-1]}
        return self.put(encoded(root))

    def manifest(self, digest):
        data = self.get(digest)
        if len(data) > 65536: raise ValueError('manifest budget exceeded')
        value = json.loads(data)
        if value.get('schema') != 'ziokt.manifest.v2': raise ValueError('unsupported manifest')
        refs = value.get('children')
        if not isinstance(refs, list) or len(refs) > FANOUT: raise ValueError('invalid manifest fanout')
        for ref in refs:
            if set(ref) != {'hash', 'size', 'tree'} or not digest_ok(ref['hash']) or type(ref['size']) is not int or not 0 < ref['size'] < 2**63 or type(ref['tree']) is not bool:
                raise ValueError('invalid child reference')
            if not ref['tree'] and ref['size'] > MAX_CHUNK: raise ValueError('oversized leaf')
        if type(value.get('size')) is not int or value['size'] != sum(r['size'] for r in refs):
            raise ValueError('invalid manifest size')
        return value

    def selected(self, manifest, start, end, offset=0, depth=0):
        if depth > 16: raise ValueError('manifest depth exceeded')
        for ref in manifest['children']:
            stop = offset + ref['size']
            if offset <= end and stop > start:
                if ref['tree']:
                    child = self.manifest(ref['hash'])
                    if child['size'] != ref['size']: raise ValueError('subtree size mismatch')
                    yield from self.selected(child, start, end, offset, depth + 1)
                else:
                    yield ref, max(0, start-offset), min(ref['size'], end-offset+1)
            offset = stop

    def stream(self, manifest, start, end, window=4):
        if not 1 <= window <= 16: raise ValueError('invalid window')
        iterator = iter(self.selected(manifest, start, end))
        pending = []
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=window)
        try:
            for _ in range(window):
                item = next(iterator, None)
                if item: pending.append((item, pool.submit(self.get, item[0]['hash'])))
            while pending:
                (ref, left, right), future = pending.pop(0)
                data = future.result()
                if len(data) != ref['size']: raise ValueError('leaf size mismatch')
                yield memoryview(data)[left:right]
                item = next(iterator, None)
                if item: pending.append((item, pool.submit(self.get, item[0]['hash'])))
        finally:
            for _, future in pending: future.cancel()
            pool.shutdown(wait=True, cancel_futures=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('peer redirects forbidden')


def byte_range(header, size):
    if not header: return 0, size - 1
    match = re.fullmatch(r'bytes=([0-9]{0,20})-([0-9]{0,20})', header)
    if not match or not any(match.groups()) or size == 0: raise ValueError('unsatisfiable range')
    left, right = match.groups()
    if left:
        start, end = int(left), min(int(right), size-1) if right else size-1
    else:
        if int(right) == 0: raise ValueError('unsatisfiable range')
        start, end = max(0, size-int(right)), size-1
    if start >= size or start > end: raise ValueError('unsatisfiable range')
    return start, end

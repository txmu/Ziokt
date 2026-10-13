"""Bounded encrypted community exchange over the existing mTLS/grant endpoint."""
import base64
import hashlib
from pathlib import Path
import threading
import time

from .artifacts import ArtifactStore
from .community import MAX_BYTES, content_id, exact, hash_id
from .protocol import ProtocolError, encoded
from .security import sign, grant

METHODS = {'community.status', 'community.checkpoint.create', 'community.checkpoint.get', 'community.checkpoint.release',
           'community.event.put', 'community.blob.put'}


class CommunityEndpoint:
    def __init__(self, community, private):
        self.community, self.private = community, private
        self.public = sign({}, private, 'Ziokt/check-key/v1')['public_key']
        community._member(self.public, 'recover')
        self.exports = ArtifactStore(community.root/'exchange')
        self.lock = threading.RLock()
        with community.lock, community.db:
            community.db.executescript('CREATE TABLE IF NOT EXISTS community_exports (digest TEXT PRIMARY KEY,cache_key TEXT UNIQUE,size INTEGER); CREATE TABLE IF NOT EXISTS export_leases (digest TEXT,principal TEXT,expires INTEGER,PRIMARY KEY(digest,principal));')

    def _prune(self):
        now = int(time.time())
        with self.community.db:
            self.community.db.execute('DELETE FROM export_leases WHERE expires<=?', (now,))
            unused = self.community.db.execute('SELECT digest FROM community_exports WHERE digest NOT IN (SELECT digest FROM export_leases)').fetchall()
            for (digest,) in unused:
                hash_id(digest)
                path = self.exports.root/digest[7:]
                if path.exists():
                    self.exports.get(digest)
                    path.unlink()
                self.community.db.execute('DELETE FROM community_exports WHERE digest=?', (digest,))

    def call(self, method, params, principal):
        if method not in METHODS: raise ProtocolError('POLICY_DENIED', 'unknown community network method')
        if principal not in self.community.policy['members']:
            raise ProtocolError('POLICY_DENIED', 'current community member required')
        if method not in {'community.event.put', 'community.blob.put'}:
            self.community._member(principal, 'replicate')
        with self.lock, self.community.lock:
            self.community._current()
            if method == 'community.blob.put':
                exact(params, {'digest', 'data_base64'}); hash_id(params['digest'])
                if not set(self.community.policy['members'][principal]) & {'files', 'packages'}:
                    raise ProtocolError('POLICY_DENIED', 'content submission permission required')
                try: blob = base64.b64decode(params['data_base64'], validate=True)
                except (ValueError, TypeError): raise ProtocolError('INVALID_REQUEST', 'bounded ciphertext encoding required')
                return {'digest': self.community.put_blob(blob, params['digest'])}
            if method == 'community.event.put':
                exact(params, {'digest', 'parts'}); hash_id(params['digest'])
                if not isinstance(params['parts'], list) or len(params['parts']) != 2:
                    raise ProtocolError('INVALID_REQUEST', 'two bounded encrypted event parts required')
                try: blob = b''.join(base64.b64decode(p, validate=True) for p in params['parts'])
                except (ValueError, TypeError): raise ProtocolError('INVALID_REQUEST', 'event encoding rejected')
                if content_id(blob) != params['digest']: raise ProtocolError('ARTIFACT_DIGEST_MISMATCH', 'event ciphertext differs from submitted digest')
                event = self.community._validate_event(blob, self.community._policies())
                if event['author'] != principal and 'recover' not in self.community.policy['members'][principal]:
                    raise ProtocolError('POLICY_DENIED', 'ordinary members submit only their own signed events')
                if event['domain'] in {'files', 'packages'} and not event['deleted']:
                    self.community.get_file(event['body'])
                return self.community.admit([blob])
            if method == 'community.status':
                exact(params, set())
                return {'community_id': self.community.community_id, 'policy': self.community.policy_id,
                        'records': self.community.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],
                        'publisher': self.public, 'runtime_ready': False,
                        'inventory_digest': self.community.inventory_digest(), 'origin': self.community.origin()}
            self._prune()
            if method == 'community.checkpoint.create':
                exact(params, {'origin', 'after'})
                if not isinstance(params['origin'], str) or type(params['after']) is not int or not 0 <= params['after'] < 2**53:
                    raise ProtocolError('INVALID_REQUEST', 'bounded source cursor required')
                inventory = self.community.inventory_digest()
                cache_key = content_id(encoded({'inventory': inventory, 'cursor': params}))
                row = self.community.db.execute('SELECT digest,size FROM community_exports WHERE cache_key=?', (cache_key,)).fetchone()
                if row:
                    digest, size = row
                    self.exports.get(digest)
                else:
                    if self.community.db.execute('SELECT COUNT(*) FROM community_exports').fetchone()[0] >= 4:
                        raise ProtocolError('BACKPRESSURE', 'four active checkpoint leases already use the export budget')
                    blob = self.community.checkpoint(self.private, after=params['after'], origin=params['origin'])
                    digest, size = self.exports.put(blob), len(blob)
                    with self.community.db:
                        self.community.db.execute('INSERT INTO community_exports VALUES (?,?,?)', (digest, cache_key, size))
                with self.community.db:
                    self.community.db.execute('INSERT OR REPLACE INTO export_leases VALUES (?,?,?)', (digest, principal, int(time.time())+600))
                return {'digest': digest, 'size': size, 'publisher': self.public,
                        'community_id': self.community.community_id, 'policy': self.community.policy_id}
            if method == 'community.checkpoint.release':
                exact(params, {'digest'}); hash_id(params['digest'])
                with self.community.db:
                    self.community.db.execute('DELETE FROM export_leases WHERE digest=? AND principal=?', (params['digest'], principal))
                self._prune()
                return {'released': True}
            exact(params, {'digest', 'offset', 'length'})
            hash_id(params['digest'])
            if type(params['offset']) is not int or params['offset'] < 0 or type(params['length']) is not int or not 1 <= params['length'] <= 6144:
                raise ProtocolError('INVALID_REQUEST', 'bounded snapshot content range required')
            lease = self.community.db.execute('SELECT expires FROM export_leases WHERE digest=? AND principal=?', (params['digest'], principal)).fetchone()
            if not lease or lease[0] <= int(time.time()):
                raise ProtocolError('POLICY_DENIED', 'caller needs an active scoped checkpoint lease')
            with self.community.db:
                self.community.db.execute('UPDATE export_leases SET expires=? WHERE digest=? AND principal=?', (int(time.time())+600, params['digest'], principal))
            data, size = self.exports.read_range(params['digest'], params['offset'], params['length'])
            return {'digest': params['digest'], 'offset': params['offset'], 'size': size,
                    'data_base64': base64.b64encode(data).decode()}


def sync_remote(community, endpoint, context, private, *, publisher, cancellation=None):
    """Fresh scoped grants per range; immutable digest pinned before restoration.

    Does not enable a direct path when a restricted community loses its carrier.
    Local apps and backups continue to function if this call cannot connect.
    """
    from .remote import request_remote, resource_for
    with community.lock: community._current()
    from .routes import resolve_endpoint
    endpoint = resolve_endpoint(community.policy['privacy'], endpoint)
    def call(method, params):
        if cancellation is not None and cancellation.is_set(): raise ProtocolError('CANCELLED', 'community sync cancelled')
        request = {'provider_id': community.community_id, 'method': method, 'params': params}
        token = lambda: grant(private, audience=community.community_id, action=method, resource=resource_for(method, params),
                      federation=community.community_id, request_digest=content_id(encoded(request)))
        return request_remote(endpoint['host'], endpoint['port'], context, request, token, carrier=endpoint.get('carrier'), cancellation=cancellation)
    status = call('community.status', {})
    exact(status, {'community_id', 'policy', 'records', 'publisher', 'runtime_ready', 'inventory_digest', 'origin'})
    if status['community_id'] != community.community_id or status['policy'] != community.policy_id or status['publisher'] != publisher:
        raise ProtocolError('SCOPE_MISMATCH', 'remote community policy or publisher differs')
    if status['inventory_digest'] == community.inventory_digest():
        return {'unchanged': True, 'runtime_ready': False, 'native_apply_required': True}
    item = call('community.checkpoint.create', {'origin': status['origin'], 'after': community.cursor(publisher, status['origin'])})
    exact(item, {'digest', 'size', 'publisher', 'community_id', 'policy'})
    hash_id(item['digest'])
    if (item['publisher'] != publisher or item['community_id'] != community.community_id or item['policy'] != community.policy_id or
            type(item['size']) is not int or not 32 <= item['size'] <= MAX_BYTES):
        raise ProtocolError('SCOPE_MISMATCH', 'remote checkpoint publisher, policy or budget mismatch')
    data = bytearray()
    while len(data) < item['size']:
        length = min(6144, item['size']-len(data))
        part = call('community.checkpoint.get', {'digest': item['digest'], 'offset': len(data), 'length': length})
        exact(part, {'digest', 'offset', 'size', 'data_base64'})
        if part['digest'] != item['digest'] or part['offset'] != len(data) or part['size'] != item['size']:
            raise ProtocolError('INVALID_RESPONSE', 'immutable snapshot range drifted')
        try: chunk = base64.b64decode(part['data_base64'], validate=True)
        except (ValueError, TypeError): raise ProtocolError('INVALID_RESPONSE', 'invalid range encoding')
        if len(chunk) != length: raise ProtocolError('INVALID_RESPONSE', 'truncated snapshot range')
        data.extend(chunk)
    if content_id(data) != item['digest']:
        raise ProtocolError('ARTIFACT_DIGEST_MISMATCH', 'downloaded checkpoint differs from pinned digest')
    result = community.restore(bytes(data), publisher)
    released = call('community.checkpoint.release', {'digest': item['digest']})
    if released != {'released': True}: raise ProtocolError('INVALID_RESPONSE', 'checkpoint lease release not confirmed')
    return {**result, 'download_bytes': len(data)}


def push_remote(community, endpoint, context, private, *, cancellation=None):
    """Idempotent submission of this member's current-policy signed events."""
    from .remote import request_remote, resource_for
    from .routes import resolve_endpoint
    endpoint = resolve_endpoint(community.policy['privacy'], endpoint)
    public = sign({}, private, 'test')['public_key']
    if public not in community.policy['members']: raise ProtocolError('POLICY_DENIED', 'current writer membership required')
    peer = content_id(encoded({'host': endpoint['host'], 'port': endpoint['port']}))
    with community.lock, community.db:
        community._current()
        community.db.execute('CREATE TABLE IF NOT EXISTS submitted_events (peer TEXT,event TEXT,PRIMARY KEY(peer,event))')
        events = community._events()
        completed = {row[0] for row in community.db.execute('SELECT event FROM submitted_events WHERE peer=?', (peer,))}
        selected = {d: e for d, e in events.items() if e['author'] == public and e['policy'] == community.policy_id and d not in completed}
        blobs = {d: community.db.execute('SELECT sealed FROM records WHERE id=?', (d,)).fetchone()[0] for d in selected}
    def call(method, params):
        if cancellation is not None and cancellation.is_set(): raise ProtocolError('CANCELLED', 'community submission cancelled')
        request = {'provider_id': community.community_id, 'method': method, 'params': params}
        token = lambda: grant(private, audience=community.community_id, action=method, resource=resource_for(method, params),
                      federation=community.community_id, request_digest=content_id(encoded(request)))
        return request_remote(endpoint['host'], endpoint['port'], context, request, token, carrier=endpoint.get('carrier'), cancellation=cancellation)
    order, visited = [], set()
    def visit(d):
        if d in visited: return
        visited.add(d)
        for parent in selected[d]['parents']:
            if parent in selected: visit(parent)
        order.append(d)
    for d in selected: visit(d)
    uploaded = set()
    for d in order:
        event = selected[d]
        if event['domain'] in {'files', 'packages'} and not event['deleted']:
            for object_id in sorted(community._file_objects(event['body'])[1]):
                if object_id in uploaded: continue
                result = call('community.blob.put', {'digest': object_id, 'data_base64': base64.b64encode(community.store.get(object_id)).decode()})
                if result != {'digest': object_id}: raise ProtocolError('INVALID_RESPONSE', 'content acceptance differs from submitted digest')
                uploaded.add(object_id)
        blob = blobs[d]
        result = call('community.event.put', {'digest': d, 'parts': [base64.b64encode(blob[:4096]).decode(), base64.b64encode(blob[4096:]).decode()]})
        if not isinstance(result, dict) or result.get('events') != [d] or result.get('added') not in {0, 1}:
            raise ProtocolError('INVALID_RESPONSE', 'signed event acceptance not confirmed')
        with community.lock, community.db:
            community._current()
            community.db.execute('INSERT OR IGNORE INTO submitted_events VALUES (?,?)', (peer, d))
    return {'submitted': len(order), 'uploaded_objects': len(uploaded)}


class SyncWorker:
    """Foreground-owned bounded synchronization; no routing or privacy downgrade."""
    def __init__(self, community, private, peers, interval=10):
        if not isinstance(peers, list) or not 1 <= len(peers) <= 4 or type(interval) is not int or not 1 <= interval <= 3600:
            raise ProtocolError('INVALID_CONFIG', 'one to four approved peers and bounded sync interval required')
        self.community, self.private, self.peers, self.interval = community, private, peers, interval
        self.stopped = threading.Event(); self.lock = threading.Lock(); self.latest = []
        self.thread = None

    def cycle(self):
        results = []
        for peer in self.peers:
            if self.stopped.is_set(): break
            try:
                # Pull ancestors first, then submit local edits. Imported events
                # are not re-signed or submitted as this member's own content.
                received = sync_remote(self.community, peer['endpoint'], peer['context'], self.private, publisher=peer['publisher'], cancellation=self.stopped)
                sent = push_remote(self.community, peer['endpoint'], peer['context'], self.private, cancellation=self.stopped)
                results.append({'healthy': True, 'received': received.get('records', 0), 'submitted': sent['submitted']})
            except (ProtocolError, OSError) as exc:
                results.append({'healthy': False, 'error': getattr(exc, 'code', 'PEER_UNAVAILABLE')})
        with self.lock: self.latest = results
        return results

    def start(self):
        if self.thread is not None: raise ProtocolError('INVALID_CONFIG', 'sync worker already started')
        def run():
            failures = 0
            while not self.stopped.is_set():
                results = self.cycle()
                failures = min(failures+1, 6) if any(not r['healthy'] for r in results) else 0
                if self.stopped.wait(min(600, self.interval*2**failures)): break
        self.thread = threading.Thread(target=run, name='community-sync', daemon=True); self.thread.start()

    def close(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(35)
            if self.thread.is_alive(): raise ProtocolError('SYNC_BUSY', 'current bounded network request is still draining')


def load_peers(path):
    from .protocol import secure_read, strict_json
    from .remote import load_remote, tls_context
    value = strict_json(secure_read(path))
    exact(value, {'schema', 'peers'})
    if value['schema'] != 'ziokt.community-peers.v1' or not isinstance(value['peers'], list) or not 1 <= len(value['peers']) <= 4:
        raise ProtocolError('INVALID_CONFIG', 'bounded explicit peer catalog required')
    results, seen = [], set()
    for item in value['peers']:
        exact(item, {'tls_config', 'publisher'})
        from .community import PUBLIC
        if not isinstance(item['publisher'], str) or not PUBLIC.fullmatch(item['publisher']) or not isinstance(item['tls_config'], str) or not Path(item['tls_config']).is_absolute():
            raise ProtocolError('INVALID_CONFIG', 'fixed peer material path and pinned publisher required')
        endpoint = load_remote(item['tls_config'])
        identity = (endpoint['host'], endpoint['port'], item['publisher'])
        if identity in seen: raise ProtocolError('INVALID_CONFIG', 'duplicate peer endpoint')
        seen.add(identity)
        context = tls_context(endpoint['certificate'], endpoint['private_key'], endpoint['ca'])
        results.append({'endpoint': endpoint, 'context': context, 'publisher': item['publisher']})
    return results

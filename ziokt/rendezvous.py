"""Approved outbound-only opaque rendezvous, independent of community data keys."""
import base64
import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from types import SimpleNamespace

from .community import PUBLIC, MAX_BYTES, exact, content_id, hash_id, policy_document
from .protocol import ProtocolError, encoded, strict_json, secure_read, make_private
from .security import sign, verify, grant

RELAY_METHODS = {'relay.start', 'relay.part.put', 'relay.list', 'relay.part.get', 'relay.ack'}
PART = 4096
RELAY_BYTES = 64*1024*1024


class OpaqueRendezvous:
    def __init__(self, root, policy, owner):
        self.policy = policy_document(policy, owner)
        self.policy_id = content_id(encoded(policy))
        self.community = SimpleNamespace(community_id=self.policy['community_id'])
        self.root = Path(root)
        if self.root.is_symlink(): raise ProtocolError('UNSAFE_FILE', 'relay root cannot be a symlink')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True); make_private(self.root)
        path = self.root/'relay.sqlite'
        if path.exists(): secure_read(path, 128*1024*1024)
        self.db = sqlite3.connect(path, timeout=5, check_same_thread=False); make_private(path)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS envelopes (id TEXT PRIMARY KEY,sender TEXT,recipient TEXT,size INTEGER,parts INTEGER,expires INTEGER,document BLOB); CREATE TABLE IF NOT EXISTS chunks (id TEXT,part INTEGER,data BLOB,PRIMARY KEY(id,part));')
        self.db.execute('CREATE TABLE IF NOT EXISTS relay_policy (id INTEGER PRIMARY KEY,epoch INTEGER,digest TEXT)')
        old = self.db.execute('SELECT epoch,digest FROM relay_policy WHERE id=1').fetchone()
        if old and (self.policy['epoch'] < old[0] or self.policy['epoch'] == old[0] and self.policy_id != old[1]):
            self.db.close(); raise ProtocolError('POLICY_ROLLBACK', 'relay policy cannot roll back or fork')
        with self.db: self.db.execute('INSERT OR REPLACE INTO relay_policy VALUES (1,?,?)', (self.policy['epoch'],self.policy_id))
        self.lock = threading.RLock()

    def close(self): self.db.close()

    def _prune(self):
        with self.db:
            self.db.execute('DELETE FROM chunks WHERE id IN (SELECT id FROM envelopes WHERE expires<=?)', (int(time.time()),))
            self.db.execute('DELETE FROM envelopes WHERE expires<=?', (int(time.time()),))

    def call(self, method, params, principal):
        if method not in RELAY_METHODS or 'replicate' not in self.policy['members'].get(principal, []):
            raise ProtocolError('POLICY_DENIED', 'approved relay method and current member required')
        with self.lock:
            if self.db.execute('SELECT digest FROM relay_policy WHERE id=1').fetchone()[0] != self.policy_id:
                raise ProtocolError('STALE_POLICY', 'relay authority was superseded')
            self._prune()
            if method == 'relay.start':
                exact(params, {'envelope'})
                value = verify(params['envelope'], principal, 'Ziokt/rendezvous/v1')
                exact(value, {'schema', 'community_id', 'policy', 'sender', 'recipient', 'digest', 'size', 'parts', 'nonce', 'expires'})
                if (value['schema'] != 'ziokt.rendezvous.v1' or value['community_id'] != self.community.community_id or value['policy'] != self.policy_id or value['sender'] != principal or
                        value['recipient'] not in self.policy['members'] or type(value['size']) is not int or not 32 <= value['size'] <= MAX_BYTES or
                        type(value['parts']) is not int or value['parts'] != (value['size']+PART-1)//PART or
                        not isinstance(value['nonce'], str) or not __import__('re').fullmatch('[a-f0-9]{32}', value['nonce']) or
                        type(value['expires']) is not int or not int(time.time()) < value['expires'] <= int(time.time())+3600):
                    raise ProtocolError('INVALID_RELAY', 'signed scoped relay envelope rejected')
                hash_id(value['digest']); packet_id = content_id(encoded(params['envelope']))
                old = self.db.execute('SELECT document FROM envelopes WHERE id=?', (packet_id,)).fetchone()
                if old:
                    if old[0] != encoded(params['envelope']): raise ProtocolError('IDEMPOTENCY_CONFLICT', 'relay packet changed')
                    return {'packet_id': packet_id}
                count, total = self.db.execute('SELECT COUNT(*),COALESCE(SUM(size),0) FROM envelopes').fetchone()
                if count >= 64 or total+value['size'] > RELAY_BYTES:
                    raise ProtocolError('BACKPRESSURE', 'relay queue storage budget exhausted')
                with self.db:
                    self.db.execute('INSERT INTO envelopes VALUES (?,?,?,?,?,?,?)', (packet_id, principal, value['recipient'], value['size'], value['parts'], value['expires'], encoded(params['envelope'])))
                return {'packet_id': packet_id}
            if method == 'relay.list':
                exact(params, set())
                rows = self.db.execute('SELECT id,document,parts FROM envelopes WHERE recipient=? ORDER BY id LIMIT 16', (principal,)).fetchall()
                return {'packets': [{'packet_id': r[0], 'envelope': strict_json(r[1])} for r in rows if self.db.execute('SELECT COUNT(*) FROM chunks WHERE id=?', (r[0],)).fetchone()[0] == r[2]]}
            expected = {'packet_id'} if method == 'relay.ack' else {'packet_id', 'part'}|({'data_base64'} if method == 'relay.part.put' else set())
            exact(params, expected); hash_id(params['packet_id'])
            row = self.db.execute('SELECT sender,recipient,size,parts FROM envelopes WHERE id=?', (params['packet_id'],)).fetchone()
            if not row: raise ProtocolError('RELAY_EXPIRED', 'relay packet unavailable')
            index = params.get('part', 0)
            if type(index) is not int or not 0 <= index < row[3]: raise ProtocolError('INVALID_RELAY', 'bounded relay part index required')
            if method == 'relay.part.put':
                if principal != row[0]: raise ProtocolError('POLICY_DENIED', 'only signed packet sender can upload')
                try: data = base64.b64decode(params['data_base64'], validate=True)
                except (ValueError, TypeError): raise ProtocolError('INVALID_RELAY', 'relay part encoding rejected')
                if len(data) != min(PART, row[2]-index*PART): raise ProtocolError('INVALID_RELAY', 'relay part length changed')
                old = self.db.execute('SELECT data FROM chunks WHERE id=? AND part=?', (params['packet_id'], index)).fetchone()
                if old and old[0] != data: raise ProtocolError('IDEMPOTENCY_CONFLICT', 'immutable relay part changed')
                with self.db: self.db.execute('INSERT OR IGNORE INTO chunks VALUES (?,?,?)', (params['packet_id'], index, data))
                return {'stored': True}
            if principal != row[1]: raise ProtocolError('POLICY_DENIED', 'relay packet belongs to another recipient')
            if method == 'relay.ack':
                with self.db:
                    self.db.execute('DELETE FROM chunks WHERE id=?', (params['packet_id'],))
                    self.db.execute('DELETE FROM envelopes WHERE id=?', (params['packet_id'],))
                return {'acknowledged': True}
            part = self.db.execute('SELECT data FROM chunks WHERE id=? AND part=?', (params['packet_id'], index)).fetchone()
            if not part: raise ProtocolError('RELAY_INCOMPLETE', 'relay part unavailable')
            return {'data_base64': base64.b64encode(part[0]).decode()}


class RendezvousClient:
    def __init__(self, community, endpoint, context, private):
        from .routes import admit_endpoint
        admit_endpoint(community.policy['privacy'], endpoint)
        self.community, self.endpoint, self.context, self.private = community, endpoint, context, private
        self.public = sign({}, private, 'test')['public_key']
        self.community._member(self.public, 'replicate')

    def call(self, method, params):
        from .remote import request_remote, resource_for
        with self.community.lock: self.community._current()
        request = {'provider_id': self.community.community_id, 'method': method, 'params': params}
        token = grant(self.private, audience=self.community.community_id, action=method, resource=resource_for(method, params),
                      federation=self.community.community_id, request_digest=content_id(encoded(request)))
        return request_remote(self.endpoint['host'], self.endpoint['port'], self.context, request, token, carrier=self.endpoint.get('carrier'))

    def send(self, recipient):
        # The approved archival sender signs a checkpoint; the relay gets only
        # ciphertext and scoped routing metadata, never community decryption keys.
        with self.community.lock:
            checkpoint = self.community.checkpoint(self.private)
            value = {'schema': 'ziokt.rendezvous.v1', 'community_id': self.community.community_id,
                     'policy': self.community.policy_id, 'sender': self.public, 'recipient': recipient,
                     'digest': content_id(checkpoint), 'size': len(checkpoint), 'parts': (len(checkpoint)+PART-1)//PART,
                     'nonce': secrets.token_hex(16), 'expires': int(time.time())+3600}
        envelope = sign(value, self.private, 'Ziokt/rendezvous/v1')
        result = self.call('relay.start', {'envelope': envelope}); packet_id = content_id(encoded(envelope))
        if result != {'packet_id': packet_id}: raise ProtocolError('INVALID_RESPONSE', 'relay packet identity not confirmed')
        for index in range(value['parts']):
            part = checkpoint[index*PART:(index+1)*PART]
            if self.call('relay.part.put', {'packet_id': packet_id, 'part': index, 'data_base64': base64.b64encode(part).decode()}) != {'stored': True}:
                raise ProtocolError('INVALID_RESPONSE', 'relay did not confirm immutable part')
        return {'packet_id': packet_id, 'queued': True, 'delivered': False}

    def receive(self):
        result = self.call('relay.list', {}); exact(result, {'packets'})
        if not isinstance(result['packets'], list) or len(result['packets']) > 16: raise ProtocolError('INVALID_RESPONSE', 'relay queue limit changed')
        restored = []
        for item in result['packets']:
            exact(item, {'packet_id', 'envelope'})
            envelope = item['envelope']
            sender = envelope.get('public_key') if isinstance(envelope, dict) else None
            self.community._member(sender, 'recover')
            value = verify(envelope, sender, 'Ziokt/rendezvous/v1')
            if (value.get('recipient') != self.public or value.get('community_id') != self.community.community_id or
                    value.get('policy') != self.community.policy_id or type(value.get('size')) is not int or not 32 <= value['size'] <= MAX_BYTES or
                    type(value.get('parts')) is not int or value['parts'] != (value['size']+PART-1)//PART or
                    type(value.get('expires')) is not int or value['expires'] <= int(time.time()) or content_id(encoded(envelope)) != item['packet_id']):
                raise ProtocolError('INVALID_RELAY', 'relay envelope scope or expiry rejected')
            data = bytearray()
            for index in range(value['parts']):
                part = self.call('relay.part.get', {'packet_id': item['packet_id'], 'part': index}); exact(part, {'data_base64'})
                try: raw = base64.b64decode(part['data_base64'], validate=True)
                except (ValueError, TypeError): raise ProtocolError('INVALID_RESPONSE', 'relay response encoding rejected')
                if len(raw) != min(PART, value['size']-len(data)): raise ProtocolError('INVALID_RESPONSE', 'relay response size changed')
                data.extend(raw)
            if content_id(data) != value['digest']: raise ProtocolError('ARTIFACT_DIGEST_MISMATCH', 'relay ciphertext differs from signed digest')
            restored.append(self.community.restore(bytes(data), sender))
            if self.call('relay.ack', {'packet_id': item['packet_id']}) != {'acknowledged': True}:
                raise ProtocolError('INVALID_RESPONSE', 'relay acknowledgement not confirmed')
        return {'received': len(restored), 'results': restored}

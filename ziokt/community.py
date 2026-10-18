"""Portable signed community applications with encrypted, coordinator-free replicas.

No host execution follows an application record. Native deployment continues to
use reviewed workflows. A replica is measured by bytes, not catalog presence.
"""
import copy
import base64
import hashlib
import os
from pathlib import Path
import re
import secrets
import sqlite3
import struct
import threading

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidTag

from .artifacts import ArtifactStore
from .protocol import ProtocolError, encoded, identifier, strict_json, secure_read, make_private
from .security import sign, verify

DOMAINS = {'forum', 'chat', 'wiki', 'files', 'packages', 'mail', 'names', 'governance', 'hosting', 'compute', 'identity'}
RIGHTS = DOMAINS | {'replicate', 'recover', 'discover', 'moderate'}
MAX_EVENTS = 1024
MAX_BLOBS = 4096
MAX_BYTES = 32 * 1024 * 1024
EVENT_FRAME = 8192
CHUNK_FRAME = 4096
CHUNK_DATA = CHUNK_FRAME-32
MAX_FILE = 8 * 1024 * 1024
DIGEST = re.compile(r'sha256:[a-f0-9]{64}\Z')
PUBLIC = re.compile(r'[a-f0-9]{64}\Z')


def content_id(data):
    return 'sha256:'+hashlib.sha256(data).hexdigest()


def exact(value, fields, code='INVALID_COMMUNITY'):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ProtocolError(code, 'exact bounded community object required')


def hash_id(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ProtocolError('INVALID_COMMUNITY', 'exact content digest required')
    return value


def policy_document(envelope, owner):
    value = verify(envelope, owner, 'Ziokt/community-policy/v1')
    base = {'schema', 'community_id', 'epoch', 'members', 'privacy'}
    if not isinstance(value, dict) or not base <= set(value) or set(value)-base-{'limits', 'registration'}:
        raise ProtocolError('INVALID_COMMUNITY', 'exact signed community policy required')
    if value['schema'] != 'ziokt.community-policy.v1' or type(value['epoch']) is not int or not 0 <= value['epoch'] < 2**53:
        raise ProtocolError('INVALID_COMMUNITY', 'bounded community policy epoch required')
    identifier(value['community_id'], 'community_id')
    if not isinstance(owner, str) or not PUBLIC.fullmatch(owner) or not isinstance(value['privacy'], str) or value['privacy'] not in {'private', 'restricted'}:
        raise ProtocolError('INVALID_COMMUNITY', 'pinned owner and explicit private policy required')
    if not isinstance(value['members'], dict) or not 1 <= len(value['members']) <= 64 or owner not in value['members']:
        raise ProtocolError('INVALID_COMMUNITY', 'bounded explicit community membership required')
    for key, rights in value['members'].items():
        if (not PUBLIC.fullmatch(key) or not isinstance(rights, list) or len(rights) > len(RIGHTS) or
                any(not isinstance(r, str) or r not in RIGHTS for r in rights) or len(rights) != len(set(rights))):
            raise ProtocolError('INVALID_COMMUNITY', 'exact member permissions required')
    if 'limits' in value:
        exact(value['limits'], {'events', 'objects', 'file_bytes', 'checkpoint_bytes'})
        for field, maximum in [('events', MAX_EVENTS), ('objects', MAX_BLOBS), ('file_bytes', MAX_FILE), ('checkpoint_bytes', MAX_BYTES)]:
            if type(value['limits'][field]) is not int or not 1 <= value['limits'][field] <= maximum:
                raise ProtocolError('INVALID_COMMUNITY', 'explicit resource budget exceeds hard safety ceiling')
    if 'registration' in value:
        registration = value['registration']
        exact(registration, {'required', 'provider_id', 'issuer', 'admin_public', 'admin_mailbox'})
        if (type(registration['required']) is not bool or
                not isinstance(registration['provider_id'], str) or
                not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', registration['provider_id']) or
                any(not isinstance(registration[k], str) or not PUBLIC.fullmatch(registration[k])
                    for k in ('issuer', 'admin_public', 'admin_mailbox')) or
                registration['admin_public'] not in value['members']):
            raise ProtocolError('INVALID_COMMUNITY', 'exact registration authority and mailbox required')
    return value


def create_policy(private, community_id, members, *, epoch=0, privacy='restricted', limits=None, registration=None):
    document = {'schema': 'ziokt.community-policy.v1', 'community_id': community_id,
                'epoch': epoch, 'members': members, 'privacy': privacy}
    if limits is not None: document['limits'] = limits
    if registration is not None: document['registration'] = registration
    envelope = sign(document, private, 'Ziokt/community-policy/v1')
    policy_document(envelope, envelope['public_key'])
    return envelope


class Community:
    def __init__(self, root, policy, owner, encryption_key, *, readonly=False):
        if type(readonly) is not bool:raise ValueError('explicit community read mode required')
        self.readonly=readonly
        self.policy = policy_document(policy, owner)
        self.policy_envelope, self.owner = policy, owner
        self.limits = self.policy.get('limits', {'events': MAX_EVENTS, 'objects': MAX_BLOBS,
                                               'file_bytes': MAX_FILE, 'checkpoint_bytes': MAX_BYTES})
        self.community_id = self.policy['community_id']
        self.policy_id = content_id(encoded(policy))
        if not isinstance(encryption_key, bytes) or len(encryption_key) != 32:
            raise ProtocolError('INVALID_COMMUNITY', 'independently held 32-byte community key required')
        key = HKDF(hashes.SHA256(), 32, None, b'Ziokt/community/'+self.community_id.encode()).derive(encryption_key)
        self.cipher = AESGCM(key)
        self._key_material = [key]
        self._read_ciphers = [self.cipher]
        self.root = Path(root)
        if self.root.is_symlink(): raise ProtocolError('UNSAFE_FILE', 'community directory cannot be a symlink')
        if readonly and not self.root.is_dir():raise ProtocolError('NATIVE_STATE_UNAVAILABLE','read-only community node is not initialized')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not readonly:make_private(self.root)
        self._ring_path = self.root/'keyrings'/self.policy_id[7:]
        if self._ring_path.exists(): self._adopt_keys(self._decode_ring(secure_read(self._ring_path, 4096)))
        path = self.root/'community.sqlite'
        if path.exists(): secure_read(path, 64*1024*1024)
        self.store = ArtifactStore(self.root/'objects')
        self.lock = threading.RLock()
        self._event_cache = {}
        if readonly:
            self.db=sqlite3.connect(path.absolute().as_uri()+'?mode=ro',uri=True,timeout=5,check_same_thread=False)
            try:
                latest=self.db.execute('SELECT id,epoch,document FROM policies ORDER BY epoch DESC LIMIT 1').fetchone()
                if not latest or latest[0]!=self.policy_id or latest[1]!=self.policy['epoch']:
                    raise ProtocolError('STALE_POLICY','read-only naming node policy changed')
                policy_document(strict_json(latest[2]),owner)
            except BaseException:self.db.close();raise
            return
        self.db = sqlite3.connect(path, timeout=5, check_same_thread=False)
        make_private(path)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS policies (id TEXT PRIMARY KEY, epoch INTEGER UNIQUE, document BLOB); CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, sealed BLOB NOT NULL);')
        self.db.executescript('CREATE TABLE IF NOT EXISTS node_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS sync_cursors (publisher TEXT,origin TEXT,policy TEXT,seq INTEGER NOT NULL,PRIMARY KEY(publisher,origin,policy));')
        try:
            with self.db:
                newest = self.db.execute('SELECT id,epoch,document FROM policies ORDER BY epoch DESC LIMIT 1').fetchone()
                if newest:
                    previous = policy_document(strict_json(newest[2]), owner)
                    if previous['community_id'] != self.community_id or self.policy['epoch'] < newest[1]:
                        raise ProtocolError('POLICY_ROLLBACK', 'community scope or policy epoch rolled back')
                    if self.policy['epoch'] == newest[1] and self.policy_id != newest[0]:
                        raise ProtocolError('POLICY_CONFLICT', 'same epoch has another policy')
                self.db.execute('INSERT OR IGNORE INTO policies VALUES (?,?,?)', (self.policy_id, self.policy['epoch'], encoded(policy)))
                self.db.execute("INSERT OR IGNORE INTO node_metadata VALUES ('origin',?)", (secrets.token_hex(32),))
        except BaseException:
            self.db.close(); raise

    def close(self): self.db.close()
    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def _current(self):
        latest = self.db.execute('SELECT id FROM policies ORDER BY epoch DESC LIMIT 1').fetchone()
        if latest[0] != self.policy_id:
            raise ProtocolError('STALE_POLICY', 'another local handle advanced policy; reopen with current policy')

    def _seal(self, data, kind, frame=None):
        nonce = secrets.token_bytes(12)
        plain = struct.pack('!I', len(data))+data
        if frame is not None:
            if len(plain)+28 > frame: raise ProtocolError('COMMUNITY_LIMIT', 'record exceeds padded frame')
            plain += secrets.token_bytes(frame-28-len(plain))
        return nonce+self.cipher.encrypt(nonce, plain, ('Ziokt/community/'+self.community_id+'/'+kind).encode())

    def _open(self, blob, kind):
        if not isinstance(blob, bytes) or not 32 <= len(blob) <= MAX_BYTES:
            raise ProtocolError('INVALID_COMMUNITY', 'bounded authenticated community blob required')
        plain = None
        for cipher in self._read_ciphers:
            try:
                plain = cipher.decrypt(blob[:12], blob[12:], ('Ziokt/community/'+self.community_id+'/'+kind).encode())
                break
            except InvalidTag: pass
        if plain is None:
            raise ProtocolError('COMMUNITY_AUTH_FAILED', 'community blob authentication failed')
        if len(plain) < 4: raise ProtocolError('INVALID_COMMUNITY', 'truncated community plaintext')
        size = struct.unpack('!I', plain[:4])[0]
        if size > len(plain)-4: raise ProtocolError('INVALID_COMMUNITY', 'invalid encrypted length')
        return plain[4:4+size]

    def _adopt_keys(self, keys):
        merged = list(dict.fromkeys(self._key_material+keys))
        if len(merged) > 16: raise ProtocolError('COMMUNITY_LIMIT', 'historical key budget exceeded')
        self._key_material = merged
        self._read_ciphers = [AESGCM(k) for k in merged]

    def _ring_blob(self):
        return self._seal(encoded({'policy': self.policy_id, 'keys': [k.hex() for k in self._key_material[1:]]}), 'keyring', 4096)

    def _decode_ring(self, blob):
        # Only the currently supplied key can unwrap historical keys. A revoked
        # holder of an earlier key cannot unwrap the next epoch's keyring.
        if not isinstance(blob, bytes) or len(blob) != 4096:
            raise ProtocolError('INVALID_COMMUNITY', 'fixed encrypted historical keyring required')
        try:
            plain = self.cipher.decrypt(blob[:12], blob[12:], ('Ziokt/community/'+self.community_id+'/keyring').encode())
            size = struct.unpack('!I', plain[:4])[0]
            if size > len(plain)-4: raise ValueError()
            value = strict_json(plain[4:4+size]); exact(value, {'policy', 'keys'})
            if value['policy'] != self.policy_id or not isinstance(value['keys'], list) or len(value['keys']) > 15:
                raise ValueError()
            if any(not isinstance(k, str) or not PUBLIC.fullmatch(k) for k in value['keys']): raise ValueError()
            return [bytes.fromhex(k) for k in value['keys']]
        except (InvalidTag, ValueError, TypeError):
            raise ProtocolError('COMMUNITY_AUTH_FAILED', 'current epoch key cannot unwrap historical keys')

    def _persist_ring(self):
        directory = self._ring_path.parent
        if directory.is_symlink(): raise ProtocolError('UNSAFE_FILE', 'keyring directory cannot be a symlink')
        directory.mkdir(mode=0o700, exist_ok=True); make_private(directory)
        if self._ring_path.exists():
            self._adopt_keys(self._decode_ring(secure_read(self._ring_path, 4096)))
        import tempfile
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
            temporary = Path(output.name)
            output.write(self._ring_blob()); output.flush(); os.fsync(output.fileno())
        try:
            make_private(temporary); os.replace(temporary, self._ring_path)
        finally: temporary.unlink(missing_ok=True)

    def rotate(self, new_policy, new_key, private):
        """Owner-authorized new epoch; old signed events and parent IDs survive."""
        with self.lock:
            self._current()
            if sign({}, private, 'test')['public_key'] != self.owner:
                raise ProtocolError('POLICY_DENIED', 'owner authority required for confidentiality rotation')
            value = policy_document(new_policy, self.owner)
            if value['community_id'] != self.community_id or value['epoch'] <= self.policy['epoch'] or new_key == private:
                raise ProtocolError('POLICY_ROLLBACK', 'rotation requires matching scope and increasing epoch')
            if not isinstance(new_key, bytes) or len(new_key) != 32:
                raise ProtocolError('INVALID_COMMUNITY', 'new independent encryption key required')
            derived = HKDF(hashes.SHA256(), 32, None, b'Ziokt/community/'+self.community_id.encode()).derive(new_key)
            if derived in self._key_material:
                raise ProtocolError('INVALID_COMMUNITY', 'confidentiality rotation requires a fresh key')
            # Prepare the authenticated historical keyring before advancing the
            # SQLite policy. If the process dies here, old policy still works;
            # reopening with the reviewed new key/policy can complete rotation.
            policy_id = content_id(encoded(new_policy)); nonce = secrets.token_bytes(12)
            raw = encoded({'policy': policy_id, 'keys': [k.hex() for k in self._key_material]})
            if len(self._key_material) >= 16: raise ProtocolError('COMMUNITY_LIMIT', 'historical key budget exceeded')
            plain = struct.pack('!I', len(raw))+raw+secrets.token_bytes(4064-len(raw))
            blob = nonce+AESGCM(derived).encrypt(nonce, plain, ('Ziokt/community/'+self.community_id+'/keyring').encode())
            directory = self.root/'keyrings'
            if directory.is_symlink(): raise ProtocolError('UNSAFE_FILE', 'keyring directory cannot be a symlink')
            directory.mkdir(mode=0o700, exist_ok=True); make_private(directory)
            target = directory/policy_id[7:]
            from .cli import write_binary_exclusive
            write_binary_exclusive(target, blob)
            return Community(self.root, new_policy, self.owner, new_key)

    def _member(self, public, right, policy=None):
        policy = self.policy if policy is None else policy
        if right not in policy['members'].get(public, []):
            raise ProtocolError('POLICY_DENIED', 'community member lacks operation permission')

    def _validate_body(self, domain, body, deleted):
        if not isinstance(body, dict) or len(encoded(body)) > 3500 or type(deleted) is not bool:
            raise ProtocolError('INVALID_APPLICATION', 'bounded typed application body required')
        if deleted:
            exact(body, {'reason'}, 'INVALID_APPLICATION')
            if not isinstance(body['reason'], str): raise ProtocolError('INVALID_APPLICATION', 'deletion reason required')
            return
        specs = {
            'forum': {'title', 'text', 'reply_to'}, 'chat': {'text', 'channel'},
            'wiki': {'title', 'text'}, 'files': {'name', 'chunks', 'size', 'digest'},
            'packages': {'name', 'version', 'chunks', 'size', 'digest', 'native_kind', 'native_signature'},
            'mail': {'to', 'ciphertext'}, 'names': {'target'},
            'governance': {'proposal', 'choice'}, 'hosting': {'service', 'workflow_digest', 'content'},
            'compute': {'job', 'workflow_digest', 'result'}, 'identity': {'name', 'public_key', 'mailbox_public'}}
        exact(body, specs[domain], 'INVALID_APPLICATION')
        for name, value in body.items():
            if name in {'chunks', 'size'}: continue
            if not isinstance(value, str) or len(value.encode()) > (2800 if name == 'ciphertext' else 2048):
                raise ProtocolError('INVALID_APPLICATION', 'bounded text application fields required')
        if domain in {'files', 'packages'}:
            if type(body['size']) is not int or not 0 <= body['size'] <= MAX_FILE:
                raise ProtocolError('INVALID_APPLICATION', 'bounded encrypted content manifest required')
            if isinstance(body['chunks'], dict):
                exact(body['chunks'], {'root'}, 'INVALID_APPLICATION'); hash_id(body['chunks']['root'])
            elif isinstance(body['chunks'], list) and 1 <= len(body['chunks']) <= 32:
                for chunk in body['chunks']: hash_id(chunk)
            else:
                raise ProtocolError('INVALID_APPLICATION', 'bounded content list or encrypted index required')
            hash_id(body['digest'])
        if domain == 'packages' and body['native_kind'] not in {'shadow6-app', 'shadow6-plugin', 'shadow6-mod', 'corium-package'}:
            raise ProtocolError('INVALID_APPLICATION', 'original native package kind required')
        if domain in {'hosting', 'compute'}: hash_id(body['workflow_digest'])
        if domain == 'governance' and body['choice'] not in {'propose', 'yes', 'no', 'abstain'}:
            raise ProtocolError('INVALID_APPLICATION', 'proposal or explicit vote choice required')
        if domain == 'identity' and not PUBLIC.fullmatch(body['public_key']):
            raise ProtocolError('INVALID_APPLICATION', 'exact identity key required')
        if domain == 'identity' and not PUBLIC.fullmatch(body['mailbox_public']):
            raise ProtocolError('INVALID_APPLICATION', 'exact recipient mailbox key required')
        if domain == 'mail' and not PUBLIC.fullmatch(body['to']):
            raise ProtocolError('INVALID_APPLICATION', 'exact recipient key required')
        if domain == 'mail':
            import base64
            try:
                if len(base64.b64decode(body['ciphertext'], validate=True)) != 2048: raise ValueError()
            except (ValueError, TypeError):
                raise ProtocolError('INVALID_MAIL', 'fixed recipient-encrypted mailbox message required')

    def _validate_event(self, blob, policies, *, historical=False):
        if len(blob) != EVENT_FRAME: raise ProtocolError('INVALID_COMMUNITY', 'fixed encrypted event frame required')
        envelope = strict_json(self._open(blob, 'event'))
        if not isinstance(envelope, dict) or not isinstance(envelope.get('public_key'), str):
            raise ProtocolError('INVALID_COMMUNITY', 'signed community event required')
        event = verify(envelope, envelope['public_key'], 'Ziokt/community-event/v1')
        exact(event, {'schema', 'community_id', 'policy', 'domain', 'key', 'parents', 'nonce', 'deleted', 'body'})
        hash_id(event['policy'])
        if event['schema'] != 'ziokt.community-event.v1' or event['community_id'] != self.community_id or event['policy'] not in policies:
            raise ProtocolError('SCOPE_MISMATCH', 'event scope or admitted policy mismatch')
        if not historical and event['policy'] != self.policy_id:
            raise ProtocolError('STALE_POLICY', 'new events require current policy')
        if not isinstance(event['domain'], str) or event['domain'] not in DOMAINS:
            raise ProtocolError('INVALID_APPLICATION', 'known community application required')
        identifier(event['key'], 'application key')
        if not isinstance(event['parents'], list) or len(event['parents']) > 32 or any(not isinstance(p, str) for p in event['parents']) or len(set(event['parents'])) != len(event['parents']):
            raise ProtocolError('INVALID_COMMUNITY', 'bounded unique parent references required')
        for parent in event['parents']: hash_id(parent)
        if not isinstance(event['nonce'], str) or not re.fullmatch('[a-f0-9]{32}', event['nonce']):
            raise ProtocolError('INVALID_COMMUNITY', 'event nonce required')
        self._member(envelope['public_key'], event['domain'], policies[event['policy']])
        if event['deleted']:
            self._member(envelope['public_key'], 'moderate', policies[event['policy']])
        self._validate_body(event['domain'], event['body'], event['deleted'])
        if event['domain'] in {'files', 'packages'} and not event['deleted']:
            limit = policies[event['policy']].get('limits', {}).get('file_bytes', MAX_FILE)
            if event['body']['size'] > limit:
                raise ProtocolError('COMMUNITY_LIMIT', 'file exceeds its signed policy resource budget')
        if event['domain'] == 'identity' and not event['deleted'] and event['body']['public_key'] != envelope['public_key']:
            raise ProtocolError('POLICY_DENIED', 'identity records must prove their own signing key')
        if event['domain'] == 'identity' and event['key'] != envelope['public_key']:
            raise ProtocolError('POLICY_DENIED', 'identity namespace belongs to its signing key')
        if event['domain'] == 'governance' and not event['deleted'] and event['body']['choice'] != 'propose':
            expected = hashlib.sha256((envelope['public_key']+'\n'+event['body']['proposal']).encode()).hexdigest()
            if event['key'] != expected:
                raise ProtocolError('POLICY_DENIED', 'one vote namespace per signer and proposal required')
        return {**event, 'author': envelope['public_key'], 'id': content_id(blob)}

    def _policies(self):
        return {row[0]: policy_document(strict_json(row[1]), self.owner) for row in self.db.execute('SELECT id,document FROM policies')}

    def _events(self):
        if self._ring_path.exists(): self._adopt_keys(self._decode_ring(secure_read(self._ring_path, 4096)))
        policies = self._policies()
        result = {}
        for event_id, blob in self.db.execute('SELECT id,sealed FROM records ORDER BY id'):
            if event_id != content_id(blob):
                raise ProtocolError('ARTIFACT_DIGEST_MISMATCH', 'stored event differs from immutable identity')
            cached = self._event_cache.get(event_id)
            if cached is None or cached[0] != blob:
                cached = (blob, self._validate_event(blob, policies, historical=True))
                self._event_cache[event_id] = cached
            result[event_id] = copy.deepcopy(cached[1])
        return result

    def _check_graph(self, events, policies=None):
        policies = self._policies() if policies is None else policies
        for event in events.values():
            for parent in event['parents']:
                if parent not in events: raise ProtocolError('MISSING_PARENT', 'causal parent unavailable; sync ancestors first')
                other = events[parent]
                if (other['domain'], other['key']) != (event['domain'], event['key']):
                    raise ProtocolError('INVALID_PARENT', 'parent belongs to another application object')
                if event['domain'] != 'wiki' and event['author'] != other['author']:
                    policy = policies[event['policy']]
                    if 'moderate' not in policy['members'].get(event['author'], []):
                        raise ProtocolError('POLICY_DENIED', 'updating another author requires moderation authority')
        # Hash-addressed signed events cannot practically form cycles, but reject
        # cycles explicitly instead of relying on that cryptographic assumption.
        visited, active = set(), set()
        def visit(node):
            if node in active: raise ProtocolError('INVALID_PARENT', 'event graph cycle')
            if node in visited: return
            if len(active) >= 128: raise ProtocolError('COMMUNITY_LIMIT', 'causal depth budget exceeded')
            active.add(node)
            for parent in events[node]['parents']: visit(parent)
            active.remove(node); visited.add(node)
        for node in events: visit(node)

    def publish(self, private, domain, key, body, *, parents=None, deleted=False):
        if not isinstance(domain, str) or domain not in DOMAINS: raise ProtocolError('INVALID_APPLICATION', 'known application required')
        identifier(key, 'application key'); self._validate_body(domain, body, deleted)
        with self.lock:
            self._current()
            if parents is None: parents = self.view(domain, key)['heads']
            event = sign({'schema': 'ziokt.community-event.v1', 'community_id': self.community_id,
                          'policy': self.policy_id, 'domain': domain, 'key': key, 'parents': parents,
                          'nonce': secrets.token_hex(16), 'deleted': deleted, 'body': body}, private, 'Ziokt/community-event/v1')
            blob = self._seal(encoded(event), 'event', EVENT_FRAME)
            return self.admit([blob])['events'][0]

    def admit(self, blobs):
        if not isinstance(blobs, list) or not 1 <= len(blobs) <= 32:
            raise ProtocolError('COMMUNITY_LIMIT', 'bounded event batch required')
        with self.lock, self.db:
            self.db.execute('BEGIN IMMEDIATE'); self._current()
            events = self._events(); policies = self._policies(); pending = {}
            for blob in blobs:
                event = self._validate_event(blob, policies)
                if event['id'] not in events: pending[event['id']] = blob
                events[event['id']] = event
            if len(events) > self.limits['events']: raise ProtocolError('COMMUNITY_LIMIT', 'event retention budget exhausted; archive first')
            self._check_graph(events, policies)
            for event_id in pending:
                event = events[event_id]
                if event['domain'] in {'files', 'packages'} and not event['deleted']:
                    self.get_file(event['body'])
            self.db.executemany('INSERT OR IGNORE INTO records VALUES (?,?)', pending.items())
            return {'events': [content_id(blob) for blob in blobs], 'added': len(pending)}

    def view(self, domain, key=None):
        if domain not in DOMAINS: raise ProtocolError('INVALID_APPLICATION', 'known application required')
        with self.lock:
            events = [e for e in self._events().values() if e['domain'] == domain and (key is None or e['key'] == key)]
            parents = {p for e in events for p in e['parents']}
            heads = sorted(e['id'] for e in events if e['id'] not in parents)
            conflicts = {}
            for event in events:
                if event['id'] in heads: conflicts.setdefault(event['key'], []).append(event['id'])
            return {'domain': domain, 'events': sorted(events, key=lambda e: e['id']), 'heads': heads,
                    'conflicts': {k: v for k, v in conflicts.items() if len(v) > 1}, 'runtime_ready': False}

    def put_file(self, data):
        if not isinstance(data, bytes) or len(data) > self.limits['file_bytes']:
            raise ProtocolError('COMMUNITY_LIMIT', 'file exceeds bounded chunk manifest')
        chunks = []
        with self.lock:
            self._current()
            for offset in range(0, max(1, len(data)), CHUNK_DATA):
                chunks.append(self.put_blob(self._seal(data[offset:offset+CHUNK_DATA], 'chunk', CHUNK_FRAME)))
            if len(chunks) > 32:
                level = 0
                while True:
                    nodes = []
                    for start in range(0, len(chunks), 32):
                        index = encoded({'schema': 'ziokt.content-index.v1', 'level': level, 'digests': chunks[start:start+32]})
                        nodes.append(self.put_blob(self._seal(index, 'chunk', CHUNK_FRAME)))
                    if len(nodes) == 1:
                        chunks = {'root': nodes[0]}; break
                    chunks = nodes; level += 1
        return {'chunks': chunks, 'size': len(data), 'digest': content_id(data)}

    def _file_objects(self, manifest, supplied=None):
        """Return ordered data chunks and all encrypted index dependencies."""
        chunks = manifest['chunks']
        if isinstance(chunks, list): return chunks, set(chunks)
        leaves, objects, active = [], set(), set()
        def visit(digest, expected_level=None):
            if digest in active or len(objects) >= MAX_BLOBS:
                raise ProtocolError('COMMUNITY_LIMIT', 'content index cycle or object budget exceeded')
            active.add(digest); objects.add(digest)
            if supplied is not None and digest not in supplied:
                raise ProtocolError('MISSING_CONTENT', 'checkpoint lacks encrypted content index')
            blob = supplied[digest] if supplied is not None else self.store.get(digest)
            index = strict_json(self._open(blob, 'chunk'))
            exact(index, {'schema', 'level', 'digests'}, 'INVALID_APPLICATION')
            if (index['schema'] != 'ziokt.content-index.v1' or type(index['level']) is not int or not 0 <= index['level'] <= 2 or
                    expected_level is not None and index['level'] != expected_level or
                    not isinstance(index['digests'], list) or not 1 <= len(index['digests']) <= 32):
                raise ProtocolError('INVALID_APPLICATION', 'bounded descending content index required')
            for child in index['digests']:
                hash_id(child)
                if index['level']:
                    visit(child, index['level']-1)
                else:
                    leaves.append(child); objects.add(child)
            active.remove(digest)
        visit(chunks['root'])
        if len(leaves) > (MAX_FILE+CHUNK_DATA-1)//CHUNK_DATA or len(objects) > MAX_BLOBS:
            raise ProtocolError('COMMUNITY_LIMIT', 'content expansion budget exceeded')
        return leaves, objects

    def put_blob(self, blob, expected=None):
        if not isinstance(blob, bytes) or len(blob) != CHUNK_FRAME:
            raise ProtocolError('INVALID_COMMUNITY', 'fixed encrypted content frame required')
        self._open(blob, 'chunk')
        with self.lock:
            self._current()
            existing = list(self.store.root.iterdir())
            if len(existing) >= self.limits['objects'] and not (self.store.root/content_id(blob)[7:]).exists():
                raise ProtocolError('COMMUNITY_LIMIT', 'encrypted chunk retention budget exhausted')
            return self.store.put(blob, expected)

    def get_file(self, manifest):
        if not isinstance(manifest, dict) or not {'chunks', 'size', 'digest'} <= set(manifest):
            raise ProtocolError('INVALID_APPLICATION', 'complete content manifest required')
        self._validate_body('files', {'name': 'content', **{k: manifest[k] for k in ('chunks', 'size', 'digest')}}, False)
        leaves, _ = self._file_objects(manifest)
        data = b''.join(self._open(self.store.get(d), 'chunk') for d in leaves)
        if len(data) != manifest['size'] or content_id(data) != manifest['digest']:
            raise ProtocolError('ARTIFACT_DIGEST_MISMATCH', 'complete plaintext file differs from signed manifest')
        return data

    def checkpoint(self, private, *, after=None, origin=None):
        with self.lock:
            self._current()
            public = sign({}, private, 'Ziokt/check-key/v1')['public_key']; self._member(public, 'recover')
            sequence = self.db.execute('SELECT COALESCE(MAX(rowid),0) FROM records').fetchone()[0]
            delta = None
            if after is not None:
                if type(after) is not int or not 0 <= after <= sequence or not isinstance(origin, str):
                    raise ProtocolError('INVALID_REQUEST', 'bounded source sequence required')
                if origin != self.origin(): after = 0
                delta = {'origin': self.origin(), 'after': after, 'through': sequence}
            records = {row[0]: row[1] for row in self.db.execute('SELECT id,sealed FROM records WHERE rowid>? ORDER BY id', (after or 0,))}
            policies = [strict_json(row[0]) for row in self.db.execute('SELECT document FROM policies ORDER BY epoch')]
            events = self._events()
            objects = sorted({d for event_id, e in events.items() if event_id in records and not e['deleted'] and e['domain'] in {'files', 'packages'} for d in self._file_objects(e['body'])[1]})
            blobs = {d: self.store.get(d) for d in objects}
            # Sign only compact immutable byte digests; payload remains encrypted.
            payload = {'schema': 'ziokt.community-checkpoint.v1', 'community_id': self.community_id,
                             'policy': self.policy_id, 'records': list(records), 'objects': list(blobs),
                             'policies': policies, 'keyring': base64.b64encode(self._ring_blob()).decode()}
            if delta is not None:
                payload['schema'] = 'ziokt.community-checkpoint.v2'; payload['delta'] = delta
            manifest = sign(payload, private, 'Ziokt/community-checkpoint/v1')
            header = encoded(manifest)
            if len(header) > 1024*1024: raise ProtocolError('COMMUNITY_LIMIT', 'checkpoint header budget exceeded')
            body = struct.pack('!I', len(header))+header+b''.join(records.values())+b''.join(blobs.values())
            if len(body)+32 > self.limits['checkpoint_bytes']: raise ProtocolError('COMMUNITY_LIMIT', 'checkpoint byte budget exceeded')
            return self._seal(body, 'checkpoint')

    def origin(self):
        with self.lock:
            return self.db.execute("SELECT value FROM node_metadata WHERE key='origin'").fetchone()[0]

    def cursor(self, publisher, origin):
        with self.lock:
            row = self.db.execute('SELECT seq FROM sync_cursors WHERE publisher=? AND origin=? AND policy=?',
                                  (publisher, origin, self.policy_id)).fetchone()
            return row[0] if row else 0

    def inventory_digest(self):
        with self.lock:
            self._current()
            events = self._events()
            objects = sorted({d for event in events.values() if not event['deleted'] and event['domain'] in {'files', 'packages'}
                              for d in self._file_objects(event['body'])[1]})
            for digest in objects: self.store.get(digest)
            return content_id(encoded({'policy': self.policy_id, 'records': sorted(events), 'objects': objects}))

    def mailbox_for(self, recipient):
        self._current()
        if recipient not in self.policy['members']:
            raise ProtocolError('POLICY_DENIED', 'recipient is not a current community member')
        result = self.view('identity', recipient)
        if len(result['heads']) != 1:
            raise ProtocolError('IDENTITY_UNRESOLVED', 'recipient needs one unambiguous signed mailbox binding')
        event = next(e for e in result['events'] if e['id'] == result['heads'][0])
        if event['deleted'] or event['author'] != recipient:
            raise ProtocolError('IDENTITY_UNRESOLVED', 'recipient identity was removed or does not prove ownership')
        return event['body']['mailbox_public']

    def vote(self, private, proposal, choice):
        identifier(proposal, 'proposal key')
        if choice not in {'yes', 'no', 'abstain'}: raise ProtocolError('INVALID_APPLICATION', 'known vote choice required')
        public = sign({}, private, 'test')['public_key']
        key = hashlib.sha256((public+'\n'+proposal).encode()).hexdigest()
        return self.publish(private, 'governance', key, {'proposal': proposal, 'choice': choice})

    def tally(self, proposal):
        identifier(proposal, 'proposal key')
        result = self.view('governance')
        heads = set(result['heads']); votes = {}; conflicts = []
        for event in result['events']:
            body = event['body']
            if event['id'] not in heads or event['deleted'] or body['proposal'] != proposal or body['choice'] == 'propose': continue
            if 'governance' not in self.policy['members'].get(event['author'], []): continue
            votes.setdefault(event['author'], []).append(body['choice'])
        counts = {'yes': 0, 'no': 0, 'abstain': 0}
        for author, choices in votes.items():
            if len(choices) != 1: conflicts.append(author)
            else: counts[choices[0]] += 1
        return {'proposal': proposal, 'votes': counts, 'conflicting_voters': sorted(conflicts),
                'execution_authorized': False, 'consensus_finality_verified': False}

    def restore(self, blob, publisher):
        # Historical keys are needed to validate old events, but a rejected
        # checkpoint must not consume the receiver's finite keyring budget.
        with self.lock:
            previous_keys = list(self._key_material)
            try:
                return self._restore(blob, publisher)
            except BaseException:
                self._key_material = previous_keys
                self._read_ciphers = [AESGCM(key) for key in previous_keys]
                raise

    def _restore(self, blob, publisher):
        with self.lock:
            self._current(); self._member(publisher, 'recover')
            if not isinstance(blob, bytes) or len(blob) > self.limits['checkpoint_bytes']:
                raise ProtocolError('COMMUNITY_LIMIT', 'checkpoint exceeds configured receive budget')
            body = self._open(blob, 'checkpoint')
            if len(body) < 4: raise ProtocolError('INVALID_COMMUNITY', 'truncated checkpoint header')
            size = struct.unpack('!I', body[:4])[0]
            if not 1 <= size <= 1024*1024 or size+4 > len(body): raise ProtocolError('COMMUNITY_LIMIT', 'checkpoint header rejected')
            envelope = strict_json(body[4:4+size], 1024*1024, string_limit=8192)
            value = verify(envelope, publisher, 'Ziokt/community-checkpoint/v1', maximum=1024*1024)
            fields = {'schema', 'community_id', 'policy', 'records', 'objects', 'policies', 'keyring'}
            delta = value.get('delta') if isinstance(value, dict) else None
            exact(value, fields|({'delta'} if delta is not None else set()))
            expected_schema = 'ziokt.community-checkpoint.v2' if delta is not None else 'ziokt.community-checkpoint.v1'
            if value['schema'] != expected_schema or value['community_id'] != self.community_id or value['policy'] != self.policy_id:
                raise ProtocolError('POLICY_ROLLBACK', 'checkpoint must match currently pinned policy')
            if delta is not None:
                exact(delta, {'origin', 'after', 'through'})
                if (not isinstance(delta['origin'], str) or not PUBLIC.fullmatch(delta['origin']) or type(delta['after']) is not int or
                        type(delta['through']) is not int or not 0 <= delta['after'] <= delta['through'] < 2**53):
                    raise ProtocolError('INVALID_COMMUNITY', 'exact signed delta sequence required')
                cursor = self.cursor(publisher, delta['origin'])
                if delta['after'] not in {0, cursor} or delta['through'] < cursor:
                    raise ProtocolError('SNAPSHOT_ROLLBACK', 'delta does not extend the admitted source sequence')
            try: keys = self._decode_ring(base64.b64decode(value['keyring'], validate=True))
            except (ValueError, TypeError): raise ProtocolError('INVALID_COMMUNITY', 'invalid encrypted historical keyring')
            self._adopt_keys(keys)
            for name, limit in [('records', MAX_EVENTS), ('objects', MAX_BLOBS)]:
                items = value[name]
                if not isinstance(items, list) or len(items) > limit or any(not isinstance(d, str) for d in items) or len(set(items)) != len(items):
                    raise ProtocolError('COMMUNITY_LIMIT', 'bounded unique checkpoint entries required')
                for digest in items: hash_id(digest)
            if not isinstance(value['policies'], list) or not 1 <= len(value['policies']) <= 64:
                raise ProtocolError('COMMUNITY_LIMIT', 'bounded policy history required')
            policies, epochs = {}, set()
            for document in value['policies']:
                policy = policy_document(document, self.owner)
                if policy['community_id'] != self.community_id or policy['epoch'] > self.policy['epoch'] or policy['epoch'] in epochs:
                    raise ProtocolError('POLICY_CONFLICT', 'checkpoint policy history rejected')
                policies[content_id(encoded(document))] = policy; epochs.add(policy['epoch'])
            if self.policy_id not in policies: raise ProtocolError('STALE_POLICY', 'checkpoint current policy absent')
            offset, pending, objects = 4+size, {}, {}
            for name, frame, target in [('records', EVENT_FRAME, pending), ('objects', CHUNK_FRAME, objects)]:
                for digest in value[name]:
                    data = body[offset:offset+frame]; offset += frame
                    if content_id(data) != digest: raise ProtocolError('ARTIFACT_DIGEST_MISMATCH', 'checkpoint entry hash mismatch')
                    target[digest] = data
            if offset != len(body): raise ProtocolError('INVALID_COMMUNITY', 'checkpoint trailing or truncated bytes')
            events = {d: self._validate_event(b, policies, historical=True) for d, b in pending.items()}
            checked = {**self._events(), **events} if delta is not None else events
            self._check_graph(checked, {**self._policies(), **policies})
            required = {d for e in events.values() if not e['deleted'] and e['domain'] in {'files', 'packages'} for d in self._file_objects(e['body'], objects)[1]}
            if required != set(objects): raise ProtocolError('MISSING_CONTENT', 'checkpoint must include exactly referenced content')
            for data in objects.values(): self._open(data, 'chunk')
            for event in events.values():
                if event['deleted'] or event['domain'] not in {'files', 'packages'}: continue
                manifest = event['body']
                leaves, _ = self._file_objects(manifest, objects)
                plain = b''.join(self._open(objects[d], 'chunk') for d in leaves)
                if len(plain) != manifest['size'] or content_id(plain) != manifest['digest']:
                    raise ProtocolError('ARTIFACT_DIGEST_MISMATCH', 'checkpoint plaintext differs from signed file manifest')
            # Authenticate everything before writing any application state. CAS
            # staging may leave harmless orphaned ciphertext if the DB fails.
            with self.db:
                self.db.execute('BEGIN IMMEDIATE'); self._current()
                merged = self._events(); merged.update(events)
                if len(merged) > self.limits['events']: raise ProtocolError('COMMUNITY_LIMIT', 'merged event retention budget exceeded')
                self._check_graph(merged, {**self._policies(), **policies})
                for d, data in objects.items(): self.put_blob(data, d)
                for document in value['policies']:
                    p = policy_document(document, self.owner)
                    old = self.db.execute('SELECT id FROM policies WHERE epoch=?', (p['epoch'],)).fetchone()
                    d = content_id(encoded(document))
                    if old and old[0] != d: raise ProtocolError('POLICY_CONFLICT', 'local historical policy fork')
                    self.db.execute('INSERT OR IGNORE INTO policies VALUES (?,?,?)', (d, p['epoch'], encoded(document)))
                self.db.executemany('INSERT OR IGNORE INTO records VALUES (?,?)', pending.items())
                self._persist_ring()
                if delta is not None:
                    cursor = self.cursor(publisher, delta['origin'])
                    if delta['after'] not in {0, cursor} or delta['through'] < cursor:
                        raise ProtocolError('SNAPSHOT_ROLLBACK', 'another receiver advanced this source cursor')
                    self.db.execute('INSERT OR REPLACE INTO sync_cursors VALUES (?,?,?,?)',
                        (publisher, delta['origin'], self.policy_id, delta['through']))
            return {'records': len(events), 'objects': len(objects), 'runtime_ready': False,
                    'native_apply_required': True, 'policy': self.policy_id}

    def replicate(self, peers, private, *, minimum=2):
        if type(minimum) is not int or not 1 <= minimum <= 4 or not isinstance(peers, list) or len(peers) > 4:
            raise ProtocolError('INVALID_REPLICATION', 'one to four explicit replica targets required')
        checkpoint = self.checkpoint(private); publisher = sign({}, private, 'Ziokt/check-key/v1')['public_key']
        verified, failed, seen = [], [], {str(self.root.resolve())}
        for peer in peers:
            location = str(peer.root.resolve())
            if location in seen: raise ProtocolError('INVALID_REPLICATION', 'duplicate or source replica directory')
            seen.add(location)
            try:
                peer.restore(checkpoint, publisher)
                receipt = peer.checkpoint(private)
                # Compare recovered immutable records and content, not randomized
                # ciphertext checkpoint envelopes or self-declared availability.
                if not set(self._events()) <= set(peer._events()): raise ProtocolError('MISSING_CONTENT', 'replica lacks source events')
                verified.append({'root': location, 'checkpoint_digest': content_id(receipt)})
            except (ProtocolError, OSError, sqlite3.Error) as exc:
                failed.append({'root': location, 'code': getattr(exc, 'code', 'REPLICA_UNAVAILABLE')})
        return {'verified': verified, 'failed': failed, 'minimum': minimum,
                'satisfied': len(verified) >= minimum, 'failure_domain_independence_verified': False}

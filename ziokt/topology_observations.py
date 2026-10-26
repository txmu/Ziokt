"""Pinned, challenge-bound observations with durable anti-replay and clock estimates.

An observer attests what it saw; this is never proof of an entire global network.
Only explicit HTTPS collectors are contacted, with no redirects or proxy inheritance.
"""
from contextlib import closing
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request

from .protocol import ProtocolError, encoded, secure_read, strict_json
from .security import sign, verify
from .package_storage import safe_path
from .runtime_policy import require_network

DOMAIN = 'Ziokt/topology-observation/v1'
IDENTIFIER = re.compile(r'[A-Za-z0-9_.:/@-]{1,160}\Z')
MAX_AGE_MS = 300000


def graph(value):
    if not isinstance(value, dict) or set(value) != {'nodes', 'edges'}:
        raise ProtocolError('INVALID_OBSERVATION', 'exact graph fields required')
    nodes, edges = value['nodes'], value['edges']
    if not isinstance(nodes, list) or len(nodes) > 128 or not isinstance(edges, list) or len(edges) > 256:
        raise ProtocolError('INVALID_OBSERVATION', 'bounded observation graph required')
    ids = set()
    for node in nodes:
        if (not isinstance(node, dict) or set(node) - {'id', 'kind', 'state', 'seen_at'} or
                not isinstance(node.get('id'), str) or not IDENTIFIER.fullmatch(node['id']) or node['id'] in ids):
            raise ProtocolError('INVALID_OBSERVATION', 'unique canonical node required')
        ids.add(node['id'])
        if 'seen_at' in node and (type(node['seen_at']) is not int or not 0<=node['seen_at']<=2**53-1):
            raise ProtocolError('INVALID_OBSERVATION','bounded node observation timestamp required')
        for field in ('kind', 'state'):
            if field in node and (not isinstance(node[field], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', node[field])):
                raise ProtocolError('INVALID_OBSERVATION', 'bounded node state required')
    for edge in edges:
        if (not isinstance(edge, dict) or set(edge) - {'source', 'target', 'relation', 'state'} or
                edge.get('source') not in ids or edge.get('target') not in ids):
            raise ProtocolError('INVALID_OBSERVATION', 'edge endpoints must be observed nodes')
        for field in ('relation', 'state'):
            if field in edge and (not isinstance(edge[field], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', edge[field])):
                raise ProtocolError('INVALID_OBSERVATION', 'bounded edge state required')
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ObservationStore:
    def __init__(self, path):
        self.path = Path(path)
        safe_path(self.path.parent, self.path.name)
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.lock = threading.RLock()
        self.cache = {}
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('CREATE TABLE IF NOT EXISTS observations (observer TEXT, component TEXT, network TEXT, sequence INTEGER, digest TEXT, document BLOB, sampled_ms INTEGER, received_ms INTEGER, offset_ms INTEGER, uncertainty_ms INTEGER, PRIMARY KEY(observer,component,network)); CREATE TABLE IF NOT EXISTS outgoing (id TEXT PRIMARY KEY, sequence INTEGER);')
        self.path.chmod(0o600)

    def export(self, source, snapshot, private, challenge):
        if not isinstance(challenge, str) or not re.fullmatch('[a-f0-9]{64}', challenge):
            raise ProtocolError('INVALID_REQUEST', '256-bit collector challenge required')
        clean = graph({'nodes': [{key: node[key] for key in ('id', 'kind', 'state', 'seen_at') if key in node} for node in snapshot['nodes'][:128]],
                       'edges': snapshot['edges'][:256]})
        identity = source['id']
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT sequence FROM outgoing WHERE id=?', (identity,)).fetchone()
            sequence = (row[0] if row else 0) + 1
            db.execute('INSERT OR REPLACE INTO outgoing VALUES (?,?)', (identity, sequence))
        now = time.time_ns() // 1000000
        sampled=snapshot.get('observed_at',now//1000)*1000
        if type(sampled) is not int or not -5000<=now-sampled<=MAX_AGE_MS:
            raise ProtocolError('OBSERVATION_STALE','source observation is stale')
        return sign({'schema': 'ziokt.topology-observation.v1', 'component': source['component'],
                     'network_id': source['network_id'], 'sequence': sequence, 'challenge': challenge,
                     'sampled_at_ms': sampled, 'sent_at_ms': now, 'graph': clean}, private, DOMAIN)

    def accept(self, source, envelope, *, started_ms, received_ms, challenge=None):
        payload = verify(envelope, source['public_key'], DOMAIN, maximum=1024*1024)
        if (not isinstance(payload, dict) or set(payload) != {'schema','component','network_id','sequence','challenge','sampled_at_ms','sent_at_ms','graph'} or
                payload['schema'] != 'ziokt.topology-observation.v1' or payload['component'] != source['component'] or
                payload['network_id'] != source['network_id']):
            raise ProtocolError('INVALID_OBSERVATION', 'observation domain mismatch')
        if challenge is not None and payload['challenge'] != challenge:
            raise ProtocolError('OBSERVATION_REPLAY', 'collector challenge mismatch')
        for field in ('sequence', 'sampled_at_ms', 'sent_at_ms'):
            if type(payload[field]) is not int or not 1 <= payload[field] <= 2**53-1:
                raise ProtocolError('INVALID_OBSERVATION', 'bounded observation integer required')
        graph(payload['graph'])
        if not 0 <= received_ms - started_ms <= 12000:
            raise ProtocolError('OBSERVATION_CLOCK', 'collection deadline exceeded')
        midpoint = (started_ms + received_ms) // 2
        offset = midpoint - payload['sent_at_ms'] if challenge is not None else 0
        uncertainty = (received_ms - started_ms + 1) // 2 if challenge is not None else 0
        sampled = payload['sampled_at_ms'] + offset
        if (abs(midpoint - payload['sent_at_ms']) > MAX_AGE_MS or
                not 0 <= payload['sent_at_ms'] - payload['sampled_at_ms'] <= MAX_AGE_MS or
                not -uncertainty <= received_ms - sampled <= MAX_AGE_MS):
            raise ProtocolError('OBSERVATION_STALE', 'observation clock or age outside budget')
        digest = hashlib.sha256(encoded(envelope)).hexdigest()
        key = (source['public_key'], source['component'], source['network_id'])
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT sequence,digest,sampled_ms FROM observations WHERE observer=? AND component=? AND network=?', key).fetchone()
            if row and (payload['sequence'] < row[0] or (payload['sequence'] == row[0] and digest != row[1])):
                raise ProtocolError('OBSERVATION_REPLAY', 'observer sequence regressed or equivocated')
            if row and payload['sequence'] == row[0]:
                if received_ms - row[2] > MAX_AGE_MS:
                    raise ProtocolError('OBSERVATION_STALE', 'replay cannot refresh old evidence')
            else:
                db.execute('INSERT OR REPLACE INTO observations VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (*key, payload['sequence'], digest, encoded(envelope), sampled, received_ms, offset, uncertainty))
        return self.latest(source, received_ms)

    def latest(self, source, now_ms=None):
        now_ms = now_ms if now_ms is not None else time.time_ns()//1000000
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT document,sampled_ms,received_ms,offset_ms,uncertainty_ms,digest FROM observations WHERE observer=? AND component=? AND network=?',
                             (source['public_key'], source['component'], source['network_id'])).fetchone()
        if not row or not -12000 <= now_ms-row[1] <= MAX_AGE_MS:
            raise ProtocolError('OBSERVATION_STALE', 'no fresh verified observation')
        payload = strict_json(row[0], 1024*1024)['payload']
        return dict(payload['graph'], evidence={'observer': source['public_key'], 'sequence': payload['sequence'],
                    'sampled_at_ms': row[1], 'received_at_ms': row[2], 'clock_offset_ms': row[3],
                    'clock_uncertainty_ms': row[4], 'digest': row[5], 'signature_verified': True})

    def evidence(self, source):
        self.latest(source)
        with closing(sqlite3.connect(self.path)) as db:
            row=db.execute('SELECT document FROM observations WHERE observer=? AND component=? AND network=?',
                (source['public_key'],source['component'],source['network_id'])).fetchone()
        return strict_json(row[0],1024*1024)

    def collect(self, source):
        with self.lock:
            now = time.monotonic()
            if now - self.cache.get(source['id'], -100) < 15:
                return self.latest(source)
            self.cache[source['id']] = now
        challenge = secrets.token_hex(32)
        started = time.time_ns()//1000000
        try:
            if source.get('url'):
                require_network()
                url = urlsplit(source['url'])
                if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise ProtocolError('INVALID_CONFIG', 'explicit HTTPS observation URL required')
                headers = {'Accept': 'application/json'}
                if source.get('token_file'):
                    headers['Authorization'] = 'Bearer '+secure_read(Path(source['token_file']),2048).decode().strip()
                request = Request(source['url']+'?'+urlencode({'challenge':challenge}), headers=headers)
                with build_opener(ProxyHandler({}),NoRedirect()).open(request, timeout=5) as response:
                    chunks=[];size=0;deadline=time.monotonic()+5
                    while True:
                        chunk=response.read1(65536)
                        if not chunk:break
                        chunks.append(chunk);size+=len(chunk)
                        if size>1024*1024 or time.monotonic()>deadline:raise ProtocolError('OBSERVATION_LIMIT','collection response budget exceeded')
                    raw=b''.join(chunks)
            else:
                raw = secure_read(Path(source['path']),1024*1024,private=None)
            envelope = strict_json(raw,1024*1024)
            return self.accept(source,envelope,started_ms=started,received_ms=time.time_ns()//1000000,
                               challenge=challenge if source.get('url') else None)
        except (OSError, ValueError, ProtocolError):
            # Loss of connectivity retains only unexpired, previously verified evidence.
            return dict(self.latest(source), collection_state='cached')

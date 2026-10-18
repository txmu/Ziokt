"""Private signed peer gossip, bounded DHT state and measured route selection.

Discovery never grants membership. Records must be signed by a current member,
bind TLS certificates, and advance persistent sequence numbers. Native address
hints are only used after this admission, never as proxy authorization.
"""
import atexit
import hashlib
import ipaddress
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time

from .community import content_id, exact, policy_document, PUBLIC
from .protocol import ProtocolError, encoded, make_private, secure_read, strict_json
from .security import sign, verify

DOMAIN = 'Ziokt/peer-discovery/v1'
MAX_RECORDS = 64
_directories = {}
_cache_lock = threading.RLock()


class PeerDirectory:
    def __init__(self, root, policy, owner, *, allowed_networks=(), native_bindings=None):
        self.policy = policy_document(policy, owner)
        self.policy_id = content_id(encoded(policy))
        if not isinstance(allowed_networks, (list, tuple)) or len(allowed_networks) > 8:
            raise ProtocolError('INVALID_DISCOVERY', 'bounded permitted discovery networks required')
        try: self.networks = [ipaddress.ip_network(n, strict=True) for n in allowed_networks]
        except (ValueError, TypeError): raise ProtocolError('INVALID_DISCOVERY', 'invalid permitted discovery network')
        self.native_bindings = native_bindings or {}
        self.root = Path(root)
        if self.root.is_symlink(): raise ProtocolError('UNSAFE_FILE', 'discovery root cannot be a symlink')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True); make_private(self.root)
        path = self.root/'peers.sqlite'
        if path.is_symlink(): raise ProtocolError('UNSAFE_FILE', 'discovery database cannot be a symlink')
        if path.exists(): secure_read(path, 16*1024*1024)
        self.db = sqlite3.connect(path, timeout=5, check_same_thread=False); make_private(path)
        self.db.execute('PRAGMA synchronous=FULL'); self.db.execute('PRAGMA secure_delete=ON')
        self.db.executescript('CREATE TABLE IF NOT EXISTS meta(id INTEGER PRIMARY KEY,epoch INTEGER,digest TEXT);'
            'CREATE TABLE IF NOT EXISTS records(public TEXT PRIMARY KEY,sequence INTEGER,expires INTEGER,document BLOB);'
            'CREATE TABLE IF NOT EXISTS water(public TEXT PRIMARY KEY,epoch INTEGER,sequence INTEGER,digest TEXT);'
            'CREATE TABLE IF NOT EXISTS health(public TEXT PRIMARY KEY,failures INTEGER,cooldown INTEGER,rtt INTEGER);')
        self.lock = threading.RLock(); self.worker = None; self.latest = []; self.local_public = None; self.cursor = 0; self.policy_path = None
        old = self.db.execute('SELECT epoch,digest FROM meta WHERE id=1').fetchone()
        if old and (self.policy['epoch'] < old[0] or self.policy['epoch'] == old[0] and self.policy_id != old[1]):
            self.db.close(); raise ProtocolError('POLICY_ROLLBACK', 'discovery policy rollback or fork rejected')
        with self.db:
            if old and self.policy_id != old[1]: self.db.execute('DELETE FROM records')
            self.db.execute('INSERT OR REPLACE INTO meta VALUES (1,?,?)', (self.policy['epoch'], self.policy_id))
            current = list(self.policy['members'])
            for table in ('records', 'health', 'water'):
                self.db.execute(f'DELETE FROM {table} WHERE public NOT IN ({",".join("?" for _ in current)})', current)

    def _current(self):
        if self.policy_path is not None and content_id(encoded(strict_json(secure_read(self.policy_path)))) != self.policy_id:
            raise ProtocolError('STALE_POLICY', 'discovery policy file changed; review and restart the directory')
        if self.db.execute('SELECT digest FROM meta WHERE id=1').fetchone()[0] != self.policy_id:
            raise ProtocolError('STALE_POLICY', 'discovery authority was superseded')

    def close(self):
        if self.worker is not None: self.worker.close()
        with self.lock: self.db.close()

    def _endpoint(self, endpoint):
        exact(endpoint, {'host', 'port', 'fingerprint', 'service'}, 'INVALID_DISCOVERY')
        from .peer_proxy import target_address
        target_address(endpoint['host'], endpoint['port'])
        if not isinstance(endpoint['fingerprint'], str) or not re.fullmatch('[a-f0-9]{64}', endpoint['fingerprint']) or not isinstance(endpoint['service'], str) or endpoint['service'] not in {'proxy', 'community'}:
            raise ProtocolError('INVALID_DISCOVERY', 'pinned certificate and explicit peer service required')
        if not endpoint['host'].endswith(('.onion', '.i2p')):
            addr = ipaddress.ip_address(endpoint['host'])
            if not addr.is_global and not any(addr in network for network in self.networks):
                raise ProtocolError('POLICY_DENIED', 'private discovery addresses need explicit local network permission')

    def validate(self, envelope):
        public = envelope.get('public_key') if isinstance(envelope, dict) else None
        if not isinstance(public, str) or 'discover' not in self.policy['members'].get(public, []):
            raise ProtocolError('POLICY_DENIED', 'current discovery member signature required')
        value = verify(envelope, public, DOMAIN)
        exact(value, {'schema', 'community_id', 'policy', 'epoch', 'sequence', 'issued_at', 'expires', 'client_fingerprint', 'endpoints'}, 'INVALID_DISCOVERY')
        now = int(time.time())
        if (value['schema'] != 'ziokt.peer-advert.v1' or value['community_id'] != self.policy['community_id'] or value['policy'] != self.policy_id or
                type(value['epoch']) is not int or value['epoch'] != self.policy['epoch'] or type(value['sequence']) is not int or not 0 <= value['sequence'] <= 2**53-1 or
                type(value['issued_at']) is not int or not now-600 <= value['issued_at'] <= now+5 or
                type(value['expires']) is not int or not now < value['expires'] <= value['issued_at']+600 or
                not isinstance(value['client_fingerprint'], str) or not re.fullmatch('[a-f0-9]{64}', value['client_fingerprint']) or
                not isinstance(value['endpoints'], list) or not 1 <= len(value['endpoints']) <= 4):
            raise ProtocolError('INVALID_DISCOVERY', 'signed discovery scope, sequence or lifetime rejected')
        seen = set()
        for endpoint in value['endpoints']:
            self._endpoint(endpoint)
            identity = (endpoint['host'], endpoint['port'])
            if identity in seen: raise ProtocolError('INVALID_DISCOVERY', 'duplicate advertised endpoint')
            seen.add(identity)
        return public, value

    def ingest(self, envelopes, *, ignore_stale=False):
        if not isinstance(envelopes, list) or len(envelopes) > 8:
            raise ProtocolError('INVALID_DISCOVERY', 'at most eight gossip records per exchange')
        validated = [(envelope, *self.validate(envelope)) for envelope in envelopes]
        admitted = 0
        with self.lock, self.db:
            self._current()
            self.db.execute('DELETE FROM records WHERE expires<=?', (int(time.time()),))
            for envelope, public, value in validated:
                digest = content_id(encoded(envelope))
                old = self.db.execute('SELECT epoch,sequence,digest FROM water WHERE public=?', (public,)).fetchone()
                if old and old[0] == value['epoch']:
                    if value['sequence'] < old[1]:
                        if ignore_stale: continue
                        raise ProtocolError('REPLAY_REJECTED', 'discovery sequence cannot decrease')
                    if value['sequence'] == old[1]:
                        if digest != old[2]: raise ProtocolError('IDEMPOTENCY_CONFLICT', 'discovery sequence has a signed fork')
                        continue
                count = self.db.execute('SELECT COUNT(*) FROM records').fetchone()[0]
                if count >= MAX_RECORDS and not self.db.execute('SELECT 1 FROM records WHERE public=?', (public,)).fetchone():
                    raise ProtocolError('BACKPRESSURE', 'discovery member storage budget exhausted')
                self.db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?,?)', (public, value['sequence'], value['expires'], encoded(envelope)))
                self.db.execute('INSERT OR REPLACE INTO water VALUES (?,?,?,?)', (public, value['epoch'], value['sequence'], digest))
                admitted += 1
        return admitted

    def advertise(self, private, endpoints, client_fingerprint):
        public = sign({}, private, DOMAIN)['public_key']
        with self.lock:
            old = self.db.execute('SELECT epoch,sequence FROM water WHERE public=?', (public,)).fetchone()
            sequence = old[1]+1 if old and old[0] == self.policy['epoch'] else 0
            now = int(time.time())
            envelope = sign({'schema': 'ziokt.peer-advert.v1', 'community_id': self.policy['community_id'], 'policy': self.policy_id,
                'epoch': self.policy['epoch'], 'sequence': sequence, 'issued_at': now, 'expires': now+300,
                'client_fingerprint': client_fingerprint, 'endpoints': endpoints}, private, DOMAIN)
            self.ingest([envelope]); return envelope

    def export(self, maximum=8):
        if type(maximum) is not int or not 1 <= maximum <= 8: raise ProtocolError('INVALID_DISCOVERY', 'bounded gossip response required')
        with self.lock:
            self._current()
            rows = self.db.execute('SELECT document FROM records WHERE expires>? ORDER BY public LIMIT 64', (int(time.time()),)).fetchall()
            if not rows: return []
            offset = self.cursor % len(rows); ordered = rows[offset:]+rows[:offset]
            self.cursor = (offset+maximum) % len(rows)
            return [strict_json(row[0]) for row in ordered[:maximum]]

    def certificate_admitted(self, fingerprint, incoming=()):
        with self.lock:
            self._current()
            rows = self.db.execute('SELECT document FROM records WHERE expires>? LIMIT 64', (int(time.time()),)).fetchall()
        for envelope in [*(strict_json(row[0]) for row in rows), *incoming]:
            try:
                public, value = self.validate(envelope)
                with self.lock:
                    water = self.db.execute('SELECT epoch,sequence,digest FROM water WHERE public=?',(public,)).fetchone()
                if water and water[0] == value['epoch'] and (value['sequence'] < water[1] or
                        value['sequence'] == water[1] and content_id(encoded(envelope)) != water[2]):
                    continue
                if value['client_fingerprint'] == fingerprint: return True
            except ProtocolError: continue
        return False

    def exchange(self, request, fingerprint):
        exact(request, {'schema', 'community_id', 'policy', 'records'}, 'INVALID_DISCOVERY')
        if request['schema'] != 'ziokt.proxy-discover.v1' or request['community_id'] != self.policy['community_id'] or request['policy'] != self.policy_id:
            raise ProtocolError('SCOPE_MISMATCH', 'discovery community differs')
        if not isinstance(request['records'], list) or len(request['records']) > 8 or not self.certificate_admitted(fingerprint, request['records']):
            raise ProtocolError('POLICY_DENIED', 'discovery TLS certificate must bind a current member signature')
        self.ingest(request['records'], ignore_stale=True)
        return {'schema': 'ziokt.proxy-discovery.v1', 'community_id': self.policy['community_id'], 'policy': self.policy_id, 'records': self.export()}

    def observe(self, public, *, success, elapsed_ms=0):
        if public not in self.policy['members'] or type(success) is not bool or type(elapsed_ms) is not int or not 0 <= elapsed_ms <= 120000:
            raise ProtocolError('INVALID_DISCOVERY', 'bounded local route observation required')
        with self.lock, self.db:
            self._current()
            old = self.db.execute('SELECT failures,rtt FROM health WHERE public=?', (public,)).fetchone()
            failures = 0 if success else min(10, (old[0] if old else 0)+1)
            cooldown = 0 if success else int(time.time())+min(300, 2**failures)+secrets.randbelow(4)
            rtt = (old[1]*3+elapsed_ms)//4 if success and old else elapsed_ms if success else old[1] if old else 120000
            self.db.execute('INSERT OR REPLACE INTO health VALUES (?,?,?,?)', (public, failures, cooldown, rtt))

    def peers(self, service='proxy'):
        result = []
        with self.lock:
            self._current()
            rows = self.db.execute('SELECT r.public,r.document,COALESCE(h.failures,0),COALESCE(h.cooldown,0),COALESCE(h.rtt,120000) '
                'FROM records r LEFT JOIN health h ON h.public=r.public WHERE r.expires>? ORDER BY COALESCE(h.failures,0),COALESCE(h.rtt,120000),r.public', (int(time.time()),)).fetchall()
        for public, raw, failures, cooldown, rtt in rows:
            if cooldown > int(time.time()): continue
            envelope = strict_json(raw); _, value = self.validate(envelope)
            for endpoint in value['endpoints']:
                if endpoint['service'] == service:
                    result.append({'public_key': public, 'endpoint': endpoint, 'rtt_ms': rtt, 'failures': failures})
        return result

    def target_carrier(self, host, port):
        for peer in self.peers('proxy')+self.peers('community'):
            endpoint = peer['endpoint']
            if (endpoint['host'], endpoint['port']) == (host, port):
                return self.native_bindings.get(peer['public_key'])
        raise ProtocolError('PROXY_DENIED', 'next hop has no live signed discovery record')

    def build_route(self, count, template, destination, *, exclude=(), randomize=False):
        if type(count) is not int or not 2 <= count <= 4:
            raise ProtocolError('INVALID_DISCOVERY', 'two to four distinct discovered proxies required')
        exact(template, {'certificate', 'private_key', 'ca'}, 'INVALID_DISCOVERY')
        from .carrier import validate_carrier
        if not isinstance(exclude,(list,tuple,set)) or len(exclude)>64 or type(randomize) is not bool:
            raise ProtocolError('INVALID_DISCOVERY','bounded excluded peers and explicit random route selection required')
        selected, seen, prefixes = [], set(), set()
        candidates=self.peers()
        if randomize: secrets.SystemRandom().shuffle(candidates)
        for peer in candidates:
            endpoint = peer['endpoint']; public = peer['public_key']
            from .ano import defence
            admitted=defence({'current_member':'discover' in self.policy['members'].get(public,[]),'distinct_member':public!=self.local_public and public not in seen,
                'healthy_route':public not in exclude,'distinct_destination':(endpoint['host'],endpoint['port'])!=destination},
                ('current_member','distinct_member','healthy_route','distinct_destination'))
            if admitted['decision']!='allow':continue
            if endpoint['host'].endswith(('.onion', '.i2p')) and public not in self.native_bindings: continue
            try: prefix = str(ipaddress.ip_network(endpoint['host']+('/24' if ':' not in endpoint['host'] else '/48'), strict=False))
            except ValueError: prefix = endpoint['host']
            # Prefer distinct network prefixes; an explicit local network may
            # contain several authorized nodes, so diversity is best effort.
            # Public networks prefer separate prefixes. Explicitly allowed
            # private subnets support local/NAT tests and authorized LAN peers.
            if prefix in prefixes and not self.networks: continue
            config = {'schema': 'ziokt.remote.v1', **template, 'host': endpoint['host'], 'port': endpoint['port']}
            path = self.tls_material('tls', public, config)
            selected.append({'host': endpoint['host'], 'port': endpoint['port'], 'tls_config': str(path), 'server_fingerprint': endpoint['fingerprint']})
            seen.add(public); prefixes.add(prefix)
            if len(selected) == count: break
        if len(selected) != count: raise ProtocolError('NO_POLICY_COMPLIANT_PATH', 'not enough healthy authenticated proxies')
        entry_public = next(p['public_key'] for p in self.peers() if (p['endpoint']['host'], p['endpoint']['port']) == (selected[0]['host'], selected[0]['port']))
        carrier = {'kind': 'peer-multihop', 'hops': selected}
        if entry_public in self.native_bindings: carrier['entry_carrier'] = self.native_bindings[entry_public]
        if any(h['host'].endswith('.i2p') for h in selected): carrier['deadline_seconds'] = 90
        validate_carrier(carrier, destination[0]); return carrier

    def tls_material(self, prefix, public, config):
        """Immutable per-endpoint templates; keep active route files intact."""
        data = encoded(config)
        path = self.root/(prefix+'-'+public+'-'+hashlib.sha256(data).hexdigest()+'.json')
        with self.lock:
            files = list(self.root.glob(prefix+'-*.json'))
            for old in files:
                if not old.is_symlink() and old.stat().st_mtime < time.time()-600:
                    old.unlink()
            if not path.exists():
                if sum(f.exists() for f in files) >= 512:
                    raise ProtocolError('BACKPRESSURE', 'discovery TLS template budget exhausted')
                _write_private(path, data)
            elif secure_read(path) != data:
                raise ProtocolError('STALE_PLAN', 'discovery TLS template changed')
        return path

    def closest(self, target, maximum=8):
        if not isinstance(target, str) or not PUBLIC.fullmatch(target) or type(maximum) is not int or not 1 <= maximum <= 8:
            raise ProtocolError('INVALID_DISCOVERY', 'bounded DHT key and neighbor count required')
        peers = self.peers()
        peers.sort(key=lambda peer: (int(hashlib.sha256(bytes.fromhex(peer['public_key'])).hexdigest(), 16)^int(target, 16), peer['public_key']))
        return peers[:maximum]


class DiscoveryWorker:
    def __init__(self, directory, config):
        self.directory, self.config = directory, config
        self.stop = threading.Event(); self.cycle_lock = threading.Lock(); self.thread = None
        self.interval = config.get('interval', 30)
        self.active = None; self.active_lock = threading.Lock()
        if type(self.interval) is not int or not 10 <= self.interval <= 300:
            raise ProtocolError('INVALID_DISCOVERY', 'bounded discovery refresh interval required')
        self.private = secure_read(config['signing_key'], 32)
        self.public = sign({}, self.private, DOMAIN)['public_key']
        if 'discover' not in directory.policy['members'].get(self.public, []):
            raise ProtocolError('POLICY_DENIED', 'worker identity is not a discovery member')
        directory.local_public = self.public
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        certificate = x509.load_pem_x509_certificate(secure_read(config['client_tls']['certificate'], 65536, private=None))
        self.fingerprint = hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()
        if not isinstance(config.get('endpoints'), list) or not 1 <= len(config['endpoints']) <= 4:
            raise ProtocolError('INVALID_DISCOVERY', 'worker needs fixed local advertised endpoints')
        for endpoint in config['endpoints']: directory._endpoint(endpoint)
        self.trackers=[]
        configured_trackers=config.get('trackers',[])
        if not isinstance(configured_trackers,list) or len(configured_trackers)>4:
            raise ProtocolError('INVALID_DISCOVERY','at most four optional trackers allowed')
        for tracker in configured_trackers:
            exact(tracker,{'tls_config','publish','anonymous','relay_authorization'},'INVALID_DISCOVERY')
            if type(tracker['publish']) is not bool or type(tracker['anonymous']) is not bool:
                raise ProtocolError('INVALID_DISCOVERY','explicit tracker publication and privacy choices required')
            from .remote import load_remote,tls_context
            from .tracker import TrackerClient
            endpoint=load_remote(tracker['tls_config'])
            context=tls_context(endpoint['certificate'],endpoint['private_key'],endpoint['ca'])
            self.trackers.append((TrackerClient(directory,self.private,endpoint,context),tracker))
        self.bootstrap = config.get('bootstrap', [])
        self.native = None
        if 'corium' in config:
            from .discovery_native import native_sources
            self.native = native_sources(config['corium'])
        if not isinstance(self.bootstrap, list) or len(self.bootstrap) > 4:
            raise ProtocolError('INVALID_DISCOVERY', 'at most four approved discovery bootstrap peers')
        for peer in self.bootstrap:
            exact(peer, {'public_key', 'tls_config', 'server_fingerprint'}, 'INVALID_DISCOVERY')
            if peer['public_key'] not in directory.policy['members'] or not isinstance(peer['server_fingerprint'], str) or not re.fullmatch('[a-f0-9]{64}', peer['server_fingerprint']):
                raise ProtocolError('INVALID_DISCOVERY', 'pinned member bootstrap authority required')
            if not isinstance(peer['tls_config'], str) or not Path(peer['tls_config']).is_absolute():
                raise ProtocolError('INVALID_DISCOVERY', 'fixed local bootstrap TLS config required')

    def _call(self, peer, own):
        from .remote import load_remote, tls_context
        from .carrier import open_carrier
        from .peer_proxy import TLSStream, read_frame, write_frame
        endpoint = load_remote(peer['tls_config'])
        context = tls_context(endpoint['certificate'], endpoint['private_key'], endpoint['ca'])
        timeout = 90 if (endpoint.get('carrier') or {}).get('kind') == 'i2p-sam' else 10
        deadline = time.monotonic()+timeout
        raw = open_carrier(endpoint['host'], endpoint['port'], endpoint.get('carrier'), timeout=timeout, cancellation=self.stop)
        with self.active_lock: self.active = raw
        stream = None
        try:
            stream = TLSStream(raw, context, endpoint['host'], deadline); stream.do_handshake()
            if hashlib.sha256(stream.tls.getpeercert(binary_form=True)).hexdigest() != peer['server_fingerprint']:
                raise ProtocolError('PROXY_DENIED', 'discovery bootstrap certificate changed')
            others = [record for record in self.directory.export(7) if record['public_key'] != self.public]
            write_frame(stream, {'schema': 'ziokt.proxy-discover.v1', 'community_id': self.directory.policy['community_id'],
                                 'policy': self.directory.policy_id, 'records': [own, *others]})
            response = read_frame(stream)
            exact(response, {'schema', 'community_id', 'policy', 'records'}, 'INVALID_DISCOVERY')
            if response['schema'] != 'ziokt.proxy-discovery.v1' or response['community_id'] != self.directory.policy['community_id'] or response['policy'] != self.directory.policy_id:
                raise ProtocolError('SCOPE_MISMATCH', 'discovery response scope differs')
            self.directory.ingest(response['records'], ignore_stale=True)
            return int((time.monotonic()-(deadline-timeout))*1000)
        finally:
            if stream is not None: stream.close()
            else: raw.close()
            with self.active_lock: self.active = None

    def cycle(self):
        if not self.cycle_lock.acquire(False): return self.directory.latest
        try:
            if self.stop.is_set(): return []
            own = self.directory.advertise(self.private, self.config['endpoints'], self.fingerprint)
            # Each optional tracker feeds the same validated directory. A
            # failed registration/query never prevents native DHT or gossip.
            for client,settings in self.trackers:
                if self.stop.is_set():break
                if settings['publish']:
                    try:client.call('tracker.register',{'envelope':own,'publish':True,'anonymous':settings['anonymous'],'relay_authorization':settings['relay_authorization']},cancellation=self.stop)
                    except (ProtocolError,OSError,ValueError):pass
                try:client.call('tracker.query',{'limit':8},cancellation=self.stop)
                except (ProtocolError,OSError,ValueError):pass
            if self.native is not None:
                from .discovery_native import fetch_records
                client, sources = self.native
                for source in sources:
                    if self.stop.is_set(): break
                    try:
                        self.directory.ingest(fetch_records(client, **source, cancellation=self.stop), ignore_stale=True)
                    except (ProtocolError, OSError):
                        self.directory.latest = [{'healthy': False}]
            with self.directory.lock:
                cooling = {r[0] for r in self.directory.db.execute('SELECT public FROM health WHERE cooldown>?', (int(time.time()),))}
            peers = [p for p in self.bootstrap if p['public_key'] not in cooling]
            for peer in self.directory.peers():
                if peer['public_key'] == self.public or any(p['public_key'] == peer['public_key'] for p in peers): continue
                endpoint = peer['endpoint']
                config = {'schema': 'ziokt.remote.v1', **self.config['client_tls'], 'host': endpoint['host'], 'port': endpoint['port']}
                if peer['public_key'] in self.directory.native_bindings: config['carrier'] = self.directory.native_bindings[peer['public_key']]
                elif endpoint['host'].endswith(('.onion', '.i2p')): continue
                path = self.directory.tls_material('gossip', peer['public_key'], config)
                peers.append({'public_key': peer['public_key'], 'tls_config': str(path), 'server_fingerprint': endpoint['fingerprint']})
            results = []
            # Bounded fanout, rotating after bootstrap, prevents a failing or
            # dishonest seed from keeping the overlay permanently isolated.
            if peers:
                offset = secrets.randbelow(len(peers)); peers = peers[offset:]+peers[:offset]
            for peer in peers[:2]:
                if self.stop.is_set(): break
                try:
                    elapsed = self._call(peer, own)
                    self.directory.observe(peer['public_key'], success=True, elapsed_ms=min(120000, elapsed))
                    results.append({'healthy': True})
                except (ProtocolError, OSError, ValueError):
                    self.directory.observe(peer['public_key'], success=False)
                    results.append({'healthy': False})
            self.directory.latest = results
            return results
        finally: self.cycle_lock.release()

    def start(self):
        if self.thread is not None: return
        def run():
            while not self.stop.is_set():
                try: self.cycle()
                except (ProtocolError, OSError): self.directory.latest = [{'healthy': False}]
                self.stop.wait(self.interval+secrets.randbelow(5))
        self.thread = threading.Thread(target=run, name='ziokt-peer-discovery', daemon=True); self.thread.start()

    def close(self):
        self.stop.set()
        with self.active_lock:
            if self.active is not None:
                import socket
                try: self.active.shutdown(socket.SHUT_RDWR)
                except OSError: pass
        if self.thread is not None:
            self.thread.join(2)
            if self.thread.is_alive():
                raise ProtocolError('DISCOVERY_BUSY', 'discovery request is still draining its deadline')


def _write_private(path, data):
    import os, tempfile
    if path.is_symlink(): raise ProtocolError('UNSAFE_FILE', 'discovery material cannot be a symlink')
    fd, name = tempfile.mkstemp(dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as output:
            make_private(temporary); output.write(data); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, path)
    finally: temporary.unlink(missing_ok=True)


def load_directory(path):
    data = secure_read(path)
    digest = content_id(data)
    with _cache_lock:
        if str(path) in _directories:
            old_digest, directory, config = _directories[str(path)]
            if old_digest != digest: raise ProtocolError('STALE_POLICY', 'restart discovery after reviewing configuration changes')
            return directory, config
        if len(_directories) >= 4: raise ProtocolError('BACKPRESSURE', 'discovery instance budget exhausted')
        config = strict_json(data)
        required = {'schema', 'enabled', 'root', 'policy', 'owner', 'allowed_networks', 'native_bindings', 'client_tls', 'hop_count'}
        optional = {'signing_key', 'client_certificate', 'endpoints', 'bootstrap', 'interval', 'corium', 'trackers'}
        if not isinstance(config, dict) or not required <= set(config) or set(config)-required-optional or config['schema'] != 'ziokt.discovery.v1' or config['enabled'] is not True:
            raise ProtocolError('DISCOVERY_DISABLED', 'exact explicitly enabled discovery config required')
        for field in ('root', 'policy', *(['signing_key'] if 'signing_key' in config else [])):
            if not isinstance(config[field], str) or not Path(config[field]).is_absolute() or '..' in Path(config[field]).parts:
                raise ProtocolError('INVALID_DISCOVERY', 'absolute discovery material path required')
        if not isinstance(config['native_bindings'], dict) or len(config['native_bindings']) > 64:
            raise ProtocolError('INVALID_DISCOVERY', 'bounded reviewed native peer bindings required')
        from .carrier import validate_carrier
        for public, binding in config['native_bindings'].items():
            if not PUBLIC.fullmatch(public) or not isinstance(binding, dict) or binding.get('kind') not in {'tor-socks5', 'i2p-sam', 'shadow6-stream'}:
                raise ProtocolError('INVALID_DISCOVERY', 'reviewed local carrier binding required')
        exact(config['client_tls'], {'certificate', 'private_key', 'ca'}, 'INVALID_DISCOVERY')
        for material in config['client_tls'].values():
            if not isinstance(material, str) or not Path(material).is_absolute() or '..' in Path(material).parts:
                raise ProtocolError('INVALID_DISCOVERY', 'fixed local discovery TLS template required')
        if type(config['hop_count']) is not int or not 2 <= config['hop_count'] <= 4:
            raise ProtocolError('INVALID_DISCOVERY', 'bounded discovered hop count required')
        directory = PeerDirectory(config['root'], strict_json(secure_read(config['policy'])), config['owner'],
                                  allowed_networks=config['allowed_networks'], native_bindings=config['native_bindings'])
        directory.policy_path = config['policy']
        _directories[str(path)] = (digest, directory, config)
        return directory, config


def close_directories():
    with _cache_lock:
        for _, directory, _ in _directories.values(): directory.close()
        _directories.clear()


atexit.register(close_directories)

"""Native gateway HTTP surface: public reads, explicit admin or client signatures."""
import hashlib
import hmac
import http.server
import json
import os
from pathlib import Path
import secrets
import sqlite3
import socket
import stat
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlsplit
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from .gateway_store import database, Store, encoded, digest_ok, byte_range

ASSETS = Path(__file__).resolve().parents[1] / 'gateway'
# zipapp deliveries contain the same versioned assets. Extract only that fixed
# subtree to a private lifetime-bound directory; never extract user archives.
_ASSET_TEMP = None
if not ASSETS.is_dir():
    import atexit, sys, tempfile, zipfile
    archive=Path(sys.argv[0])
    if archive.is_file() and zipfile.is_zipfile(archive):
        _ASSET_TEMP=tempfile.TemporaryDirectory(prefix='ziokt-gateway-assets-')
        atexit.register(_ASSET_TEMP.cleanup)
        ASSETS=Path(_ASSET_TEMP.name)/'gateway'
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                path=Path(member.filename)
                if path.parts and path.parts[0]=='gateway' and '..' not in path.parts and not path.is_absolute() and not member.is_dir():
                    dest=Path(_ASSET_TEMP.name)/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(bundle.read(member))
        (ASSETS/'native.sh').chmod(0o700)


def read_token(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 256:
            raise ValueError('invalid admin token file')
        return source.read().strip().decode('ascii')


def verify_client(payload, network, now=None):
    required = {'schema','network','title','content','reply_to','timestamp','nonce','public_key','signature'}
    if not isinstance(payload, dict) or set(payload) != required: raise ValueError('invalid signed fields')
    if payload['schema'] != 'ziokt.forum.v3' or payload['network'] != network: raise ValueError('wrong signing scope')
    now = int(time.time()) if now is None else now
    if type(payload['timestamp']) is not int or abs(now-payload['timestamp']) > 300: raise ValueError('expired signature')
    for field, maximum in [('title',256),('content',65536),('reply_to',64),('nonce',64),('public_key',64),('signature',128)]:
        if not isinstance(payload[field], str) or len(payload[field].encode()) > maximum or '\0' in payload[field]: raise ValueError('invalid '+field)
    if not payload['content'].strip() or (not payload['title'].strip() and not digest_ok(payload['reply_to'])): raise ValueError('missing topic or reply')
    if payload['reply_to'] and not digest_ok(payload['reply_to']): raise ValueError('invalid reply')
    if not digest_ok(payload['nonce']) or not digest_ok(payload['public_key']): raise ValueError('invalid nonce/key')
    unsigned = {k:v for k,v in payload.items() if k != 'signature'}
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(payload['public_key'])).verify(bytes.fromhex(payload['signature']), encoded(unsigned))
    return hashlib.sha256(bytes.fromhex(payload['public_key'])).hexdigest()


def public_endpoints(value):
    allowed={'gateway','mcp','content','corium','shadow6','openci','effort','downloads','nntp'}
    if type(value) is not dict or set(value)-allowed:raise ValueError('unknown public service endpoint')
    for name,url in value.items():
        if type(url) is not str or not 1<=len(url)<=2048:raise ValueError('bounded public endpoint URL required')
        parsed=urlsplit(url)
        if parsed.scheme not in {'http','https','nntps'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('public endpoint must not contain credentials or query secrets')
        parsed.port
    return dict(value)


class Gateway:
    def __init__(self, config, transports=False):
        from .build_info import snapshot
        self.build_info=snapshot()
        self.config = config
        self.service_endpoints=public_endpoints(config.get('public_endpoints',{}))
        from .public_address import PublicAddress
        self.public_address=PublicAddress(sources=config.get('public_address_sources'))
        self.transports=[]
        self.transport_stop=threading.Event()
        self.transport_threads=[]
        self.store = Store(config['objects'], config.get('dht_db'), config.get('peers', []))
        if transports and config.get('etp_bulk'):
            from .etp import EtpGateway,EtpRecordSocket
            from .etp_bulk import BulkPeer,serve_objects
            bulk=config['etp_bulk']
            if not 2<=len(bulk['nodes'])<=16:raise ValueError('bounded ETP node configuration required')
            for path in bulk['nodes']:
                worker=EtpGateway(bulk['binary'],bulk['digest'],path)
                worker.call('etp.stats',{})
                self.transports.append(worker)
            fetchers=[]
            for route in bulk.get('clients',[]):
                records=EtpRecordSocket(self.transports[route['node']],route['hops'],bytes.fromhex(route['key']),route['scope'],max_record=60000)
                fetchers.append(BulkPeer(records).fetch)
            self.store.fetchers=tuple(fetchers)
            for route in bulk.get('sources',[]):
                records=EtpRecordSocket(self.transports[route['node']],route['hops'],bytes.fromhex(route['key']),route['scope'],server=True,max_record=60000)
                source=Store(config['objects'],config.get('dht_db'))
                thread=threading.Thread(target=serve_objects,args=(records,source,self.transport_stop),daemon=True)
                self.transport_threads.append(thread);thread.start()
        self.lock = threading.Lock()
        self.rate_key = os.urandom(32)
        with database(config['forum_db']) as db:
            db.execute('CREATE TABLE IF NOT EXISTS gateway_nonces (nonce TEXT PRIMARY KEY, author TEXT, ip TEXT, timestamp INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS gateway_outbox (id TEXT PRIMARY KEY, kind TEXT, topic TEXT, sent INTEGER DEFAULT 0)')
            columns={r[1] for r in db.execute('PRAGMA table_info(gateway_outbox)')}
            for name,definition in {'attempts':'INTEGER NOT NULL DEFAULT 0','retry_at':'INTEGER NOT NULL DEFAULT 0','last_error':'TEXT'}.items():
                if name not in columns:db.execute('ALTER TABLE gateway_outbox ADD COLUMN '+name+' '+definition)

    def chain_provenance(self):
        from .chain_provenance import snapshot
        try:return snapshot(self.config)
        except (OSError, ValueError, KeyError, __import__('sqlite3').Error):
            return {'schema':'ziokt.chain-provenance.v1','available':False,'source_protocol_activation_proved':False}

    def close(self):
        self.transport_stop.set()
        for thread in self.transport_threads:thread.join(timeout=12)
        for transport in self.transports:transport.close()

    def verify_native_source(self):
        from .config import fingerprint
        if not self.config.get('corix_digest') or fingerprint(Path(self.config['corix']))!=self.config['corix_digest']:
            raise ValueError('native source digest changed; redeploy reviewed gateway')

    def native_text(self,*args):
        self.verify_native_source()
        result=subprocess.run([str(ASSETS/'native.sh'),self.config['corix'],self.config['state_root'],self.config['network'],*args],check=True,timeout=60,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        if len(result.stdout)>262144:raise ValueError('native result budget')
        return result.stdout.decode('utf-8')

    def native(self, *args):
        self.verify_native_source()
        subprocess.run([str(ASSETS/'native.sh'), self.config['corix'], self.config['state_root'], self.config['network'], *args],
                       check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def rate_identity(self, ip):
        # Short-lived pseudonym for abuse control, never store the raw IP.
        return hmac.new(self.rate_key,str(ip).encode(),hashlib.sha256).hexdigest()

    def flush(self):
        now=int(time.time())
        with database(self.config['forum_db']) as db:
            db.execute('DELETE FROM gateway_nonces WHERE timestamp<?',(now-600,))
            rows = db.execute('SELECT id,kind,topic,attempts FROM gateway_outbox WHERE sent=0 AND retry_at<=? ORDER BY retry_at,id LIMIT 16',(now,)).fetchall()
        for digest, kind, topic, attempts in rows:
            try:
                self.native('announce', kind, digest, topic)
            except (OSError,ValueError,subprocess.SubprocessError) as exc:
                # Isolate a failed object; it must not starve healthy records.
                delay=min(300,2**min(attempts+1,8))
                with database(self.config['forum_db']) as db:
                    db.execute('UPDATE gateway_outbox SET attempts=MIN(attempts+1,32),retry_at=?,last_error=? WHERE id=?',(now+delay,type(exc).__name__,digest))
                continue
            with database(self.config['forum_db']) as db:
                db.execute('UPDATE gateway_outbox SET sent=1,last_error=NULL WHERE id=?', (digest,))
        with database(self.config['forum_db']) as db:
            db.execute('DELETE FROM gateway_outbox WHERE sent=1 AND id NOT IN (SELECT id FROM gateway_outbox WHERE sent=1 ORDER BY rowid DESC LIMIT 10000)')

    def submit(self, payload, ip):
        author = verify_client(payload, self.config['network'])
        ip = self.rate_identity(ip)
        now = int(time.time())
        content = payload['content'].encode()
        content_hash = hashlib.sha256(content).hexdigest()
        manifest = {**payload, 'version':'3.0', 'author':author, 'content_hash':content_hash,
                    'attachment_hash':'', 'attachment_name':'', 'associated_group_id':None}
        if payload['reply_to']: manifest['topic_id'] = payload['reply_to']
        raw = encoded(manifest)
        digest = hashlib.sha256(raw).hexdigest()
        with self.lock, sqlite3.connect(self.config['forum_db'], timeout=10) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM gateway_nonces WHERE timestamp<?', (now-600,))
            if db.execute('SELECT 1 FROM gateway_nonces WHERE nonce=?', (payload['nonce'],)).fetchone(): raise ValueError('replayed request')
            if db.execute('SELECT 1 FROM gateway_nonces WHERE (author=? OR ip=?) AND timestamp>?', (author,ip,now-300)).fetchone(): raise ValueError('rate limit: one post per five minutes')
            if db.execute('SELECT count(*) FROM gateway_nonces').fetchone()[0] >= 10000: raise ValueError('gateway busy')
            topic = payload['reply_to']
            if topic and not db.execute('SELECT 1 FROM topics WHERE id=?', (topic,)).fetchone(): raise ValueError('unknown topic')
            self.store.put(content)
            self.store.put(raw)
            # Native forum readers and recovery use the same object and manifest roots.
            objects = Path(self.config['forum_db']).parent/'objects'; objects.mkdir(exist_ok=True)
            manifests = Path(self.config['forum_db']).parent/'manifests'; manifests.mkdir(exist_ok=True)
            (objects/content_hash).write_bytes(content)
            (manifests/(digest+'.json')).write_bytes(raw)
            if topic:
                db.execute('INSERT INTO posts(id,topic_id,author,timestamp,signature,content_hash,attachment_hash,attachment_name) VALUES (?,?,?,?,?,?,?,?)',
                           (digest,topic,author,now,payload['signature'],content_hash,'',''))
            else:
                db.execute('INSERT INTO topics(id,title,author,timestamp,signature,content_hash,attachment_hash,attachment_name,associated_group_id) VALUES (?,?,?,?,?,?,?,?,?)',
                           (digest,payload['title'],author,now,payload['signature'],content_hash,'','',None))
            db.execute('INSERT INTO gateway_nonces VALUES (?,?,?,?)', (payload['nonce'],author,ip,now))
            db.execute('INSERT INTO gateway_outbox(id,kind,topic) VALUES (?,?,?)', (digest,'forum_post' if topic else 'forum_topic',topic))
        return digest


def handler(gateway):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def setup(self):
            super().setup(); self.connection.settimeout(15)
        def log_message(self, *args): pass  # Authorization and request bodies never enter logs.
        def send(self, status, data, mime='application/json'):
            raw = encoded(data) if not isinstance(data, bytes) else data
            self.send_response(status); self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Referrer-Policy','no-referrer')
            origin=self.headers.get('Origin')
            if origin in gateway.config.get('gui_origins',[]):
                self.send_header('Access-Control-Allow-Origin',origin);self.send_header('Vary','Origin')
                self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type, X-Ziokt-Auth')
            self.end_headers()
            if self.command != 'HEAD': self.wfile.write(raw)
        def check_gui_origin(self):
            origin=self.headers.get('Origin')
            host=self.headers.get('Host','')
            if origin and origin not in gateway.config.get('gui_origins',[]) and origin!='https://'+host and not (host.startswith(('127.0.0.1:', 'localhost:')) and origin=='http://'+host):
                from .gui_api import GuiError
                raise GuiError(403,'GUI origin rejected')
        def do_OPTIONS(self):
            from .gui_api import GuiError
            try:
                self.check_gui_origin()
                if urlsplit(self.path).path not in {'/api/gateway/tools','/api/gateway/tools/call'}:return self.send(404,{'error':'not found'})
                self.send(204,b'')
            except GuiError as exc:self.send(exc.status,{'error':str(exc)})
        def do_HEAD(self): self.do_GET()
        def do_GET(self):
            path = urlsplit(self.path).path
            try:
                if path == '/api/gateway/tools':
                    self.check_gui_origin()
                    from .gui_api import dispatch
                    return self.send(200, dispatch(gateway, self.headers.get('Authorization')))
                if path == '/api/gateway/public-address':
                    observation = gateway.public_address.observe()
                    return self.send(200 if observation['ok'] else 503, observation)
                if path == '/api/gateway/status':
                    from .assurance import snapshot as assurance_snapshot, public_hold
                    with database(gateway.config['forum_db']) as db:
                        pending = db.execute('SELECT count(*) FROM gateway_outbox WHERE sent=0').fetchone()[0]
                    return self.send(200, {'schema':'ziokt.gateway.v1','network':gateway.config['network'],'write':'client-ed25519-or-admin','pending_announcements':pending,'build':gateway.build_info,'native_entrypoint_digest':gateway.config.get('corix_digest'),'service_endpoints':gateway.service_endpoints,'assurance':assurance_snapshot(public_hold(gateway.config)), 'chain_provenance':gateway.chain_provenance()})
                if path == '/api/gateway/registrations':
                    from .registry import Registry
                    return self.send(200,Registry(gateway.config['registry_db'],gateway.config['network']).list())
                if path.startswith('/stream/'):

                    digest = path.removeprefix('/stream/')
                    manifest = gateway.store.manifest(digest)
                    size = manifest['size']
                    etag = '"'+digest+'"'
                    if self.headers.get('If-None-Match') == etag:
                        self.send_response(304); self.send_header('Content-Length','0'); self.end_headers(); return
                    requested = self.headers.get('Range')
                    if self.headers.get('If-Range',etag) != etag: requested = None
                    try: start, end = byte_range(requested,size)
                    except ValueError:
                        self.send_response(416); self.send_header('Content-Range',f'bytes */{size}'); self.send_header('Content-Length','0'); self.end_headers(); return
                    iterator = gateway.store.stream(manifest,start,end)
                    # Fail missing/corrupt first object before sending successful headers.
                    first = next(iterator, b'') if self.command != 'HEAD' else b''
                    self.send_response(206 if requested else 200)
                    self.send_header('Content-Type','application/octet-stream')
                    self.send_header('Content-Length',str(max(0,end-start+1)))
                    self.send_header('Accept-Ranges','bytes'); self.send_header('ETag',etag)
                    if requested: self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                    self.end_headers()
                    try:
                        if self.command != 'HEAD':
                            self.wfile.write(first)
                            for data in iterator: self.wfile.write(data)
                    except (OSError, ValueError): self.close_connection = True
                    finally: iterator.close()
                    return
                if path.startswith('/gateway-assets/'):
                    name = path.removeprefix('/gateway-assets/')
                    if name.startswith('gui/'):
                        gui_sub = name.removeprefix('gui/')
                        if '..' in gui_sub or Path(gui_sub).is_absolute(): return self.send(404,{'error':'not found'})
                        target_file = (ASSETS / 'gui' / gui_sub).resolve()
                        gui_root = (ASSETS / 'gui').resolve()
                        if not target_file.is_relative_to(gui_root) or not target_file.is_file():
                            return self.send(404,{'error':'not found'})
                        if name.endswith('.tar.gz') or name.endswith('.gz'): ctype = 'application/gzip'
                        elif name.endswith('.zip'): ctype = 'application/zip'
                        elif name.endswith('.apk') or name.endswith('.msi') or name.endswith('.dmg'): ctype = 'application/octet-stream'
                        elif name.endswith('.html'): ctype = 'text/html; charset=utf-8'
                        elif name.endswith('.json'): ctype = 'application/json'
                        elif name.endswith('.css'): ctype = 'text/css; charset=utf-8'
                        elif name.endswith('.svg'): ctype = 'image/svg+xml'
                        elif name.endswith('.png'): ctype = 'image/png'
                        else: ctype = 'text/javascript; charset=utf-8'
                        return self.send(200, target_file.read_bytes(), ctype)
                    if name not in ('gateway.js','i18n.json','media.js','mcp-console.js','oauth-callback.html','oauth-callback.js','registry.html','registry.js'): return self.send(404,{'error':'not found'})
                    return self.send(200,(ASSETS/name).read_bytes(),'application/json' if name.endswith('.json') else 'text/html; charset=utf-8' if name.endswith('.html') else 'text/javascript; charset=utf-8')
                return self.send(404,{'error':'not found'})
            except (ValueError, FileNotFoundError) as exc:
                from .gui_api import GuiError
                self.send(exc.status if isinstance(exc,GuiError) else 404,{'error':str(exc) if isinstance(exc,GuiError) else 'object unavailable'})
        def do_POST(self):
            path=urlsplit(self.path).path
            if path not in ('/api/gateway/forum','/api/gateway/registrations','/api/gateway/registrations/decide','/api/gateway/tools/call'):return self.send(404,{'error':'not found'})
            try:
                lengths = self.headers.get_all('Content-Length',[])
                if len(lengths)!=1 or not lengths[0].isdigit() or not 0<int(lengths[0])<=100000 or self.headers.get('Transfer-Encoding'):
                    self.close_connection=True; return self.send(413,{'error':'invalid request size'})
                if self.headers.get_content_type() != 'application/json': raise ValueError('JSON required')
                payload = json.loads(self.rfile.read(int(lengths[0])), object_pairs_hook=unique)
                auth = self.headers.get('Authorization','')
                if path == '/api/gateway/tools/call':
                    self.check_gui_origin()
                    from .gui_api import dispatch
                    return self.send(200,dispatch(gateway,auth,payload))
                if path.startswith('/api/gateway/registrations'):
                    from .registry import Registry
                    registry=Registry(gateway.config['registry_db'],gateway.config['network'])
                    if auth:
                        if not hmac.compare_digest(auth,'Bearer '+read_token(gateway.config['admin_token'])):return self.send(403,{'error':'authentication failed'})
                        if path.endswith('/decide'):
                            if not isinstance(payload,dict) or set(payload)!={'registration_id','digest','decision','confirm'} or payload['confirm'] is not True:raise ValueError('exact confirmed decision required')
                            return self.send(200,registry.decide('node-owner',payload['registration_id'],payload['digest'],payload['decision'],gateway.native_text))
                        return self.send(201,registry.submit('node-owner',payload))
                    if path.endswith('/decide'):return self.send(403,{'error':'owner approval required'})
                    fields={'schema','network','entry','public_key','timestamp','nonce','signature'}
                    if not isinstance(payload,dict) or set(payload)!=fields or payload['schema']!='ziokt.registry.v1' or payload['network']!=gateway.config['network']:raise ValueError('invalid signed request')
                    if type(payload['timestamp']) is not int or abs(int(time.time())-payload['timestamp'])>300:raise ValueError('expired request')
                    if not digest_ok(payload['nonce']) or not digest_ok(payload['public_key']) or not isinstance(payload['signature'],str) or len(payload['signature'])!=128:raise ValueError('invalid signer')
                    unsigned={k:v for k,v in payload.items() if k!='signature'}
                    Ed25519PublicKey.from_public_bytes(bytes.fromhex(payload['public_key'])).verify(bytes.fromhex(payload['signature']),encoded(unsigned))
                    registry.validate(payload['entry'])
                    author=hashlib.sha256(bytes.fromhex(payload['public_key'])).hexdigest()
                    with database(gateway.config['forum_db']) as db:
                        now=int(time.time());db.execute('DELETE FROM gateway_nonces WHERE timestamp<?',(now-600,))
                        ip=gateway.rate_identity(self.headers.get('X-Ziokt-Client-IP',self.client_address[0]))
                        if db.execute('SELECT count(*) FROM gateway_nonces WHERE (author=? OR ip=?) AND timestamp>?',(author,ip,now-300)).fetchone()[0]>=10:raise ValueError('rate limit')
                        db.execute('INSERT INTO gateway_nonces VALUES (?,?,?,?)',(payload['nonce'],author,ip,now))
                    return self.send(201,registry.submit(author,payload['entry']))
                # Every browser poster proves its own identity. Administrator
                # authentication never borrows the node's signing identity.
                digest = gateway.submit(payload,self.headers.get('X-Ziokt-Client-IP',self.client_address[0]))
                return self.send(201,{'id':digest,'identity':'client','announcement':'queued'})
            except Exception as exc:
                from .gui_api import GuiError
                from .mcp import McpError
                if isinstance(exc,GuiError):return self.send(exc.status,{'error':str(exc)})
                if isinstance(exc,McpError):return self.send(exc.status,{'error':exc.message})
                if path=='/api/gateway/tools/call' and isinstance(exc,ValueError):return self.send(400,{'error':'Tool arguments or idempotency key rejected'})
                from cryptography.exceptions import InvalidSignature
                if isinstance(exc,(ValueError,InvalidSignature,sqlite3.IntegrityError)):
                    return self.send(403,{'error':'write rejected: signature, replay, rate or content invalid'})
                return self.send(503,{'error':'native publication unavailable'})
    return Handler


def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('duplicate field')
        result[key]=value
    return result


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32
    def __init__(self,*args,**kwargs):
        if args and ':' in args[0][0]:self.address_family=socket.AF_INET6
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(*args,**kwargs)
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False): self.shutdown_request(request); return
        try: super().process_request(request,address)
        except BaseException: self.slots.release(); raise
    def process_request_thread(self,*args):
        try: super().process_request_thread(*args)
        finally: self.slots.release()


def serve(config):
    gateway=Gateway(config,transports=True)
    stop=threading.Event();dns_servers=[];dns_threads=[];server=None
    def relay():
        while not stop.is_set():
            try:gateway.flush()
            except (OSError,subprocess.SubprocessError,sqlite3.Error):pass
            stop.wait(10)
    worker=threading.Thread(target=relay,daemon=True);worker.start()
    try:
        if config.get('dns_config'):
            from .dns_server import load as load_dns,servers as open_dns
            dns_config,networks=load_dns(config['dns_config'])
            dns_servers=open_dns(networks,host=dns_config['listen'],port=dns_config.get('port',5353),doh_port=dns_config.get('doh_port',8188),dot_port=dns_config.get('dot_port'),doq_port=dns_config.get('doq_port'),doh3_port=dns_config.get('doh3_port'),tls_cert=dns_config.get('tls_cert'),tls_key=dns_config.get('tls_key'))
            for listener in dns_servers:
                thread=threading.Thread(target=listener.serve_forever,daemon=True);thread.start();dns_threads.append(thread)
        from .endpoint_config import local_listener
        server=Server((local_listener(config.get('listen','127.0.0.1')),config.get('port',8185)),handler(gateway))
        server.serve_forever()
    finally:
        stop.set()
        if server is not None:server.server_close()
        for listener in dns_servers:
            if hasattr(listener,'shutdown'):
                try:listener.shutdown()
                except Exception:pass
            listener.server_close()
        for thread in dns_threads:thread.join(2)
        worker.join(2);gateway.close()

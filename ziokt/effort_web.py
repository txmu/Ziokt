"""Opt-in public Engine Zero workers. All chain authority stays on the server."""
import argparse
import hashlib
import http.server
import ipaddress
from importlib.resources import files,files as files_resource
import os
from pathlib import Path
import secrets
import sqlite3
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit

from .client import NativeClient
from .config import load
from .protocol import ProtocolError, encoded, make_private, secure_read, strict_json
from .runtime_policy import require_network


class EffortPool:
    def __init__(self,client,submitter,state,*,expected_network=None):
        if not isinstance(submitter,str) or len(submitter)!=64 or any(c not in '0123456789abcdef' for c in submitter):raise ProtocolError('INVALID_CONFIG','fixed Corium node contribution address required')
        if expected_network is not None and (not isinstance(expected_network,str) or not expected_network or len(expected_network)>64 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in expected_network)):raise ProtocolError('INVALID_CONFIG','explicit Corium network identifier required')
        self.client=client;self.submitter=submitter;self.expected_network=expected_network;self.lock=threading.RLock();self.jobs={};self.cache=None;self.cached_at=0
        state=Path(state)
        if not state.is_absolute() or '..' in state.parts or state.is_symlink():raise ProtocolError('UNSAFE_FILE','private absolute effort state directory required')
        state.mkdir(mode=0o700,parents=True,exist_ok=True);make_private(state)
        file=state/'effort.sqlite'
        try:fd=os.open(file,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600);os.close(fd)
        except FileExistsError:pass
        secure_read(file,16*1024*1024)
        self.db=sqlite3.connect(file,check_same_thread=False);self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS submissions (problem TEXT PRIMARY KEY,operation TEXT NOT NULL,nonce TEXT NOT NULL,result BLOB)');self.db.commit()

    def close(self):self.db.close()

    def recover(self,problem,operation):
        """Resume a durable intent without confusing prepare with execution."""
        result=self.client.call('operation.reconcile',{'operation_id':operation})
        if result.get('state')=='prepared':
            try:
                result=self.client.call('operation.commit',{'operation_id':operation,'plan_digest':result['plan_digest']})
            except ProtocolError as exc:
                if exc.code!='STALE_PLAN':raise
                # Native commit did not claim this prepared intent. Abort it before
                # allowing another operation; unknown execution is never retried.
                result=self.client.call('operation.abort',{'operation_id':operation,'plan_digest':result['plan_digest']})
        if result.get('state')=='aborted':
            with self.db:self.db.execute('DELETE FROM submissions WHERE problem=? AND operation=? AND result IS NULL',(problem,operation))
        elif result.get('state')=='committed':
            receipt={'accepted':True,'phase':result['result']['phase'],'transaction_hash':result['result']['transaction_hash'],'confirmed':False}
            with self.db:self.db.execute('UPDATE submissions SET result=? WHERE problem=? AND operation=?',(encoded(receipt),problem,operation))
            self.cache=None
        return result

    def issue(self):
        require_network()
        with self.lock:
            # Reconcile an interrupted native commit without issuing another transaction.
            pending=self.db.execute('SELECT problem,operation FROM submissions WHERE result IS NULL LIMIT 1').fetchone()
            if pending:
                self.recover(pending[0],pending[1])
            now=time.time()
            self.jobs={key:value for key,value in self.jobs.items() if value['expires']>now}
            if len(self.jobs)>=1024:raise ProtocolError('BACKPRESSURE','worker job budget is full')
            if self.cache is None or now-self.cached_at>=2:
                self.cache=self.client.call('compute.challenge',{});self.cached_at=now
            value=self.cache
            if not isinstance(value,dict) or (self.expected_network is not None and value.get('network_id')!=self.expected_network):raise ProtocolError('NETWORK_MISMATCH','native compute challenge does not match configured mainnet')
            if value['submitter_id']!=self.submitter:raise ProtocolError('SCOPE_MISMATCH','configured contribution address differs from the Corium signer')
            if not value['available']:return {'available':False,'retry_ms':5000}
            token=secrets.token_hex(24);start=secrets.randbits(48)
            job={**value,'token':token,'start':str(start),'limit':1000000,'expires':int(now)+90,'batch':64,'pause_ms':40}
            self.jobs[token]=job
            return {**job,'available':True}

    def submit(self,token,nonce):
        require_network()
        with self.lock:
            if not isinstance(token,str) or not isinstance(nonce,str) or not nonce.isascii() or not nonce.isdecimal() or len(nonce)>20 or str(int(nonce))!=nonce:raise ProtocolError('INVALID_PROOF','bounded decimal proof required')
            job=self.jobs.get(token)
            if not job or job['expires']<=time.time():raise ProtocolError('STALE_JOB','worker job expired')
            start=int(job['start'])
            if not start<=int(nonce)<start+job['limit']:raise ProtocolError('INVALID_PROOF','nonce is outside assigned work range')
            digest=hashlib.sha256((job['network_id']+self.submitter+nonce+job['problem_id']).encode()).hexdigest()
            if not digest.startswith('000'):raise ProtocolError('INVALID_PROOF','Engine Zero proof verification failed')
            problem=job['problem_id'];op='web-zero-'+hashlib.sha256((job['network_id']+self.submitter+problem).encode()).hexdigest()[:42]+'-'+secrets.token_hex(6)
            row=self.db.execute('SELECT operation,nonce,result FROM submissions WHERE problem=?',(problem,)).fetchone()
            if row and row[2]:return {**strict_json(row[2]),'duplicate':True}
            if row:
                # The native durable operation journal resolves any interrupted commit.
                result=self.recover(problem,row[0])
            else:
                plan=self.client.call('operation.prepare',{'operation_id':op,'action':'compute.submit','resource':'compute:corium/internal-engine-zero-v1','arguments':{'problem_id':problem,'nonce':nonce},'expected_revision':None})
                with self.db:
                    self.db.execute('INSERT INTO submissions VALUES (?,?,?,NULL)',(problem,op,nonce))
                result=self.client.call('operation.commit',{'operation_id':op,'plan_digest':plan['plan_digest']})
            if result.get('state')!='committed':raise ProtocolError('RESULT_UNKNOWN','proof submission awaits native reconciliation')
            receipt={'accepted':True,'phase':result['result']['phase'],'transaction_hash':result['result']['transaction_hash'],'confirmed':False}
            with self.db:
                self.db.execute('UPDATE submissions SET result=? WHERE problem=?',(encoded(receipt),problem))
                self.db.execute('DELETE FROM submissions WHERE rowid IN (SELECT rowid FROM submissions WHERE result IS NOT NULL ORDER BY rowid DESC LIMIT -1 OFFSET 2048)')
            self.cache=None
            return {**receipt,'duplicate':False}


def effort_server(pool,origin,*,host='127.0.0.1',port=0,explorer=None,relay_origins=(),direct_relay=None):
    require_network()
    origins = [origin] if isinstance(origin, str) else list(origin)
    for o in origins:
        p = urlsplit(o)
        if p.scheme not in {'http','https'} or not p.netloc or p.username or p.password or p.path or p.query or p.fragment:raise ProtocolError('INVALID_CONFIG','exact public origin required')
        if p.scheme=='http' and p.hostname not in {'127.0.0.1','localhost','::1'}:raise ProtocolError('INVALID_CONFIG','public workers require HTTPS')
    allowed_hosts = {urlsplit(o).netloc for o in origins}
    allowed_origin_strs = set(origins)
    if not isinstance(relay_origins,(list,tuple)) or len(relay_origins)>8:raise ProtocolError('INVALID_CONFIG','bounded approved collaboration origins required')
    for item in relay_origins:
        from .relay_web import approved_origin
        try:approved_origin(item)
        except ValueError:raise ProtocolError('INVALID_CONFIG','exact HTTPS or loopback collaboration origin required') from None
    connect_sources=' '.join(["'self'"]+list(relay_origins))
    assets=files('ziokt').joinpath('effort');workers=threading.BoundedSemaphore(16);rates={};rate_lock=threading.Lock()
    class Handler(http.server.BaseHTTPRequestHandler):
        def setup(self):super().setup();self.connection.settimeout(35)
        def log_message(self,*_):pass
        def send_value(self,status,value,kind='application/json'):
            data=value if isinstance(value,bytes) else encoded(value)
            self.send_response_only(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)))
            for key,val in {'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'none'; script-src 'self'; worker-src 'self'; style-src 'self'; connect-src "+connect_sources+"; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",'Cross-Origin-Resource-Policy':'same-origin','Permissions-Policy':'camera=(),microphone=(),geolocation=()','Connection':'close'}.items():self.send_header(key,val)
            self.end_headers();self.wfile.write(data)
        def valid_origin(self,post=False):
            # Public GETs are read-only, including navigation from WeChat or an
            # external site. Fetch Metadata describes the navigation initiator,
            # not permission to view a public document. Host pinning, CSP, CORP
            # and absence of CORS remain in force; writes require exact origin.
            host = self.headers.get('Host')
            if host and host not in allowed_hosts:
                raise ProtocolError('ORIGIN_REJECTED','configured public host required')
            if post:
                sites = self.headers.get_all('Sec-Fetch-Site', [])
                if sites and (len(sites) != 1 or sites[0] not in {'same-origin', 'none'}):
                    raise ProtocolError('ORIGIN_REJECTED','cross-site worker mutations rejected')
                req_origin = self.headers.get('Origin')
                if req_origin and req_origin not in allowed_origin_strs:
                    raise ProtocolError('ORIGIN_REJECTED','same-origin worker requests required')
        def rate(self,scope,maximum):
            with rate_lock:
                now=int(time.time()//60);key=(scope,self.client_address[0])
                for old in [k for k,v in rates.items() if v[0]!=now]:del rates[old]
                previous=rates.get(key,(now,0))
                if previous[1]>=maximum or len(rates)>=4096 and key not in rates:raise ProtocolError('BACKPRESSURE','request rate exceeded')
                rates[key]=(now,previous[1]+1)
        def do_GET(self):
            try:
                self.valid_origin()
                if self.path=='/api/people/config':return self.send_value(200,{'schema':'ziokt.people-help.v1','relay_origins':list(relay_origins),'direct_relay':{'enabled':direct_relay is not None,'network_id':direct_relay.network if direct_relay else None,'transport':'direct','anonymous':False}})
                if explorer is not None and self.path.startswith('/api/explorer/'):
                    self.rate('explorer',600)
                    return self.send_value(200,explorer.query(self.path))
                if explorer is not None and self.path in {'/explorer','/explorer/','/explorer/app.js','/explorer/style.css'}:
                    name,kind=('index.html','text/html; charset=utf-8') if self.path in {'/explorer','/explorer/'} else ('app.js','text/javascript') if self.path.endswith('app.js') else ('style.css','text/css')
                    return self.send_value(200,files_resource('ziokt').joinpath('explorer',name).read_bytes(),kind)
                files={'/':('index.html','text/html; charset=utf-8'),'/relay.js':('relay.js','text/javascript'),'/geography.js':('geography.js','text/javascript'),'/app.js':('app.js','text/javascript'),'/worker.js':('worker.js','text/javascript'),'/profiles.js':('profiles.js','text/javascript'),'/style.css':('style.css','text/css')}
                if self.path not in files:return self.send_value(404,{'error':'NOT_FOUND'})
                name,kind=files[self.path];self.send_value(200,assets.joinpath(name).read_bytes(),kind)
            except ProtocolError as exc:self.send_value(404 if exc.code=='NOT_FOUND' else 429 if exc.code=='BACKPRESSURE' else 503 if exc.code=='CHAIN_UNAVAILABLE' else 403 if exc.code=='ORIGIN_REJECTED' else 400,{'error':exc.code})
            except (OSError,ValueError,TypeError):self.send_value(503,{'error':'CHAIN_UNAVAILABLE'})
        def do_POST(self):
            try:
                self.valid_origin(True)
                if self.headers.get('Transfer-Encoding') is not None or self.headers.get('Content-Type')!='application/json':raise ProtocolError('INVALID_REQUEST','bounded JSON required')
                length=self.headers.get('Content-Length','')
                limit=8192 if self.path.startswith('/api/people/direct/') else 2048
                if not length.isdecimal() or not 1<=int(length)<=limit:raise ProtocolError('REQUEST_LIMIT','worker request exceeds budget')
                self.rate('direct' if self.path.startswith('/api/people/direct/') else 'worker',1200 if self.path.startswith('/api/people/direct/') else 120)
                value=strict_json(self.rfile.read(int(length)),limit)
                if self.path.startswith('/api/people/direct/'):
                    if direct_relay is None:raise ProtocolError('NATIVE_UNAVAILABLE','mainnet direct relay is not configured')
                    if self.headers.get('Origin') not in allowed_origin_strs:raise ProtocolError('ORIGIN_REJECTED','exact origin required for direct relay')
                    tail=self.path[len('/api/people/direct/'):].split('/')
                    if isinstance(value,dict) and set(value)=={'arguments','padding'}:
                        if not isinstance(value['padding'],str) or any(c!='0' for c in value['padding']):raise ProtocolError('INVALID_REQUEST','canonical bounded padding required')
                        value=value['arguments']
                    if tail==['open']:result=direct_relay.call(None,'open',value)
                    elif len(tail)==2:result=direct_relay.call(tail[0],tail[1],value,self.headers.get('Authorization'))
                    else:raise ProtocolError('NOT_FOUND','fixed direct relay operation required')
                elif self.path=='/api/job' and value=={}:result=pool.issue()
                elif self.path=='/api/proof' and isinstance(value,dict) and set(value)=={'token','nonce'}:result=pool.submit(value['token'],value['nonce'])
                else:raise ProtocolError('INVALID_REQUEST','fixed worker endpoint required')
                self.send_value(200,result)
            except ProtocolError as exc:self.send_value(429 if exc.code=='BACKPRESSURE' else 409,{'error':exc.code})
            except (OSError,ValueError,KeyError,TypeError):self.send_value(503,{'error':'NATIVE_UNAVAILABLE'})
    class Server(http.server.ThreadingHTTPServer):
        daemon_threads=True
        def process_request(self,request,address):
            if not workers.acquire(False):request.close();return
            try:super().process_request(request,address)
            except BaseException:workers.release();raise
        def process_request_thread(self,request,address):
            try:super().process_request_thread(request,address)
            finally:workers.release()
        def handle_error(self,*_):pass
    Server.address_family=socket.AF_INET6 if ":" in host else socket.AF_INET
    return Server((host,port),Handler)


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);args=parser.parse_args(argv)
    require_network();config=strict_json(secure_read(args.config))
    required={'schema','origin','listen','port','federation_config','provider','network_id','submitter','state_root'}
    if not isinstance(config,dict) or not required<=set(config) or set(config)-required-{'certificate','private_key','explorer','relay_origins','direct_relay'} or config['schema']!='ziokt.effort-web.v1' or type(config['port']) is not int or not 1<=config['port']<=65535:raise ProtocolError('INVALID_CONFIG','exact effort web configuration required')
    if not isinstance(config['network_id'],str) or not config['network_id'] or len(config['network_id'])>64 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in config['network_id']):raise ProtocolError('INVALID_CONFIG','explicit Corium mainnet identifier required')
    if type(config.get('explorer',False)) is not bool:raise ProtocolError('INVALID_CONFIG','boolean explorer setting required')
    if not isinstance(config['listen'],str):raise ProtocolError('INVALID_CONFIG','literal listening address required')
    address=ipaddress.ip_address(config['listen'])
    tls='certificate' in config or 'private_key' in config
    if not address.is_loopback and not tls:raise ProtocolError('INVALID_CONFIG','non-loopback listener requires server TLS')
    federation=load(config['federation_config'])
    provider=next((p for p in federation['providers'] if p['native_project']=='corium' and p['provider_id']==config['provider']),None)
    if not federation['enabled'] or provider is None or provider.get('network_id')!=config['network_id']:raise ProtocolError('NETWORK_MISMATCH','enabled Corium provider must match the explicitly configured mainnet')
    client=NativeClient(federation['federation_id'],provider);client.health();pool=EffortPool(client,config['submitter'],config['state_root'],expected_network=config['network_id'])
    direct_relay=None
    try:
        # Refuse to open the web listener until the configured native chain is ready.
        from .explorer import ChainExplorer
        explorer=ChainExplorer(provider['state_root'],provider['network_id']) if config.get('explorer',False) else None
        from .effort_direct import DirectRelay
        direct_relay=DirectRelay(config['direct_relay'],config['network_id']) if 'direct_relay' in config else None
        pool.issue();server=effort_server(pool,config['origin'],host=config['listen'],port=config['port'],explorer=explorer,relay_origins=config.get('relay_origins',[]),direct_relay=direct_relay)
        try:
            if tls:
                if not {'certificate','private_key'}<=set(config) or urlsplit(config['origin']).scheme!='https':raise ProtocolError('INVALID_CONFIG','complete HTTPS credentials required')
                secure_read(config['private_key'],65536);secure_read(config['certificate'],65536,private=None)
                context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2;context.load_cert_chain(config['certificate'],config['private_key']);server.socket=context.wrap_socket(server.socket,server_side=True,do_handshake_on_connect=False)
            print(encoded({'event':'ziokt.effort-ready','origin':config['origin']}).decode(),flush=True)
            server.serve_forever()
        except KeyboardInterrupt:pass
        finally:
            server.server_close()
    finally:
        if direct_relay is not None:direct_relay.close()
        pool.close()

if __name__=='__main__':main()

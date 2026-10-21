"""Bounded application HTTP service, with a separate permission domain from Gateway.

Start: python -m ziokt.content_server --config /absolute/private/config.json
TLS required outside loopback. No arbitrary remote endpoint arguments accepted.
"""
import argparse
import base64
import hashlib
import hmac
import http.server
import json
import re
from pathlib import Path
import secrets
import socketserver
import ssl
import threading
import time
from urllib.parse import urlsplit,parse_qs
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

from .content_fabric import Fabric, ident, merkle_verify
from .content_api import invoke, OPERATIONS, ADMIN_OPERATIONS
from .protocol import encoded, secure_read, strict_json
from .security import sign, verify
from .gateway_store import byte_range
from .chunkstore import CHUNK_BYTES

TRANSPORT_DOMAIN='Ziokt/ContentFabric/transport/v1'
PUBLIC_READ_OPERATIONS={
    'applications.capabilities','library.search','library.get','library.extract',
    'netnews.groups','netnews.articles','netnews.search','netnews.get',
    'content.object.info','content.object.get','content.object.verify','feeds.describe',
}


class RateLimited(ValueError):pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('redirect rejected')


def remote(peer, payload):
    endpoint=peer['url']
    url=urlsplit(endpoint)
    if url.scheme not in {'https','http'} or url.username or url.password or url.query or url.fragment:raise ValueError('peer URL')
    if url.scheme!='https' and url.hostname not in {'127.0.0.1','::1','localhost'}:raise ValueError('TLS required')
    context=ssl.create_default_context(cafile=peer.get('ca'))
    opener=build_opener(NoRedirect(),HTTPSHandler(context=context))
    headers={'Content-Type':'application/json'}
    if peer.get('token'):headers['Authorization']='Bearer '+peer['token']
    request=Request(endpoint.rstrip('/')+'/api',data=encoded(payload),headers=headers,method='POST')
    with opener.open(request,timeout=15) as response:
        raw=response.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError('remote response budget')
        return strict_json(raw,1024*1024,string_limit=65536)


def sync(fabric, alias, peers):
    """Durable incremental pull; retries are idempotent, relay loops deduplicate."""
    peer=peers[alias];key=peer['public_key']
    with fabric.lock:
        row=fabric.db.execute('SELECT cursor FROM cursors WHERE peer=?',(alias,)).fetchone()
    cursor=row[0] if row else 0
    challenge=secrets.token_hex(24)
    envelope=remote(peer,{'operation':'federation.export','arguments':{'after':cursor,'challenge':challenge}})
    page=verify(envelope,key,TRANSPORT_DOMAIN,maximum=1024*1024)
    if page.get('challenge')!=challenge or page.get('node')!=key or type(page.get('cursor')) is not int or page['cursor']<cursor:raise ValueError('sync response')
    result=fabric.ingest(page['events'])
    with fabric.transaction():fabric.db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?)',(alias,page['cursor']))
    return {**result,'cursor':page['cursor'],'has_more':len(page['events'])==8}


def download(fabric, owner, book, sources, peers, *, max_chunks=128):
    with fabric.lock:record=fabric._get(owner,book,'book')
    return _download_object(fabric,owner,record['file'],record['file_id'],sources,peers,max_chunks=max_chunks)


def download_attachment(fabric,owner,article,oid,sources,peers,*,max_chunks=128):
    with fabric.lock:record=fabric._get(owner,article,'article')
    attachment=next((entry for entry in record.get('attachments',[]) if entry['id']==oid),None)
    if attachment is None:raise PermissionError('article attachment unavailable')
    return _download_object(fabric,owner,attachment,oid,sources,peers,max_chunks=max_chunks,application='netnews')


def _download_object(fabric,owner,meta,oid,sources,peers,*,max_chunks=128,application='library'):
    """Bounded sparse download, pinned sources, Merkle proofs and final digest."""
    if not isinstance(sources,list) or not 1<=len(sources)<=8 or any(s not in peers for s in sources):raise ValueError('configured sources required')
    if type(max_chunks) is not int or not 1<=max_chunks<=1024:raise ValueError('download budget')
    job=hashlib.sha256((owner+'\0'+oid).encode()).hexdigest()
    upload='download-'+job[:48]
    fabric.begin(owner,upload,meta['size'],meta['digest'],meta['mime'])
    with fabric.transaction():
        fabric.db.execute('INSERT OR IGNORE INTO downloads(id,owner,remote,upload,metadata,state) VALUES(?,?,?,?,?,?)',(job,owner,oid,upload,encoded(meta),'running'))
    profile=fabric.optimizations.get(owner,application)['effective']
    with fabric.lock:
        state=fabric.db.execute('SELECT state FROM downloads WHERE id=? AND owner=?',(job,owner)).fetchone()
        if state and state[0]=='paused':return {'job':job,'state':'paused'}
        with fabric.store(owner) as store:
            received={row[0] for row in store.db.execute('SELECT position FROM parts WHERE upload=?',(upload,))}
    positions=[i for i in range((meta['size']+CHUNK_BYTES-1)//CHUNK_BYTES) if i not in received][:max_chunks]
    if fabric.upload_status(owner,upload)['state']=='complete':positions=[]
    ordered=list(sources)
    if profile['transfer_prefer_verified_sources']:
        with fabric.lock:
            scores={row['alias']:row['successes'] for row in fabric.db.execute('SELECT alias,successes FROM source_health')}
        ordered.sort(key=lambda alias:-scores.get(alias,0))
    def fetch_one(position):
        failures=[]
        for alias in ordered:
            with fabric.lock:health=fabric.db.execute('SELECT quarantined_until FROM source_health WHERE alias=?',(alias,)).fetchone()
            if health and health[0]>time.time():
                failures.append({'source':alias,'error':'temporarily_quarantined'});continue
            for attempt in range(profile['transfer_retries']+1):
                try:
                    result=remote(peers[alias],{'operation':'content.object.get','arguments':{'id':oid,'position':position}})
                    data=base64.b64decode(result['data'],validate=True)
                    merkle_verify(data,position,result['proof'],meta['merkle_root'])
                    with fabric.transaction():fabric.db.execute('INSERT INTO source_health VALUES(?,1,0,0,?) ON CONFLICT(alias) DO UPDATE SET successes=successes+1,verified=excluded.verified,quarantined_until=0',(alias,int(time.time())))
                    return position,data,failures
                except (OSError,ValueError,KeyError,PermissionError) as exc:
                    failures.append({'source':alias,'error':type(exc).__name__})
                    with fabric.transaction():fabric.db.execute('INSERT INTO source_health VALUES(?,0,1,?,0) ON CONFLICT(alias) DO UPDATE SET failures=failures+1,quarantined_until=excluded.quarantined_until',(alias,int(time.time())+profile['transfer_quarantine_seconds']))
        return position,None,failures
    failures=[]
    from concurrent.futures import ThreadPoolExecutor
    # At most four chunks in flight; account database writes remain serialized.
    with ThreadPoolExecutor(max_workers=profile['transfer_parallelism']) as pool:
        for start in range(0,len(positions),profile['transfer_parallelism']):
            futures=[pool.submit(fetch_one,position) for position in positions[start:start+profile['transfer_parallelism']]]
            for future in futures:
                position,data,issues=future.result();failures.extend(issues)
                with fabric.lock:state=fabric.db.execute('SELECT state FROM downloads WHERE id=? AND owner=?',(job,owner)).fetchone()[0]
                if state=='paused':return {'job':job,'state':'paused'}
                if data is not None:fabric.put(owner,upload,position,data)
    status=fabric.upload_status(owner,upload)
    if status['next_missing']>=status['total_chunks']:
        result=fabric.finish(owner,upload)
        with fabric.transaction():
            fabric.db.execute('INSERT OR REPLACE INTO locations VALUES(?,?,?,?)',(oid,result['id'],owner,int(time.time())))
            fabric.db.execute("UPDATE downloads SET state='complete',error='' WHERE id=?",(job,))
        return {'job':job,'state':'complete','object':result,'verified':True}
    state='waiting' if failures and any(issue['error']!='temporarily_quarantined' for issue in failures) else 'running'
    with fabric.transaction():fabric.db.execute('UPDATE downloads SET state=?,error=? WHERE id=?',(state,'some sources unavailable' if failures else '',job))
    return {'job':job,'state':state,'received_chunks':status['received_chunks'],'total_chunks':status['total_chunks'],'failures':failures[-8:]}


class BoundedHTTP(http.server.ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=32
    def __init__(self,*args,**kwargs):
        self.slots=threading.BoundedSemaphore(16)
        super().__init__(*args,**kwargs)
    def process_request(self,request,client_address):
        if not self.slots.acquire(False):self.shutdown_request(request);return
        try:super().process_request(request,client_address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,client_address):
        try:super().process_request_thread(request,client_address)
        finally:self.slots.release()


def server(fabric, config):
    tokens=config.get('tokens',[])
    peers=config.get('peers',{})
    fabric.remote_peers=peers
    fabric.tc16_legacy_compiler=config.get('tc16_legacy_compiler')
    fabric.community_config=config.get('community',{})
    fabric.feed_base_url=config.get('feed_base_url','')
    rate_lock=threading.Lock();rates={}
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def setup(self):super().setup();self.connection.settimeout(15)
        def log_message(self,*args):pass
        def send(self,status,data,mime='application/json',extra=None):
            raw=data if isinstance(data,bytes) else encoded(data)
            self.send_response(status)
            self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control',(extra or {}).get('Cache-Control','no-store'));self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.send_header('Referrer-Policy','no-referrer')
            origin=self.headers.get('Origin')
            if origin in config.get('origins',[]) or (config.get('allow_webextensions') is True and isinstance(origin,str) and re.fullmatch(r'(?:chrome-extension://[a-p]{32}|moz-extension://[a-f0-9-]{36})',origin)):
                self.send_header('Access-Control-Allow-Origin',origin);self.send_header('Vary','Origin')
                self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type')
            for k,v in (extra or {}).items():
                if k!='Cache-Control':self.send_header(k,v)
            self.end_headers()
            if self.command!='HEAD':self.wfile.write(raw)
        def admit(self,principal):
            with rate_lock:
                now=int(time.time())//60;key=principal['account'];previous,count=rates.get(key,(now,0));count=count+1 if previous==now else 1;rates[key]=(now,count)
                if count>1200:raise RateLimited('request rate')
        def principal(self,feed_auth=False):
            auth=self.headers.get('Authorization','')
            for entry in tokens:
                if hmac.compare_digest(auth,'Bearer '+entry['token']):return entry
            if feed_auth and auth.startswith('Basic ') and len(auth)<4096:
                try:user,password=base64.b64decode(auth[6:],validate=True).decode('ascii').split(':',1)
                except (ValueError,UnicodeError):raise PermissionError('feed authentication')
                for entry in tokens:
                    if hmac.compare_digest(user,entry['account']) and hmac.compare_digest(password,entry['token']):return entry
            if not auth and config.get('public_read') is True:
                return {'account':'@anonymous','scopes':['applications:read','library:read','netnews:read','content:read','feeds:read'],'public':True}
            raise PermissionError('authentication required')
        def origin(self):
            origin=self.headers.get('Origin')
            # No CORS grants. Browsers cannot reuse a Gateway administrator credential.
            scheme='https' if config.get('tls') else 'http'
            port=self.server.server_port
            local_hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
            configured=set(config.get('origins',[]))
            hosts=local_hosts|{urlsplit(value).netloc for value in configured}
            if self.headers.get('Host') not in hosts:raise PermissionError('host denied')
            allowed=configured|{scheme+'://'+host for host in local_hosts}
            extension_allowed=config.get('allow_webextensions') is True and isinstance(origin,str) and re.fullmatch(r'(?:chrome-extension://[a-p]{32}|moz-extension://[a-f0-9-]{36})',origin)
            if origin and origin not in allowed and not extension_allowed:raise PermissionError('origin denied')
        def do_OPTIONS(self):
            try:
                self.origin()
                if self.path!='/api':return self.send(404,b'')
                self.send(204,b'')
            except PermissionError:self.send(403,b'')
        def do_HEAD(self):self.do_GET()
        def do_GET(self):
            try:
                path=urlsplit(self.path).path
                if path in {'/','/content.js','/content.css','/application-client.js'}:
                    name={'/':'content.html','/content.js':'content.js','/content.css':'content.css','/application-client.js':'application-client.js'}[path]
                    mime={'content.html':'text/html; charset=utf-8','content.js':'text/javascript','content.css':'text/css','application-client.js':'text/javascript'}[name]
                    return self.send(200,(Path(__file__).parent/'web'/name).read_bytes(),mime)
                if path.startswith('/feeds/'):
                    self.origin();principal=self.principal(feed_auth=True);self.admit(principal)
                    from .content_feeds import render,describe,opml
                    base=config.get('feed_base_url') or next((origin for origin in config.get('origins',[]) if urlsplit(origin).netloc==self.headers.get('Host')),None)
                    if not base:base=('https' if config.get('tls') else 'http')+'://'+self.headers['Host']
                    if path=='/feeds/index.json':return self.send(200,describe(base))
                    if path=='/feeds/subscriptions.opml':
                        if 'feeds:read' not in principal['scopes'] and 'netnews:read' not in principal['scopes']:raise PermissionError('subscription scope')
                        return self.send(200,opml(fabric,principal['account'],base),'text/x-opml; charset=utf-8')
                    match=re.fullmatch(r'/feeds/(all|library|netnews|community)\.(rss|atom|json)',path)
                    if not match:return self.send(404,{'error':'unknown feed'})
                    source,fmt=match.groups();scopes=set(principal['scopes'])
                    required={'library:read','netnews:read'} if source=='all' else {('community' if source=='community' else source)+':read'}
                    if 'feeds:read' not in scopes and not required<=scopes:raise PermissionError('feed scope')
                    if source in {'all','community'} and principal.get('public') and source=='community':raise PermissionError('private native delegation required')
                    query=parse_qs(urlsplit(self.path).query,keep_blank_values=True,max_num_fields=4)
                    if set(query)-{'group','limit','offset'} or any(len(values)!=1 for values in query.values()):raise ValueError('feed query')
                    output,mime,etag=render(fabric,principal['account'],base,source,fmt,query.get('group',[''])[0],int(query.get('limit',['30'])[0]),int(query.get('offset',['0'])[0]),include_community=('feeds:read' in scopes or 'community:read' in scopes))
                    headers={'ETag':etag,'Vary':'Authorization, Origin','Cache-Control':'public, max-age=60' if principal.get('public') else 'private, no-store'}
                    if self.headers.get('If-None-Match')==etag:return self.send(304,b'',mime,headers)
                    return self.send(200,output,mime,headers)
                if path.startswith('/objects/'):
                    self.origin();principal=self.principal();self.admit(principal)
                    if 'content:read' not in principal['scopes']:raise PermissionError('scope')
                    oid=path.removeprefix('/objects/')
                    with fabric.lock:
                        row=fabric.object_info(principal['account'],oid);meta=json.loads(row['metadata'])
                    if meta['size']==0:
                        if self.headers.get('Range'):return self.send(416,b'',extra={'Content-Range':'bytes */0'})
                        return self.send(200,b'','application/octet-stream',{'Accept-Ranges':'bytes'})
                    try:start,end=byte_range(self.headers.get('Range'),meta['size'])
                    except ValueError:return self.send(416,b'',extra={'Content-Range':f"bytes */{meta['size']}"})
                    if meta['size']==0:return self.send(200,b'','application/octet-stream',{'Accept-Ranges':'bytes'})
                    # Verify requested chunks before headers, then stream; no full-file buffer.
                    first=fabric.read_chunk(principal['account'],oid,start//CHUNK_BYTES)
                    ranged=bool(self.headers.get('Range'))
                    self.send_response(206 if ranged else 200)
                    self.send_header('Content-Type','application/octet-stream')
                    self.send_header('Content-Disposition','attachment; filename="ziokt-content.bin"')
                    self.send_header('X-Content-Type-Options','nosniff')
                    self.send_header('Cache-Control','no-store')
                    self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
                    if ranged:self.send_header('Content-Range',f"bytes {start}-{end}/{meta['size']}")
                    self.end_headers()
                    if self.command=='HEAD':return
                    try:
                        for position in range(start//CHUNK_BYTES,end//CHUNK_BYTES+1):
                            part=first if position==start//CHUNK_BYTES else fabric.read_chunk(principal['account'],oid,position)
                            lo=max(0,start-position*CHUNK_BYTES);hi=min(len(part),end-position*CHUNK_BYTES+1)
                            self.wfile.write(part[lo:hi])
                    except (OSError,ValueError,PermissionError):self.close_connection=True
                    return
                self.send(404,{'error':'not found'})
            except RateLimited:self.send(429,{'error':'request rate exceeded'},extra={'Retry-After':'60'})
            except PermissionError:self.send(403,{'error':'access denied'})
            except (ValueError,KeyError):self.send(400,{'error':'invalid request'})
            except Exception:self.close_connection=True;self.send(503,{'error':'read failed; inspect node state'})
        def do_POST(self):
            try:
                if self.path!='/api':self.close_connection=True;return self.send(404,{'error':'not found'})
                self.origin();principal=self.principal()
                self.admit(principal)
                if self.headers.get('Transfer-Encoding'):raise ValueError('transfer encoding unsupported')
                lengths=self.headers.get_all('Content-Length',[])
                if len(lengths)!=1:raise ValueError('content length required')
                size=int(lengths[0])
                if not 0<size<=131072:raise ValueError('request budget')
                payload=strict_json(self.rfile.read(size),131072,string_limit=65536)
                if set(payload)!={'operation','arguments'}:raise ValueError('request envelope')
                op,args=payload['operation'],payload['arguments']
                scopes=principal['scopes'];owner=principal['account']
                if principal.get('public') and op not in PUBLIC_READ_OPERATIONS:raise PermissionError('public identity is read-only')
                if op=='federation.export':
                    if 'content:replicate' not in scopes:raise PermissionError('peer grant')
                    if not isinstance(args,dict) or set(args)!={'after','challenge'}:raise ValueError('export fields')
                    ident(args['challenge'])
                    result=sign({**fabric.export(args['after'],8),'challenge':args['challenge']},fabric.key,TRANSPORT_DOMAIN)
                elif op=='federation.sync':
                    if 'content:admin' not in scopes:raise PermissionError('admin')
                    if set(args)!={'peer'}:raise ValueError('sync fields')
                    result=sync(fabric,args['peer'],peers)
                elif op=='library.download':
                    if 'library:write' not in scopes or 'content:write' not in scopes:raise PermissionError('download grant')
                    if set(args)-{'book','sources','max_chunks'} or not {'book','sources'}<=set(args):raise ValueError('download fields')
                    result=download(fabric,owner,args['book'],args['sources'],peers,max_chunks=args.get('max_chunks',128))
                else:
                    fields,write=OPERATIONS[op]
                    scope='content:admin' if op in ADMIN_OPERATIONS else op.split('.')[0]+(':write' if write else ':read')
                    if scope not in scopes:raise PermissionError('scope')
                    result=invoke(fabric,owner,op,args)
                self.send(200,result)
            except RateLimited:self.close_connection=True;self.send(429,{'error':'request rate exceeded'},extra={'Retry-After':'60'})
            except PermissionError:self.close_connection=True;self.send(403,{'error':'access denied'})
            except (ValueError,KeyError,TypeError):self.close_connection=True;self.send(400,{'error':'invalid request or operation rejected'})
            except Exception:
                self.close_connection=True;self.send(503,{'error':'operation failed; inspect durable state before retry'})
    address=config.get('listen','127.0.0.1');port=config.get('port',8210)
    if address not in {'127.0.0.1','::1','localhost'} and not config.get('tls'):raise ValueError('non-loopback listener requires TLS')
    result=BoundedHTTP((address,port),Handler)
    if config.get('tls'):
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(config['tls']['cert'],config['tls']['key'])
        result.socket=context.wrap_socket(result.socket,server_side=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True)
    args=parser.parse_args();config=strict_json(secure_read(args.config),131072)
    peers=config.get('peers',{})
    for token in config.get('tokens',[]):
        ident(token['account'])
        if not isinstance(token['token'],str) or len(token['token'])<32:raise ValueError('strong application credential required')
    fabric=Fabric(config['root'],quota=config.get('quota',2*1024**3),peers={p['public_key']:{'groups':p.get('groups',[])} for p in peers.values()})
    http=server(fabric,config)
    nntp=[]
    if config.get('nntp_tls_bridge',{}).get('enabled'):
        bridge=config['nntp_tls_bridge']
        if bridge.get('listen','127.0.0.1')!='127.0.0.1' or not bridge.get('allow_loopback_auth'):raise ValueError('TLS bridge must use explicitly trusted IPv4 loopback')
    for key in ('nntp','nntp_tls_bridge'):
        if not config.get(key,{}).get('enabled'):continue
        from .netnews_nntp import server as nntp_server
        listener=nntp_server(fabric,config[key],config.get(key+'_tokens',config.get('nntp_tokens',config['tokens'])))
        nntp.append(listener);threading.Thread(target=listener.serve_forever,daemon=True).start()
    print(json.dumps({'http':http.server_address,'node':fabric.public,'nntp':nntp[0].server_address if nntp else None,'nntp_listeners':[listener.server_address for listener in nntp]}),flush=True)
    try:http.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        http.server_close()
        for listener in nntp:listener.shutdown();listener.server_close()
        fabric.close()


if __name__=='__main__':main()

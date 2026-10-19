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
from pathlib import Path
import secrets
import socketserver
import ssl
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

from .content_fabric import Fabric, ident, merkle_verify
from .content_api import invoke, OPERATIONS
from .protocol import encoded, secure_read, strict_json
from .security import sign, verify
from .gateway_store import byte_range
from .chunkstore import CHUNK_BYTES

TRANSPORT_DOMAIN='Ziokt/ContentFabric/transport/v1'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('redirect rejected')


def remote(peer, payload):
    endpoint=peer['url']
    url=urlsplit(endpoint)
    if url.scheme not in {'https','http'} or url.username or url.password or url.query or url.fragment:raise ValueError('peer URL')
    if url.scheme!='https' and url.hostname not in {'127.0.0.1','::1','localhost'}:raise ValueError('TLS required')
    context=ssl.create_default_context(cafile=peer.get('ca'))
    opener=build_opener(NoRedirect(),HTTPSHandler(context=context))
    request=Request(endpoint.rstrip('/')+'/api',data=encoded(payload),headers={'Authorization':'Bearer '+peer['token'],'Content-Type':'application/json'},method='POST')
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
    """Persistent sparse checkpoint in ChunkStore; rotate explicit pinned sources.

    Source availability is proved by bytes, never merely a replica claim.
    Each call performs bounded work; repeated calls resume from durable chunks.
    """
    if not isinstance(sources,list) or not 1<=len(sources)<=8 or any(s not in peers for s in sources):raise ValueError('configured sources required')
    if type(max_chunks) is not int or not 1<=max_chunks<=1024:raise ValueError('download budget')
    with fabric.lock:record=fabric._get(owner,book,'book')
    meta=record['file'];oid=record['file_id']
    job=hashlib.sha256((owner+'\0'+oid).encode()).hexdigest()
    upload='download-'+job[:48]
    fabric.begin(owner,upload,meta['size'],meta['digest'],meta['mime'])
    with fabric.transaction():
        fabric.db.execute('INSERT OR IGNORE INTO downloads(id,owner,remote,upload,metadata,state) VALUES(?,?,?,?,?,?)',(job,owner,oid,upload,encoded(meta),'running'))
    completed=0
    failures=[]
    for _ in range(max_chunks):
        status=fabric.upload_status(owner,upload)
        if status['state']=='complete' or status['next_missing']>=status['total_chunks']:break
        position=status['next_missing']
        ok=False
        for alias in sources:
            try:
                result=remote(peers[alias],{'operation':'content.object.get','arguments':{'id':oid,'position':position}})
                data=base64.b64decode(result['data'],validate=True)
                merkle_verify(data,position,result['proof'],meta['merkle_root'])
                fabric.put(owner,upload,position,data)
                completed+=1;ok=True;break
            except (OSError,ValueError,KeyError,PermissionError) as exc:
                failures.append({'source':alias,'error':type(exc).__name__})
        if not ok:
            with fabric.transaction():fabric.db.execute("UPDATE downloads SET state='waiting',error='sources unavailable' WHERE id=?",(job,))
            return {'job':job,'state':'waiting','received_chunks':status['received_chunks'],'failures':failures[-8:]}
    status=fabric.upload_status(owner,upload)
    if status['next_missing']>=status['total_chunks']:
        result=fabric.finish(owner,upload)
        with fabric.transaction():
            fabric.db.execute('INSERT OR REPLACE INTO locations VALUES(?,?,?,?)',(oid,result['id'],owner,int(time.time())))
            fabric.db.execute("UPDATE downloads SET state='complete',error='' WHERE id=?",(job,))
        return {'job':job,'state':'complete','object':result,'verified':True}
    return {'job':job,'state':'running','received_chunks':status['received_chunks'],'total_chunks':status['total_chunks'],'failures':failures[-8:]}


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
    fabric.community_config=config.get('community',{})
    rate_lock=threading.Lock();rates={}
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def setup(self):super().setup();self.connection.settimeout(15)
        def log_message(self,*args):pass
        def send(self,status,data,mime='application/json',extra=None):
            raw=data if isinstance(data,bytes) else encoded(data)
            self.send_response(status)
            self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.send_header('Referrer-Policy','no-referrer')
            origin=self.headers.get('Origin')
            if origin in config.get('origins',[]):
                self.send_header('Access-Control-Allow-Origin',origin);self.send_header('Vary','Origin')
                self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type')
            for k,v in (extra or {}).items():self.send_header(k,v)
            self.end_headers()
            if self.command!='HEAD':self.wfile.write(raw)
        def principal(self):
            auth=self.headers.get('Authorization','')
            for entry in tokens:
                if hmac.compare_digest(auth,'Bearer '+entry['token']):return entry
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
            if origin and origin not in allowed:raise PermissionError('origin denied')
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
                if path in {'/','/content.js','/content.css'}:
                    name={'/':'content.html','/content.js':'content.js','/content.css':'content.css'}[path]
                    mime={'content.html':'text/html; charset=utf-8','content.js':'text/javascript','content.css':'text/css'}[name]
                    return self.send(200,(Path(__file__).parent/'web'/name).read_bytes(),mime)
                if path.startswith('/objects/'):
                    self.origin();principal=self.principal()
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
            except PermissionError:self.send(403,{'error':'access denied'})
            except (ValueError,KeyError):self.send(400,{'error':'invalid request'})
        def do_POST(self):
            try:
                if self.path!='/api':self.close_connection=True;return self.send(404,{'error':'not found'})
                self.origin();principal=self.principal()
                with rate_lock:
                    now=int(time.time())//60;key=principal['account']
                    previous,count=rates.get(key,(now,0));count=count+1 if previous==now else 1
                    rates[key]=(now,count)
                    if count>1200:raise ValueError('request rate')
                if self.headers.get('Transfer-Encoding'):raise ValueError('transfer encoding unsupported')
                lengths=self.headers.get_all('Content-Length',[])
                if len(lengths)!=1:raise ValueError('content length required')
                size=int(lengths[0])
                if not 0<size<=131072:raise ValueError('request budget')
                payload=strict_json(self.rfile.read(size),131072,string_limit=65536)
                if set(payload)!={'operation','arguments'}:raise ValueError('request envelope')
                op,args=payload['operation'],payload['arguments']
                scopes=principal['scopes'];owner=principal['account']
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
                    scope='content:admin' if op in {'content.sync','content.maintenance'} else op.split('.')[0]+(':write' if write else ':read')
                    if scope not in scopes:raise PermissionError('scope')
                    result=invoke(fabric,owner,op,args)
                self.send(200,result)
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
    nntp=None
    if config.get('nntp',{}).get('enabled'):
        from .netnews_nntp import server as nntp_server
        nntp=nntp_server(fabric,config['nntp'],config['tokens'])
        threading.Thread(target=nntp.serve_forever,daemon=True).start()
    print(json.dumps({'http':http.server_address,'node':fabric.public,'nntp':nntp.server_address if nntp else None}),flush=True)
    try:http.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        http.server_close()
        if nntp:nntp.shutdown();nntp.server_close()
        fabric.close()


if __name__=='__main__':main()

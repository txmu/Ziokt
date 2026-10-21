"""Authenticated HTTP adapter for bounded legacy-browser byte relay halves.

The connector is supplied by the operator/native transport. HTTP callers cannot
choose a socket address, service, command, encryption key or filesystem path.
"""
import hashlib
import hmac
import http.server
import re
import secrets
import socketserver
import threading
from pathlib import Path
from urllib.parse import urlsplit
from .protocol import ProtocolError,encoded,secure_read,strict_json
from .relay_stream import RelayHalf


def approved_origin(origin):
    if not isinstance(origin,str) or not re.fullmatch(r'https?://(?:[A-Za-z0-9.-]{1,253}|\[[a-fA-F0-9:]{2,45}\])(?::[0-9]{1,5})?',origin):raise ValueError('exact bounded origin required')
    parsed=urlsplit(origin)
    if parsed.port is not None and not 1<=parsed.port<=65535:raise ValueError('origin port')
    if parsed.scheme!='https' and parsed.hostname not in {'127.0.0.1','localhost','::1'}:raise ValueError('public relay requires HTTPS')
    return origin


class RelayService:
    def __init__(self,config,connector):
        self.config=Path(config);self.connector=connector
        self.lock=threading.RLock();self.sessions={};self.creating=set();self.stopped=False
        self.stop_event=threading.Event();self.settings()
        self.reaper=threading.Thread(target=self._reap,name='relay-capability-reaper',daemon=True);self.reaper.start()

    def _reap(self):
        while not self.stop_event.wait(.5):
            try:principals=self.settings()['principals']
            except Exception:principals={}
            with self.lock:
                removed=[]
                for name,entry in self.sessions.items():
                    if principals.get(name,{}).get('token_sha256')!=entry[2]:
                        entry[1].close('credential_revoked');removed.append(name)
                for name in removed:self.sessions.pop(name,None)

    def settings(self):
        value=strict_json(secure_read(self.config,32768),32768)
        if not isinstance(value,dict) or set(value)!={'schema','origins','principals'} or value['schema']!='ziokt.browser-relay.v1':raise ValueError('relay configuration schema')
        if not isinstance(value['origins'],list) or not 1<=len(value['origins'])<=8:raise ValueError('explicit page origins required')
        for origin in value['origins']:
            approved_origin(origin)
        if not isinstance(value['principals'],dict) or len(value['principals'])>32:raise ValueError('bounded approved relay principals required')
        for name,item in value['principals'].items():
            if not isinstance(name,str) or not 1<=len(name)<=64 or not isinstance(item,dict) or set(item)!={'token_sha256'} or not isinstance(item['token_sha256'],str) or len(item['token_sha256'])!=64 or any(c not in '0123456789abcdef' for c in item['token_sha256']):raise ValueError('relay principal')
        return value

    def authenticate(self,authorization):
        if not isinstance(authorization,str) or not authorization.startswith('Bearer ') or not 32<=len(authorization[7:])<=128:raise ProtocolError('AUTH_REQUIRED','Approved relay capability required')
        candidate=hashlib.sha256(authorization[7:].encode()).hexdigest();settings=self.settings()
        with self.lock:
            # Revoked credentials also close their live native transport.
            for name in list(self.sessions):
                if name not in settings['principals'] or self.sessions[name][2]!=settings['principals'][name]['token_sha256']:
                    self.sessions.pop(name)[1].close('credential_revoked')
        for name,value in settings['principals'].items():
            if hmac.compare_digest(value['token_sha256'],candidate):return name,candidate
        raise ProtocolError('AUTH_REJECTED','Unknown or revoked relay capability')

    def call(self,name,credential,operation,args):
        if not isinstance(args,dict):raise ValueError('object arguments required')
        if operation=='open':
            if args:raise ValueError('open fields')
            with self.lock:
                if self.stopped:raise ProtocolError('RELAY_CLOSED','Service stopped')
                previous=self.sessions.get(name)
                if previous and previous[1].status()['state'] not in {'closed','complete'}:
                    try:previous[1].read()
                    except ProtocolError:pass
                    else:return {'state':'open','session':previous[0],'duplicate':True}
                if name in self.creating:raise ProtocolError('RELAY_BUSY','Native connection is being established')
                if previous:self.sessions.pop(name)[1].close('replaced')
                self.creating.add(name)
            try:
                stream=self.connector()
                if stream is None:return {'state':'waiting','retry_ms':1000}
                with self.lock:
                    try:current=self.settings()['principals'].get(name)
                    except BaseException:stream.close();raise
                    if self.stopped or not current or current['token_sha256']!=credential:
                        stream.close();raise ProtocolError('AUTH_REJECTED','Capability revoked while opening native connection')
                    half=RelayHalf(stream);session=secrets.token_hex(24)
                    self.sessions[name]=(session,half,credential)
                return {'state':'open','session':session,'duplicate':False}
            finally:
                with self.lock:self.creating.discard(name)
        if operation not in {'read','write','ack','close','status'}:raise ProtocolError('NOT_FOUND','Unknown relay operation')
        fields={'session'}|({'frame'} if operation=='write' else {'sequence'} if operation=='ack' else set())
        if not isinstance(args,dict) or set(args)!=fields:raise ValueError('exact relay operation fields required')
        with self.lock:entry=self.sessions.get(name)
        if not entry or not isinstance(args['session'],str) or not hmac.compare_digest(entry[0],args['session']) or entry[2]!=credential:raise ProtocolError('RELAY_SESSION','Session is unavailable for this capability')
        half=entry[1]
        if operation=='read':return half.read()
        if operation=='write':return half.write(args['frame'])
        if operation=='ack':return half.acknowledge(args['sequence'])
        if operation=='status':return half.status()
        half.close('browser_stopped');return half.status()

    def close(self):
        self.stop_event.set()
        with self.lock:
            self.stopped=True
            halves=[v[1] for v in self.sessions.values()];self.sessions.clear()
        for half in halves:half.close('service_stopped')
        for half in halves:half.thread.join(2)
        self.reaper.join(2)


class RelayServer(socketserver.ThreadingMixIn,http.server.HTTPServer):
    daemon_threads=True;request_queue_size=16
    def __init__(self,address,service):
        self.slots=threading.BoundedSemaphore(16)
        super().__init__(address,handler(service))
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):self.shutdown_request(request);return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()


def handler(service):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def setup(self):super().setup();self.connection.settimeout(10)
        def log_message(self,*args):pass  # Never log bearer credentials or frames.
        def send(self,status,value,origin=None):
            if isinstance(value,dict) and value.get('state')=='frame':
                value={**value,'padding':''}
                value['padding']='0'*max(0,6144-len(encoded(value)))
            raw=encoded(value)
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Connection','close')
            if origin:self.send_header('Access-Control-Allow-Origin',origin);self.send_header('Vary','Origin')
            if self.command=='OPTIONS':
                self.send_header('Access-Control-Allow-Methods','POST');self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type')
            self.end_headers();self.wfile.write(raw);self.close_connection=True
        def process(self):
            origin=None
            try:
                origin=self.headers.get('Origin')
                if origin and origin not in service.settings()['origins']:return self.send(403,{'error':{'code':'ORIGIN_DENIED'}})
                if self.command=='OPTIONS':return self.send(200,{'state':'preflight'},origin)
                if self.command!='POST' or not self.path.startswith('/relay/v1/') or self.path.count('/')!=3:return self.send(404,{'error':{'code':'NOT_FOUND'}},origin)
                name,credential=service.authenticate(self.headers.get('Authorization'))
                if self.headers.get('Transfer-Encoding') or self.headers.get_content_type()!='application/json':raise ValueError('bounded JSON body required')
                lengths=self.headers.get_all('Content-Length',[])
                if len(lengths)!=1 or not lengths[0].isascii() or not lengths[0].isdigit() or not 2<=int(lengths[0])<=8192:raise ValueError('body limit')
                length=int(lengths[0]);raw=self.rfile.read(length)
                if len(raw)!=length:raise ValueError('incomplete body')
                args=strict_json(raw,8192)
                if isinstance(args,dict) and set(args)=={'arguments','padding'}:
                    if not isinstance(args['padding'],str) or any(c!='0' for c in args['padding']):raise ValueError('padding format')
                    args=args['arguments']
                result=service.call(name,credential,self.path.rsplit('/',1)[-1],args)
                return self.send(200,result,origin)
            except ProtocolError as error:return self.send(401 if error.code.startswith('AUTH_') else 409,{'error':{'code':error.code,'message':str(error)}},origin)
            except (ValueError,TypeError,KeyError):return self.send(400,{'error':{'code':'INVALID_REQUEST'}},origin)
            except (OSError,TimeoutError):return self.send(503,{'error':{'code':'NATIVE_UNAVAILABLE'}},origin)
        do_POST=process
        do_OPTIONS=process
    return Handler


def main():
    import argparse
    import socket
    from .runtime_policy import require_network
    parser=argparse.ArgumentParser(description='People Help opaque native transport adapter')
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--port',type=int,default=8769)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--ingress-port',type=int)
    modes.add_argument('--native-binding',type=Path)
    args=parser.parse_args();require_network()
    if not 1<=args.port<=65535 or args.ingress_port is not None and not 1<=args.ingress_port<=65535:parser.error('explicit port must be 1..65535')
    listener=None
    if args.ingress_port is not None:
        listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        listener.bind(('127.0.0.1',args.ingress_port));listener.listen(4);listener.settimeout(.5)
        def connector():
            try:return listener.accept()[0]
            except socket.timeout:return None
    else:
        from .native_peer import connect_native,validate_native
        binding=strict_json(secure_read(args.native_binding,8192),8192)
        validate_native(binding,binding.get('service_name'))
        if binding.get('require_s6epe') is not True:parser.error('reviewed S6EPE native binding required')
        def connector():return connect_native(binding['service_name'],1,binding,timeout=10)
    service=RelayService(args.config,connector);service.settings()
    server=RelayServer(('127.0.0.1',args.port),service)
    try:
        print(encoded({'state':'listening','host':'127.0.0.1','port':args.port,'public_tls_required':True,'inner_application_tls_required':True}).decode(),flush=True)
        server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        server.server_close();service.close()
        if listener:listener.close()


if __name__=='__main__':main()

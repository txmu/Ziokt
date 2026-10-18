"""Portable bounded DNS UDP/TCP and loopback DoH listener (TLS at proxy).

No recursive forwarding, system DNS calls, query logs, or identity authorization.
Requires explicitly configured native-node adapters. Configuration is private.
"""
import argparse
from collections import OrderedDict
import hashlib
import hmac
import http.server
import ipaddress
import os
import socketserver
import struct
import threading
import time
from urllib.parse import parse_qs,urlsplit
import base64
from .protocol import ProtocolError,secure_read,strict_json
from .naming import Names,NameNetworks
from .naming_corium import CoriumNames
from .dns_wire import answer


class Limits:
    def __init__(self):
        self.key=os.urandom(32);self.clients=OrderedDict();self.lock=threading.Lock()
    def admit(self,ip):
        identity=hmac.new(self.key,ip.encode(),hashlib.sha256).digest();now=time.monotonic()
        with self.lock:
            tokens,then=self.clients.pop(identity,(20.,now));tokens=min(20.,tokens+(now-then)*5)
            allowed=tokens>=1
            self.clients[identity]=(tokens-1 if allowed else tokens,now)
            while len(self.clients)>4096:self.clients.popitem(last=False)
            return allowed


class Workers:
    daemon_threads=True;block_on_close=False
    def process_request(self,request,address):
        if not self.workers.acquire(blocking=False):return self.shutdown_request(request)
        try:super().process_request(request,address)
        except BaseException:self.workers.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.workers.release()
    def handle_error(self,*_):pass


class UDP(Workers,socketserver.ThreadingUDPServer):
    max_packet_size=4097
class TCP(Workers,socketserver.ThreadingTCPServer):
    allow_reuse_address=True
class HTTP(Workers,http.server.ThreadingHTTPServer):pass


def servers(resolver,*,host='127.0.0.1',port=5353,doh_port=0):
    from .runtime_policy import require_network
    require_network()
    family=ipaddress.ip_address(host).version
    if type(port) is not int or not 0<=port<=65535:raise ValueError('invalid DNS port')
    limits=Limits()
    class Datagram(socketserver.BaseRequestHandler):
        def handle(self):
            data,sock=self.request
            if len(data)<=4096 and limits.admit(self.client_address[0]):sock.sendto(answer(data,resolver),self.client_address)
    class Stream(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(3)
            def receive(length):
                output=bytearray()
                while len(output)<length:
                    part=self.request.recv(length-len(output))
                    if not part:raise EOFError()
                    output.extend(part)
                return bytes(output)
            try:
                for _ in range(16):
                    length=struct.unpack('!H',receive(2))[0]
                    if not 12<=length<=4096 or not limits.admit(self.client_address[0]):return
                    response=answer(receive(length),resolver,tcp=True)
                    self.request.sendall(struct.pack('!H',len(response))+response)
            except (EOFError,OSError,ValueError):pass
    class DoH(http.server.BaseHTTPRequestHandler):
        def setup(self):super().setup();self.connection.settimeout(5)
        def log_message(self,*_):pass
        def send_response(self,code,message=None):
            self.send_response_only(code,message);self.send_header('Date',self.date_time_string())
        def do_GET(self):self.serve(False)
        def do_POST(self):self.serve(True)
        def serve(self,post):
            parts=urlsplit(self.path)
            active=resolver
            if parts.path!='/dns-query':
                segments=parts.path.split('/')
                if len(segments)!=4 or segments[1]!='realms' or segments[3]!='dns-query' or not isinstance(resolver,NameNetworks):return self.send_error(404)
                try:active=resolver.view(segments[2])
                except ProtocolError:return self.send_error(404)
            address=self.client_address[0]
            forwarded=self.headers.get_all('X-Ziokt-Client-IP',[])
            if forwarded:
                try:
                    if len(forwarded)!=1 or len(forwarded[0])>45:raise ValueError()
                    address=str(ipaddress.ip_address(forwarded[0]))
                except ValueError:return self.send_error(400)
            if not limits.admit(address):return self.send_error(429)
            try:
                if post:
                    if self.headers.get('Content-Type')!='application/dns-message' or self.headers.get('Transfer-Encoding'):raise ValueError()
                    length=int(self.headers.get('Content-Length','0'))
                    if not 12<=length<=4096:raise ValueError()
                    data=self.rfile.read(length)
                    if len(data)!=length:raise ValueError()
                else:
                    query=parse_qs(parts.query,strict_parsing=True)
                    if set(query)!={'dns'} or len(query['dns'])!=1 or len(query['dns'][0])>5462:raise ValueError()
                    text=query['dns'][0]
                    data=base64.b64decode(text+'='*((-len(text))%4),altchars=b'-_',validate=True)
                    if not 12<=len(data)<=4096:raise ValueError()
                body=answer(data,active,tcp=True)
                self.send_response(200);self.send_header('Content-Type','application/dns-message')
                self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            except (ValueError,OSError):self.send_error(400)
    opened=[]
    try:
        import socket
        udp_type=type('FamilyUDP',(UDP,),{'address_family':socket.AF_INET6 if family==6 else socket.AF_INET})
        tcp_type=type('FamilyTCP',(TCP,),{'address_family':socket.AF_INET6 if family==6 else socket.AF_INET})
        udp=udp_type((host,port),Datagram);opened.append(udp)
        tcp=tcp_type((host,udp.server_address[1]),Stream);opened.append(tcp)
        if doh_port is not None:opened.append(HTTP(('127.0.0.1',doh_port),DoH))
        # Share one finite budget across all transports, including expensive
        # encrypted-community projections. DoH must not bypass UDP/TCP limits.
        workers=threading.BoundedSemaphore(8)
        for server in opened:server.workers=workers
        return opened
    except BaseException:
        for server in opened:server.server_close()
        raise


def load(path):
    config=strict_json(secure_read(path))
    if (not isinstance(config,dict) or set(config)!={'schema','listen','port','doh_port','default_realm','realms'} or
            config['schema']!='ziokt.dns.v2' or not isinstance(config['realms'],dict)):
        raise ValueError('exact private multi-realm DNS configuration required')
    realms={}
    for realm,profile in config['realms'].items():
        if not isinstance(profile,dict) or set(profile)!={'network_id','sources'} or not isinstance(profile['sources'],dict):
            raise ValueError('explicit per-realm chain and sources required')
        sources={}
        for component,source in profile['sources'].items():
            if component=='corium':
                if isinstance(source,dict) and set(source)=={'ibc'}:
                    from .ibc_naming import IBCNames
                    sources[component]=IBCNames(**source['ibc'],namespace=profile['network_id'])
                else:
                    if not isinstance(source,dict) or set(source)-{'native_network_id'}!={'forum_db','chain_db','objects'}:
                        raise ValueError('Corium suffixes exclusively require native NNS or native IBC node paths')
                    native_source={key:value for key,value in source.items() if key!='native_network_id'}
                    sources[component]=CoriumNames(**native_source,network_id=source.get('native_network_id',profile['network_id']),namespace=profile['network_id'])
            else:
                if not isinstance(source,dict) or set(source)!={'component_bridge'}:
                    raise ValueError('component-owned naming node required; cross-component fallback forbidden')
                from .naming_community import ComponentNames
                sources[component]=ComponentNames(source['component_bridge'],component=component,network_id=profile['network_id'])
        realms[realm]=Names(sources,network_id=profile['network_id'])
    return config,NameNetworks(realms,default=config['default_realm'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True);args=parser.parse_args()
    config,resolver=load(args.config)
    opened=servers(resolver,host=config['listen'],port=config['port'],doh_port=config['doh_port'])
    try:
        for server in opened[1:]:threading.Thread(target=server.serve_forever,daemon=True).start()
        opened[0].serve_forever()
    finally:
        for server in opened:server.server_close()

if __name__=='__main__':main()


def register(sub):
    parser=sub.add_parser('dns',help='node-backed multi-realm Ziokt naming; no public DNS fallback')
    actions=parser.add_subparsers(dest='dns_action',required=True)
    for action in ('serve','resolve','status'):
        command=actions.add_parser(action);command.add_argument('--config',required=True)
        if action=='resolve':
            command.add_argument('--name',required=True);command.add_argument('--realm');command.add_argument('--component')

def execute(args):
    config,networks=load(args.config)
    if args.dns_action=='resolve':return networks.resolve(args.name,realm=args.realm,component=args.component,public=args.component is None)
    if args.dns_action=='status':return {'default_realm':networks.default,'realms':{key:{'network_id':view.network_id,'sources':sorted(view.sources)} for key,view in networks.realms.items()},'public_dns_fallback':False}
    opened=servers(networks,host=config['listen'],port=config['port'],doh_port=config['doh_port'])
    try:
        for server in opened[1:]:threading.Thread(target=server.serve_forever,daemon=True).start()
        opened[0].serve_forever()
    except KeyboardInterrupt:pass
    finally:
        for server in opened:server.server_close()
    return {'stopped':True}

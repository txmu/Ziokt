"""Real loopback HTTP + endpoint mTLS fixture; no Shadow6 deployment claim."""
import hashlib,json,queue,secrets,socket,sys,tempfile,threading
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'tests')]
from test_community_network import certificates
from ziokt.remote import tls_context
from ziokt.relay_web import RelayService,RelayServer
from ziokt.effort_web import effort_server

class NoCompute:
    def issue(self):raise AssertionError('Legacy relay must not request CPU work')

def main():
    if '--direct' in sys.argv:return direct_main()
    with tempfile.TemporaryDirectory(prefix='people-browser-') as directory:
        root=Path(directory);servers=[];threads=[];services=[];errors=[];outcome=[]
        app_a,half_a=socket.socketpair();app_b,half_b=socket.socketpair()
        for stream in (app_a,app_b):stream.settimeout(30)
        invitations=[];configs=[]
        for index,stream in enumerate((half_a,half_b)):
            path=root/(str(index)+'.json');token=secrets.token_urlsafe(36)
            config={'schema':'ziokt.browser-relay.v1','origins':['http://127.0.0.1'],'principals':{'phone':{'token_sha256':hashlib.sha256(token.encode()).hexdigest()}}}
            path.write_text(json.dumps(config));path.chmod(0o600);configs.append((path,config))
            pending=queue.Queue();pending.put(stream)
            def connector(pending=pending):
                try:return pending.get_nowait()
                except queue.Empty:return None
            service=RelayService(path,connector);services.append(service)
            server=RelayServer(('127.0.0.1',0),service);servers.append(server)
            invitations.append({'origin':'http://127.0.0.1:'+str(server.server_port),'token':token})
        # Reserve a test-only page port; no public listener or production mutation.
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0));page_port=reservation.getsockname()[1]
        page_origin='http://127.0.0.1:'+str(page_port)
        for path,config in configs:
            config['origins']=[page_origin];path.write_text(json.dumps(config))
        servers.append(effort_server(NoCompute(),page_origin,port=page_port,relay_origins=[v['origin'] for v in invitations]))
        ca,pairs=certificates(root,host='localhost')
        client=tls_context(*pairs['client'][:2],ca);server_context=tls_context(*pairs['server'][:2],ca,server=True)
        def application(stream,context,is_server):
            try:
                with context.wrap_socket(stream,server_side=is_server,server_hostname=None if is_server else 'localhost') as secured:
                    if is_server:
                        assert secured.recv(4096)==b'GEOGRAPHY-PRIVATE-TLS-LESSON'
                        secured.sendall(b'GEOGRAPHY-PRIVATE-TLS-ANSWER')
                    else:
                        secured.sendall(b'GEOGRAPHY-PRIVATE-TLS-LESSON')
                        assert secured.recv(4096)==b'GEOGRAPHY-PRIVATE-TLS-ANSWER'
                    secured.unwrap().close()
                outcome.append('server' if is_server else 'client')
            except BaseException as error:errors.append(repr(error))
        for server in servers:
            thread=threading.Thread(target=server.serve_forever);thread.start();threads.append(thread)
        applications=[threading.Thread(target=application,args=(app_a,client,False)),threading.Thread(target=application,args=(app_b,server_context,True))]
        for thread in applications:thread.start()
        try:
            print(json.dumps({'origin':page_origin,'invitation':{'v':1,'a':invitations[0],'b':invitations[1]}}),flush=True)
            sys.stdin.readline()
        finally:
            for service in services:service.close()
            for server in servers:server.shutdown();server.server_close()
            for thread in threads+applications:thread.join(3)
            app_a.close();app_b.close()
        if errors or sorted(outcome)!=['client','server']:raise RuntimeError(json.dumps({'errors':errors,'completed':outcome}))
        print(json.dumps({'state':'passed','inner_mtls':True,'native_shadow6_deployment':False,'corium_settlement':False}),flush=True)


def direct_main():
    from ziokt.effort_direct import DirectRelay
    with tempfile.TemporaryDirectory(prefix='people-direct-') as directory:
        root=Path(directory);ca,pairs=certificates(root,host='localhost')
        client=tls_context(*pairs['client'][:2],ca);secure_server=tls_context(*pairs['server'][:2],ca,server=True)
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(30)
        with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));relay_port=reservation.getsockname()[1]
        relay=DirectRelay({'listen':'127.0.0.1','port':relay_port,'target_host':'127.0.0.1','target_port':listener.getsockname()[1],'network_id':'ziokt-main'},'ziokt-main')
        with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));page_port=reservation.getsockname()[1]
        origin='http://127.0.0.1:'+str(page_port);page=effort_server(NoCompute(),origin,port=page_port,direct_relay=relay)
        thread=threading.Thread(target=page.serve_forever);thread.start();errors=[];outcome=[]
        def application(is_server):
            try:
                stream=listener.accept()[0] if is_server else socket.create_connection(('127.0.0.1',relay_port),timeout=30)
                stream.settimeout(30)
                context=secure_server if is_server else client
                with context.wrap_socket(stream,server_side=is_server,server_hostname=None if is_server else 'localhost') as secured:
                    if is_server:
                        assert secured.recv(4096)==b'GEOGRAPHY-PRIVATE-TLS-LESSON';secured.sendall(b'GEOGRAPHY-PRIVATE-TLS-ANSWER')
                    else:
                        secured.sendall(b'GEOGRAPHY-PRIVATE-TLS-LESSON');assert secured.recv(4096)==b'GEOGRAPHY-PRIVATE-TLS-ANSWER'
                    secured.unwrap().close()
                outcome.append('server' if is_server else 'client')
            except BaseException as error:errors.append(repr(error))
        applications=[threading.Thread(target=application,args=(value,)) for value in (True,False)]
        for app in applications:app.start()
        try:
            print(json.dumps({'origin':origin,'invitation':None,'direct':True}),flush=True);sys.stdin.readline()
        finally:
            relay.close();page.shutdown();page.server_close();thread.join(3);listener.close()
            for app in applications:app.join(3)
        if errors or sorted(outcome)!=['client','server']:raise RuntimeError(json.dumps({'errors':errors,'completed':outcome}))
        print(json.dumps({'state':'passed','inner_mtls':True,'direct_default':True,'native_shadow6_deployment':False,'corium_settlement':False}),flush=True)

if __name__=='__main__':main()

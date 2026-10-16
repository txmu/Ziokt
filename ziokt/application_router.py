"""One owner-configured, typed native application entry for every component."""
from pathlib import Path
import threading
from .component_links import COMPONENTS
from .protocol import ProtocolError, secure_read, strict_json


class ApplicationRouter:
    def __init__(self, path):
        self._backends={};self._backend_lock=threading.RLock()
        self.path=Path(path);self.raw=secure_read(path);self.config=strict_json(self.raw)
        if not isinstance(self.config,dict) or set(self.config)!={'schema','components'} or self.config['schema']!='ziokt.application-router.v1' or not isinstance(self.config['components'],dict) or not self.config['components'] or set(self.config['components'])-COMPONENTS:
            raise ProtocolError('INVALID_ROUTER','fixed component routing table required')
        for target,route in self.config['components'].items():
            fields=({'federation_config','provider','methods'} if target in {'shadow6','corium'} else {'binary','digest','config','methods'} if target=='etp' else {'config','methods'})
            if not isinstance(route,dict) or set(route)!=fields or not isinstance(route['methods'],list) or not 1<=len(route['methods'])<=32 or any(not isinstance(m,str) or len(m)>64 for m in route['methods']):raise ProtocolError('INVALID_ROUTER','exact route and method grants required')
            for field in fields-{'provider','methods','digest'}:
                if not isinstance(route[field],str) or not Path(route[field]).is_absolute() or '..' in Path(route[field]).parts:raise ProtocolError('INVALID_ROUTER','fixed absolute backend paths required')

    def call(self,target,method,params):
        try:current=secure_read(self.path)
        except (OSError,ProtocolError):self.close();raise
        if current!=self.raw:
            self.close();raise ProtocolError('STALE_PLAN','application routing configuration changed')
        if not isinstance(target,str) or target not in self.config['components'] or not isinstance(method,str) or not isinstance(params,dict):raise ProtocolError('POLICY_DENIED','configured typed component call required')
        route=self.config['components'][target]
        if method not in route['methods']:raise ProtocolError('POLICY_DENIED','component method is not granted')
        if target in {'shadow6','corium'}:
            from .config import load
            from .client import NativeClient
            config=load(route['federation_config'])
            provider=next((p for p in config['providers'] if p['provider_id']==route['provider'] and p['native_project']==target),None)
            if not config['enabled'] or provider is None:raise ProtocolError('POLICY_DENIED','enabled matching native provider required')
            return NativeClient(config['federation_id'],provider).call(method,params)
        if target=='etp':
            from .etp import EtpGateway
            with self._backend_lock:
                backend=self._backends.get(target)
                if backend is None:
                    backend=EtpGateway(route['binary'],route['digest'],route['config']);self._backends[target]=backend
                return backend.call(method,params)
        else:
            from .companion_bridge import CompanionBridge
            backend=CompanionBridge(route['config'])
            if backend.app!=target:
                backend.close();raise ProtocolError('SCOPE_MISMATCH','target does not match configured application identity')
        try:return backend.call(method,params)
        finally:backend.close()

    def close(self):
        with self._backend_lock:
            backends=list(self._backends.values());self._backends.clear()
        for backend in backends:backend.close()

    def __enter__(self):return self
    def __exit__(self,*exc):self.close()


def serve(path,input_stream,output_stream):
    """Owner-started bounded JSONL process; no listener, sockets or implicit daemon."""
    from .protocol import encoded
    router=ApplicationRouter(path)
    try:
        for _ in range(4096):
            frame=input_stream.readline(131073)
            if not frame:break
            terminal=len(frame)>131072 or not frame.endswith(b'\n')
            try:
                if terminal:raise ProtocolError('REQUEST_LIMIT','bounded newline terminated application frame required')
                request=strict_json(frame,131072,string_limit=32768)
                if not isinstance(request,dict) or set(request)!={'target','method','params'}:raise ProtocolError('INVALID_REQUEST','exact target/method/params required')
                result=router.call(request['target'],request['method'],request['params'])
                response={'ok':True,'result':result}
                raw=encoded(response)+b'\n'
                if len(raw)>131072:raise ProtocolError('RESPONSE_LIMIT','bounded application result required')
            except ProtocolError as error:
                raw=encoded({'ok':False,'error':{'code':error.code}})+b'\n'
            except (OSError,ValueError,TypeError):
                raw=encoded({'ok':False,'error':{'code':'APPLICATION_REJECTED'}})+b'\n'
            output_stream.write(raw);output_stream.flush()
            if terminal:break
    finally:router.close()

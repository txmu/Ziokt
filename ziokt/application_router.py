"""One owner-configured, typed native application entry for every component."""
from pathlib import Path
from .component_links import COMPONENTS
from .protocol import ProtocolError, secure_read, strict_json


class ApplicationRouter:
    def __init__(self, path):
        self.path=Path(path);self.raw=secure_read(path);self.config=strict_json(self.raw)
        if not isinstance(self.config,dict) or set(self.config)!={'schema','components'} or self.config['schema']!='ziokt.application-router.v1' or not isinstance(self.config['components'],dict) or not self.config['components'] or set(self.config['components'])-COMPONENTS:
            raise ProtocolError('INVALID_ROUTER','fixed component routing table required')
        for target,route in self.config['components'].items():
            fields=({'federation_config','provider','methods'} if target in {'shadow6','corium'} else {'binary','digest','config','methods'} if target=='etp' else {'config','methods'})
            if not isinstance(route,dict) or set(route)!=fields or not isinstance(route['methods'],list) or not 1<=len(route['methods'])<=32 or any(not isinstance(m,str) or len(m)>64 for m in route['methods']):raise ProtocolError('INVALID_ROUTER','exact route and method grants required')
            for field in fields-{'provider','methods','digest'}:
                if not isinstance(route[field],str) or not Path(route[field]).is_absolute() or '..' in Path(route[field]).parts:raise ProtocolError('INVALID_ROUTER','fixed absolute backend paths required')

    def call(self,target,method,params):
        if secure_read(self.path)!=self.raw:raise ProtocolError('STALE_PLAN','application routing configuration changed')
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
            backend=EtpGateway(route['binary'],route['digest'],route['config'])
        else:
            from .companion_bridge import CompanionBridge
            backend=CompanionBridge(route['config'])
            if backend.app!=target:
                backend.close();raise ProtocolError('SCOPE_MISMATCH','target does not match configured application identity')
        try:return backend.call(method,params)
        finally:backend.close()

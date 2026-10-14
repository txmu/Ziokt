"""Reviewed joint Corium / Virtual Broker / S6EPE node deployment.

Planning and export do not start host services. The exported target binds the
existing Corium, Guard and Gate units to Ziokt's owned Virtual Broker process.
Native Brokers and S6EPE remain independent same-family locked deployments.
"""
import asyncio
import hashlib
import importlib.util
import ipaddress
from pathlib import Path
import re
import sys
import tempfile

from .cli import write_exclusive,write_binary_exclusive
from .config import load
from .client import NativeClient
from .extensions import sha
from .protocol import ProtocolError,encoded,identifier,secure_read,strict_json

SOURCES=('Public6/virtual_broker.py','Deployment/service_storage.py')
CORES={'go','rust','gleam','ada','nim','pony','zig','d','cpp','idris','hare','carp'}


def _snapshot(root,pins,target):
    if set(pins)!=set(SOURCES):raise ProtocolError('INVALID_NODE','complete Virtual Broker source pins required')
    for name in SOURCES:
        data=secure_read(Path(root)/name,1024*1024,private=None)
        if sha(data)!=pins[name]:raise ProtocolError('STALE_PLAN','reviewed native Virtual Broker source changed')
        dest=Path(target)/name;dest.parent.mkdir(mode=0o700,parents=True,exist_ok=True);write_binary_exclusive(dest,data)


def _virtual_module(tree):
    # Import verified private snapshot bytes under a unique name. Its executable
    # bootstrap is not run, and it cannot import ambient Shadow6 modules.
    name='ziokt_vbroker_'+hashlib.sha256(str(tree).encode()).hexdigest()[:16]
    old_path=list(sys.path);saved={k:sys.modules.pop(k) for k in ('service_storage','Deployment','Deployment.service_storage') if k in sys.modules}
    (Path(tree)/'Deployment/__init__.py').write_text('')
    try:
        sys.path[:0]=[str(tree),str(Path(tree)/'Deployment')]
        spec=importlib.util.spec_from_file_location(name,Path(tree)/SOURCES[0]);module=importlib.util.module_from_spec(spec)
        sys.modules[name]=module;spec.loader.exec_module(module);return module
    finally:
        sys.path[:]=old_path
        for k in ('service_storage','Deployment','Deployment.service_storage'):sys.modules.pop(k,None)
        sys.modules.update(saved)
        sys.modules.pop(name,None)


def create_profile(root,federation,provider,registry,virtual_config,units,*,require_s6epe=True):
    root=Path(root).absolute();identifier(provider,'provider')
    for unit in units.values():
        if not isinstance(unit,str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,95}\\.service',unit):raise ProtocolError('INVALID_NODE','fixed native service unit names required')
    if set(units)!={'corium','guard','gate'} or type(require_s6epe) is not bool:raise ProtocolError('INVALID_NODE','explicit joint native dependencies required')
    pins={name:sha(secure_read(root/name,1024*1024,private=None)) for name in SOURCES}
    profile={'schema':'ziokt.node.v1','shadow6_root':str(root),'federation_config':str(Path(federation).absolute()),'corium_provider':provider,
        'registry':str(Path(registry).absolute()),'virtual_config':str(Path(virtual_config).absolute()),'sources':pins,'units':units,
        'require_s6epe':require_s6epe,'virtual_digest':sha(secure_read(virtual_config,262144)),
        'registry_digest':sha(secure_read(registry,4*1024*1024)),'federation_digest':sha(secure_read(federation,262144))}
    plan(profile,probe=False)
    return profile


def plan(profile,*,probe=True,require_runtime=False):
    required={'schema','shadow6_root','federation_config','corium_provider','registry','virtual_config','sources','units','require_s6epe','virtual_digest','registry_digest','federation_digest'}
    if not isinstance(profile,dict) or set(profile)!=required or profile['schema']!='ziokt.node.v1' or type(profile['require_s6epe']) is not bool:raise ProtocolError('INVALID_NODE','exact joint node profile required')
    if not isinstance(profile['units'],dict) or set(profile['units'])!={'corium','guard','gate'} or any(not isinstance(v,str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,95}\\.service',v) for v in profile['units'].values()):raise ProtocolError('INVALID_NODE','native unit dependencies required')
    for field in ('shadow6_root','federation_config','registry','virtual_config'):
        if not isinstance(profile[field],str) or not Path(profile[field]).is_absolute() or '..' in Path(profile[field]).parts or Path(profile[field]).is_symlink():raise ProtocolError('INVALID_NODE','owner-controlled absolute node paths required')
    for field,budget in (('virtual',262144),('registry',4*1024*1024),('federation',262144)):
        path=profile['virtual_config' if field=='virtual' else 'federation_config' if field=='federation' else 'registry']
        if sha(secure_read(path,budget))!=profile[field+'_digest']:raise ProtocolError('STALE_PLAN','reviewed joint node material changed')
    config=load(profile['federation_config'])
    source=next((p for p in config['providers'] if p['provider_id']==profile['corium_provider'] and p['native_project']=='corium'),None)
    if source is None or not config['enabled']:raise ProtocolError('INVALID_NODE','enabled native Corium federation provider required')
    registry=strict_json(secure_read(profile['registry'],4*1024*1024),4*1024*1024)
    if not isinstance(registry,dict) or registry.get('schema')!='shadow6.service-registry.v2' or not isinstance(registry.get('services'),dict):raise ProtocolError('INVALID_NODE','native named-service registry required')
    with tempfile.TemporaryDirectory(prefix='ziokt-node-plan-') as tmp:
        _snapshot(profile['shadow6_root'],profile['sources'],tmp)
        module=_virtual_module(tmp);vb=module.load_config(Path(profile['virtual_config']))
    shadow=next((p for p in config['providers'] if p['native_project']=='shadow6' and Path(p['root'])==Path(profile['shadow6_root'])),None)
    if probe and shadow is None:raise ProtocolError('INVALID_NODE','reviewed Shadow6 provider required for native lock verification')
    shadow_client=NativeClient(config['federation_id'],shadow) if probe else None
    rows=[];families=set()
    for (tenant,core),endpoint in sorted(vb.routes.items()):
        # Each route must have a dedicated locked Broker of exactly that family.
        matching=[]
        for name,item in registry['services'].items():
            if not isinstance(item,dict):continue
            binding=item.get('coreBinding') or {};context=item.get('protocolContext') or {}
            if binding.get('core')!=core or context.get('role') not in {'broker','all'} or not item.get('deploymentLock'):continue
            # Native Broker target is explicit reviewed configuration. A service
            # cannot claim readiness merely from a loopback open port.
            native_path=(binding.get('config') or {}).get('config_path')
            if not native_path:continue
            try: native=strict_json(secure_read(native_path,262144))
            except (OSError,ProtocolError):continue
            entries=[]
            if item.get('privacy')=='envelope':
                envelope_path=(item.get('spec') or {}).get('envelope_config')
                if not envelope_path:continue
                for line in secure_read(envelope_path,16384).decode().splitlines():
                    if line.startswith('listen='):entries.append(line.split('=',1)[1])
            else:
                def scan(value):
                    if isinstance(value,dict):
                        if isinstance(value.get('listen_host'),str) and type(value.get('listen_port')) is int:
                            entries.append(('['+value['listen_host']+']' if ':' in value['listen_host'] else value['listen_host'])+':'+str(value['listen_port']))
                        for k,v in value.items():
                            if k in {'listen','listen_addr','listen_address'} and isinstance(v,str):entries.append(v)
                            scan(v)
                    elif isinstance(value,list):
                        for v in value:scan(v)
                scan(native.get('broker',native))
            target=('['+endpoint[0]+']' if ':' in endpoint[0] else endpoint[0])+':'+str(endpoint[1])
            if target not in entries:continue
            if profile['require_s6epe'] and item.get('privacy')!='envelope':continue
            matching.append(name)
        if len(matching)!=1:raise ProtocolError('NO_POLICY_COMPLIANT_PATH','each Virtual Broker route needs one matching locked native Broker and required S6EPE')
        if shadow_client is not None:
            fact=shadow_client.call('service.binding',{'service_name':matching[0]})
            target=('['+endpoint[0]+']' if ':' in endpoint[0] else endpoint[0])+':'+str(endpoint[1])
            if fact.get('core')!=core or fact.get('assurance')!='native-locked-material' or target not in fact.get('entry_endpoints',[]) or profile['require_s6epe'] and fact.get('privacy')!='envelope':raise ProtocolError('STALE_PLAN','Virtual Broker route differs from native locked entry')
            if require_runtime and fact.get('runtime_ready') is not True:raise ProtocolError('NATIVE_STATE_UNAVAILABLE','native Broker must be running before joint Virtual Broker')
        rows.append({'tenant':tenant,'core':core,'service':matching[0],'privacy':'envelope' if profile['require_s6epe'] else 'native','runtime_verified':False})
        families.add(core)
    native_status=NativeClient(config['federation_id'],source).call('status.get') if probe else None
    return {'schema':'ziokt.node-plan.v1','plan_digest':sha(encoded(profile)),'cores':sorted(families),'routes':rows,
        'corium':{'provider_id':profile['corium_provider'],'status':native_status,'p2p_and_ledger_unit':profile['units']['corium']},
        'guard_required':True,'gate_required':True,'s6epe_required':profile['require_s6epe'],'free_forwarding':True,
        'runtime_verified':False,'lifecycle':'explicit-exported-target','wire_translation':False}


def _unit_arg(value):
    if not isinstance(value,str) or any(c in value for c in '\n\r\0'):raise ProtocolError('INVALID_NODE','single-line service argument required')
    return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('%','%%').replace('$','$$')+'"'


def export_units(profile,profile_path,output,name,python=sys.executable):
    identifier(name,'node name');review=plan(profile,probe=False)
    output=Path(output);output.mkdir(mode=0o700,parents=True,exist_ok=True)
    dependencies=' '.join(profile['units'][k] for k in ('corium','guard','gate'))
    target=f'[Unit]\nDescription=Ziokt joint native node\nRequires={dependencies} {name}-virtual-broker.service\nAfter={dependencies}\n\n[Install]\nWantedBy=multi-user.target\n'
    service=f'[Unit]\nDescription=Ziokt opaque Virtual Broker\nRequires={dependencies}\nAfter={dependencies}\nPartOf={name}.target\n\n[Service]\nType=simple\nExecStart={_unit_arg(str(python))} -m ziokt node serve --profile {_unit_arg(str(Path(profile_path).absolute()))} --expected-digest {_unit_arg(review["plan_digest"])}\nNoNewPrivileges=yes\nPrivateTmp=yes\nProtectSystem=strict\nRestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX\nMemoryMax=512M\nTasksMax=128\nRestart=on-failure\nRestartSec=5\n'
    write_binary_exclusive(output/(name+'.target'),target.encode());write_binary_exclusive(output/(name+'-virtual-broker.service'),service.encode())
    return {**review,'files':[str(output/(name+'.target')),str(output/(name+'-virtual-broker.service'))],'installed':False}


def serve(profile,expected_digest):
    review=plan(profile,require_runtime=True)
    if review['plan_digest']!=expected_digest:raise ProtocolError('STALE_PLAN','joint node differs from reviewed plan')
    with tempfile.TemporaryDirectory(prefix='ziokt-node-run-') as tmp:
        _snapshot(profile['shadow6_root'],profile['sources'],tmp)
        module=_virtual_module(tmp);config=module.load_config(Path(profile['virtual_config']))
        asyncio.run(module.Broker(config).serve())

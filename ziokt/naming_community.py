"""Explicit public naming projection from component-owned encrypted communities.

The signed community owner assigns roots. This is a community authority, not an
invented Corium consensus proof. Corium suffixes exclusively use native NNS.
"""
import hashlib
from pathlib import Path
from .protocol import ProtocolError,encoded,strict_json,secure_read
from .security import verify
from .naming import LABEL,Names,GROUPS

DOMAIN='Ziokt/component-name-registration/v1'
APP_COMPONENT={'sim-manager':'sim'}
def component_of(bridge):return APP_COMPONENT.get(bridge.app,bridge.app)


def key_for(component,network_id,root):
    return hashlib.sha256(encoded([component,network_id,root])).hexdigest()


def check_record(bridge,envelope,network_id,root):
    authorities = []
    if hasattr(bridge, 'signing_public') and bridge.signing_public:
        authorities.append(bridge.signing_public)
    if hasattr(bridge, 'signing_key') and bridge.signing_key:
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
            key_bytes = bridge.signing_key
            if isinstance(key_bytes, (str, Path)):key_bytes = secure_read(key_bytes, 32)
            authorities.append(Ed25519PrivateKey.from_private_bytes(key_bytes).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex())
        except Exception:pass
    if hasattr(bridge, 'community') and hasattr(bridge.community, 'owner') and bridge.community.owner:
        authorities.append(bridge.community.owner)
    record = None
    verified_authority = None
    for auth in authorities:
        for domain in (DOMAIN, 'Ziokt/tc16-name-registration/v1'):
            try:
                record = verify(envelope, auth, domain)
                verified_authority = auth
                break
            except ProtocolError:pass
        if record is not None:break
    if record is None:
        raise ProtocolError('SCOPE_MISMATCH', 'registration is not authorized by companion native signing authority')
    fields={'network_id','component','root','owner','revision','expires_at','delegations','published_suffixes'}
    if (not isinstance(record,dict) or set(record)!=fields or record['network_id']!=network_id or
            record['component']!=component_of(bridge) or record['root']!=root or (not isinstance(root,str) or not LABEL.fullmatch(root)) or
            component_of(bridge) not in GROUPS or component_of(bridge)=='corium' or network_id not in bridge.naming_namespaces):
        raise ProtocolError('SCOPE_MISMATCH','component node, community network and root must match registration')
    comp=component_of(bridge)
    native={k:v for k,v in record.items() if k not in {'root','component'}}
    native['proof']={'kind':f'native-{comp}-authority','component':comp,'application':bridge.app,
                     'community_id':getattr(bridge.community,'community_id',None),
                     'authority':verified_authority,'vault_root':getattr(bridge,'vault_root',None),'registration':envelope}
    if record['published_suffixes']:
        Names({comp:lambda _:native},network_id=network_id).resolve(root+'.'+record['published_suffixes'][0])
    elif type(record['revision']) is not int or record['revision']<1:
        raise ProtocolError('NAME_REJECTED','positive registration revision required')
    return record,native


def current(bridge,network_id,root):
    view=bridge.community.view('names',key_for(component_of(bridge),network_id,root))
    if view['conflicts']:raise ProtocolError('NAME_REJECTED','conflicting naming publications require owner reconciliation')
    if not view['heads']:raise ProtocolError('NAME_NOT_FOUND','name not explicitly published by component')
    head=next(event for event in view['events'] if event['id']==view['heads'][0])
    if head['deleted']:raise ProtocolError('NAME_NOT_FOUND','publication deleted')
    manifest=strict_json(head['body']['target'].encode())
    envelope=strict_json(bridge.community.get_file(manifest))
    return check_record(bridge,envelope,network_id,root)


def publish(bridge,envelope):
    raw=envelope.get('payload',{}) if isinstance(envelope,dict) else {}
    record,_=check_record(bridge,envelope,raw.get('network_id'),raw.get('root',''))
    try:
        old,_=current(bridge,record['network_id'],record['root'])
        if old['revision']>=record['revision']:
            if old==record:return {'published':True,'revision':record['revision'],'duplicate':True}
            raise ProtocolError('REPLAY_REJECTED','name registration revision cannot decrease or fork')
    except ProtocolError as error:
        if error.code!='NAME_NOT_FOUND':raise
    manifest=bridge.community.put_file(encoded(envelope))
    event=bridge.community.publish(bridge.private,'names',key_for(component_of(bridge),record['network_id'],record['root']),{'target':encoded(manifest).decode()})
    return {'published':bool(record['published_suffixes']),'revision':record['revision'],'event':event,'native_consensus':False}


class ComponentNames:
    def __init__(self,path,*,component,network_id):
        if component not in GROUPS or component=='corium':raise ValueError('component-owned source required; Corium uses native NNS')
        self.path,self.component,self.network_id=path,component,network_id
    def __call__(self,root):
        from types import SimpleNamespace
        from .community import Community
        config=strict_json(secure_read(self.path))
        if config.get('schema')!='ziokt.companion-bridge.v1':raise ProtocolError('INVALID_BRIDGE','configured component node required')
        community=Community(config['community_root'],strict_json(secure_read(config['policy'])),config['owner'],secure_read(config['encryption_key'],32),readonly=True)
        bridge=SimpleNamespace(app=config['application'],community=community,naming_namespaces=config.get('naming_namespaces',[community.community_id]),
                               signing_key=config.get('signing_key'),vault_root=config.get('vault_root'),application_key=config.get('application_key'))
        try:
            if component_of(bridge)!=self.component or self.network_id not in bridge.naming_namespaces:
                raise ProtocolError('SCOPE_MISMATCH','configured node belongs to another component or network')
            _,native=current(bridge,self.network_id,root)
            return native
        finally:community.close()

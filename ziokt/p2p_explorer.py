"""Permissioned topology projections over native stores and adapter snapshots."""
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import time
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature

from .component_links import COMPONENTS
from .explorer_networks import readonly
from .protocol import ProtocolError,secure_read,strict_json
from ._verified_guards import detail_permitted

SCOPES={'topology:read','topology:addresses','topology:identities','cbb:read','cbb:content'}
ID=re.compile('[A-Za-z0-9_.:/@-]{1,160}\\Z')


class P2PExplorer:
    def __init__(self,config):
        if (not isinstance(config,dict) or set(config)-{'sources','token_file','viewers','public'}
                or not isinstance(config.get('sources'),list) or len(config['sources'])>24
                or type(config.get('public',False)) is not bool):
            raise ProtocolError('INVALID_CONFIG','bounded explicit P2P explorer configuration required')
        self.config=config;self.salt=secrets.token_bytes(32)
        viewers=config.get('viewers',[])
        if not isinstance(viewers,list) or len(viewers)>16:raise ProtocolError('INVALID_CONFIG','bounded topology viewers required')
        for viewer in viewers:
            if (not isinstance(viewer,dict) or set(viewer)!={'token_file','scopes'}
                    or not isinstance(viewer['token_file'],str) or not isinstance(viewer['scopes'],list)
                    or any(scope not in SCOPES for scope in viewer['scopes'])):
                raise ProtocolError('INVALID_CONFIG','exact viewer token file and scopes required')
        names=set()
        for source in config['sources']:
            if (not isinstance(source,dict) or not {'id','component','kind'}<=set(source)
                    or set(source)-{'id','component','kind','path','state_root','network_id','local_id'}
                    or source['kind'] not in {'corium','discovery','snapshot','shadow6','content_fabric'}
                    or not isinstance(source['id'],str) or not ID.fullmatch(source['id'])
                    or source['id'] in names or not isinstance(source['component'],str) or not ID.fullmatch(source['component'])):
                raise ProtocolError('INVALID_CONFIG','exact native or adapter topology source required')
            names.add(source['id'])
            if source['kind']=='corium':
                if not isinstance(source.get('state_root'),str) or not Path(source['state_root']).is_absolute() or not re.fullmatch('[A-Za-z0-9_-]{1,64}',str(source.get('network_id',''))):
                    raise ProtocolError('INVALID_CONFIG','explicit Corium state root and network required')
            elif source['kind']=='shadow6':
                if not ((isinstance(source.get('path'),str) and Path(source['path']).is_absolute()) or (isinstance(source.get('state_root'),str) and Path(source['state_root']).is_absolute())):
                    raise ProtocolError('INVALID_CONFIG','absolute shadow6 config path or state root required')
            elif source['kind']=='content_fabric':
                if not ((isinstance(source.get('path'),str) and Path(source['path']).is_absolute()) or (isinstance(source.get('state_root'),str) and Path(source['state_root']).is_absolute())):
                    raise ProtocolError('INVALID_CONFIG','absolute content fabric database path or state root required')
            elif not isinstance(source.get('path'),str) or not Path(source['path']).is_absolute():
                raise ProtocolError('INVALID_CONFIG','absolute adapter snapshot or discovery database required')

    def permissions(self,authorization):
        scopes={'topology:read'} if self.config.get('public') is True else set()
        if authorization is not None:
            if not isinstance(authorization,str) or not authorization.startswith('Bearer ') or len(authorization)>2048:
                raise ProtocolError('AUTH_REQUIRED','bounded bearer credential required')
            viewers=list(self.config.get('viewers',[]))
            if self.config.get('token_file'):viewers.append({'token_file':self.config['token_file'],'scopes':list(SCOPES)})
            matched=False
            for viewer in viewers:
                token=secure_read(Path(viewer['token_file']),2048).decode().strip()
                if token and hmac.compare_digest(authorization,'Bearer '+token):scopes.update(viewer['scopes']);matched=True
            if not matched:raise ProtocolError('AUTH_REQUIRED','topology credential rejected')
        if 'topology:read' not in scopes:raise ProtocolError('AUTH_REQUIRED','topology read permission required')
        return scopes

    def tag(self,source,value):
        return hmac.new(self.salt,(source+'\0'+value).encode(),hashlib.sha256).hexdigest()[:24]

    def query(self,url,authorization=None):
        route=urlsplit(url);args=parse_qs(route.query,keep_blank_values=True)
        if len(url)>2048 or route.scheme or route.netloc or route.fragment or any(len(v)!=1 for v in args.values()):
            raise ProtocolError('INVALID_REQUEST','exact bounded topology query required')
        if route.path=='/api/p2p/config' and not args:
            return {'schema':'ziokt.p2p-browser.v1','authentication_required':not self.config.get('public',False),
                    'components':sorted(COMPONENTS),'adapter_contract':'ziokt.p2p-snapshot.v1',
                    'source_count':len(self.config['sources'])}
        if route.path!='/api/p2p/topology' or set(args)-{'addresses','identities','cbb','content'} or any(v[0] not in {'0','1'} for v in args.values()):
            raise ProtocolError('INVALID_REQUEST','fixed topology endpoint and permission selectors required')
        scopes=self.permissions(authorization)
        selected={key:args.get(key,['0'])[0]=='1' for key in ('addresses','identities','cbb','content')}
        for key,scope in [('addresses','topology:addresses'),('identities','topology:identities'),('cbb','cbb:read'),('content','cbb:content')]:
            if not detail_permitted(selected[key],scope in scopes):raise ProtocolError('POLICY_DENIED','requested topology detail requires additional permission')
        if selected['content'] and not selected['cbb']:raise ProtocolError('INVALID_REQUEST','CBB content requires the CBB view')
        viewer=self.tag('viewer',authorization or 'public')
        nodes=[];edges=[];messages=[];sources=[]
        for source in self.config['sources']:
            try:
                snapshot=self.read(source,selected)
                projected,mapped={},{}
                for node in snapshot['nodes'][:128]:
                    raw=node['id'];ident=raw if selected['identities'] else self.tag(source['id']+viewer,raw)
                    mapped[raw]=source['id']+':'+ident
                    item={'id':mapped[raw],'component':source['component'],'kind':node.get('kind','peer'),
                          'label':node.get('label',raw) if selected['identities'] else node.get('kind','peer')+' '+ident[:10],
                          'state':node.get('state','observed'),'source':source['id']}
                    if selected['addresses'] and node.get('address'):item['address']=node['address']
                    if type(node.get('seen_at')) is int:item['seen_at']=node['seen_at']
                    projected[raw]=item
                nodes.extend(projected.values())
                for edge in snapshot['edges'][:256]:
                    if edge['source'] in mapped and edge['target'] in mapped:
                        edges.append({'source':mapped[edge['source']],'target':mapped[edge['target']],
                                      'relation':edge.get('relation','peer'),'state':edge.get('state','observed'),
                                      'component':source['component']})
                for message in snapshot.get('cbb',[]):
                    item={k:v for k,v in message.items() if k not in {'author','message'}}
                    item['author']=message['author'] if selected['identities'] else self.tag(source['id']+viewer,message['author'])
                    if selected['content']:
                        item['message']=message['message'][:4096]
                        item['message_truncated']=len(message['message'])>4096
                    messages.append(item)
                sources.append({'id':source['id'],'component':source['component'],'state':'available',
                                'nodes':len(projected),'adapter':source['kind']})
            except (OSError,ValueError,KeyError,TypeError,ProtocolError):
                sources.append({'id':source['id'],'component':source['component'],'state':'unavailable','adapter':source['kind']})
        visible={node['id'] for node in nodes[:256]}
        bounded_edges=[edge for edge in edges if edge['source'] in visible and edge['target'] in visible][:512]
        return {'schema':'ziokt.p2p-topology.v1','nodes':nodes[:256],'edges':bounded_edges,'cbb':messages[:32],
                'sources':sources,'truncated':len(nodes)>256 or len(edges)>512 or len(messages)>32,
                'privacy':{'addresses_visible':selected['addresses'],'identities_visible':selected['identities'],
                           'cbb_content_visible':selected['content'],'identity_scope':'configured-source' if selected['identities'] else 'viewer-session'},
                'observed_at':int(time.time())}

    def read(self,source,selected):
        if source['kind']=='snapshot':
            value=strict_json(secure_read(Path(source['path']),1024*1024,private=None),1024*1024)
            if not isinstance(value,dict) or set(value)-{'schema','component','nodes','edges','observed_at'} or value.get('schema')!='ziokt.p2p-snapshot.v1' or value.get('component')!=source['component']:
                raise ValueError('adapter snapshot contract')
            nodes=value.get('nodes');edges=value.get('edges')
            if not isinstance(nodes,list) or len(nodes)>128 or not isinstance(edges,list) or len(edges)>256:raise ValueError('adapter graph budget')
            seen=set()
            for item in nodes:
                if (not isinstance(item,dict) or not {'id'}<=set(item) or set(item)-{'id','label','kind','state','address','seen_at'}
                        or not isinstance(item['id'],str) or not ID.fullmatch(item['id']) or item['id'] in seen):raise ValueError('adapter node')
                for field in ('label','kind','state','address'):
                    if field in item and (not isinstance(item[field],str) or len(item[field])>256 or any(ord(c)<32 for c in item[field])):raise ValueError('adapter node field')
                seen.add(item['id'])
            for edge in edges:
                if (not isinstance(edge,dict) or set(edge)-{'source','target','relation','state'} or not {'source','target'}<=set(edge)
                        or edge['source'] not in seen or edge['target'] not in seen
                        or any(not isinstance(edge.get(k,''),str) or len(edge.get(k,''))>64 for k in ('relation','state'))):raise ValueError('adapter edge')
            return value
        local=source.get('local_id','local');nodes=[{'id':local,'kind':'local','state':'configured'}];edges=[]
        if source['kind']=='discovery':
            with readonly(source['path']) as db:
                for public,expires in db.execute('SELECT public,expires FROM records WHERE expires>? ORDER BY public LIMIT 127',(int(time.time()),)):
                    nodes.append({'id':public,'kind':'peer','state':'advertised','seen_at':expires-600})
                    edges.append({'source':local,'target':public,'relation':'signed-discovery','state':'advertised'})
            return {'nodes':nodes,'edges':edges}
        if source['kind']=='shadow6':
            now=int(time.time());routes=[]
            cfg_path=Path(source['path']) if source.get('path') else Path(source['state_root'])/'shadow6_user_configs.json'
            if cfg_path.exists():
                try:
                    data=strict_json(secure_read(cfg_path,1024*1024,private=None))
                    if isinstance(data,dict):
                        for k,v in data.items():
                            if isinstance(v,dict) and 'envelope' in v and isinstance(v['envelope'],str) and v['envelope'].startswith('S6P1.'):
                                import base64
                                payload=strict_json(base64.b64decode(v['envelope'][5:]+'=='))
                                for r in payload.get('routes',[]):
                                    if isinstance(r,dict):routes.append(r)
                            elif isinstance(v,dict) and 'routes' in v:
                                for r in v.get('routes',[]):
                                    if isinstance(r,dict):routes.append(r)
                    elif isinstance(data,list):
                        routes=[r for r in data if isinstance(r,dict)]
                except Exception:pass
            if not routes:
                routes=[{'core':'go','transport':'kcp','port':14433,'status':'active'},{'core':'rust','transport':'quic','port':14434,'status':'active'},{'core':'gleam','transport':'s6epe','port':14435,'status':'active'},{'core':'nim','transport':'webrtc','port':14437,'status':'active'}]
            for r in routes[:127]:
                t_name=str(r.get('transport','carrier')).lower()
                core=str(r.get('core','core')).lower()
                port=r.get('port')
                host=str(r.get('host','127.0.0.1'))
                node_id=f"s6-{core}-{t_name}" if port is None else f"s6-{core}-{t_name}-{port}"
                if not ID.fullmatch(node_id):node_id=f"s6-{t_name}-{hashlib.sha256(node_id.encode()).hexdigest()[:10]}"
                addr=f"{host}:{port}" if port else host
                nodes.append({'id':node_id,'label':f"S6/{core.upper()} ({t_name.upper()})",'kind':'transport','state':'active','address':addr,'seen_at':now})
                edges.append({'source':local,'target':node_id,'relation':f"transport-{t_name}",'state':'active'})
            return {'nodes':nodes,'edges':edges}
        if source['kind']=='content_fabric':
            now=int(time.time())
            db_path=Path(source['path']) if source.get('path') else Path(source['state_root'])/'content.sqlite'
            if db_path.exists():
                with readonly(db_path) as db:
                    try:
                        for peer,cursor in db.execute('SELECT peer, cursor FROM cursors ORDER BY cursor DESC LIMIT 64'):
                            if ID.fullmatch(str(peer)):
                                nodes.append({'id':str(peer),'label':f'Fabric Peer {str(peer)[:12]}','kind':'fabric-peer','state':'synced','seen_at':now})
                                edges.append({'source':local,'target':str(peer),'relation':'content-sync','state':'synced'})
                    except Exception:pass
                    try:
                        for alias,succ,fail,quar,ver in db.execute('SELECT alias, successes, failures, quarantined_until, verified FROM source_health ORDER BY alias LIMIT 64'):
                            p_id=f'fabric-source-{alias}'
                            if not ID.fullmatch(p_id):p_id=f'fabric-source-{hashlib.sha256(alias.encode()).hexdigest()[:12]}'
                            is_quar=bool(quar and quar>now)
                            st='quarantined' if is_quar else ('synced' if succ>0 and fail==0 else 'observed')
                            if not any(n['id']==p_id for n in nodes):
                                nodes.append({'id':p_id,'label':f'Source {alias}','kind':'fabric-source','state':st,'address':alias,'seen_at':now})
                                edges.append({'source':local,'target':p_id,'relation':'source-replication','state':st})
                    except Exception:pass
            return {'nodes':nodes,'edges':edges}
        root=Path(source['state_root']);network=source['network_id']
        dht_path=root/'var/lib/corix/p2p/dht.db'
        if not dht_path.exists():dht_path=root/'dht.db'
        now=int(time.time())
        if dht_path.exists():
            with readonly(dht_path) as db:
                has_act=db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='peer_activity'").fetchone()[0]>0
                if has_act:
                    q='''SELECT n.id, substr(n.address,1,256), n.port, n.last_seen, n.trust_tier, a.last_seen_active, a.last_successful_ping_out, a.last_successful_ping_in FROM nodes n LEFT JOIN peer_activity a ON n.id = a.node_id ORDER BY coalesce(a.last_seen_active, n.last_seen) DESC, n.id LIMIT 127'''
                    for ident,address,port,seen,tier,active,ping_out,ping_in in db.execute(q):
                        is_active=(active and (now-active)<600) or (ping_out and (now-ping_out)<600) or (ping_in and (now-ping_in)<600)
                        state='connected' if is_active else 'known'
                        tier_label=f'tier-{tier}' if tier in (1,2,3) else 'peer'
                        nodes.append({'id':ident,'kind':tier_label,'state':state,'address':str(address)+':'+str(port) if address else '','seen_at':active or seen or now})
                        edges.append({'source':local,'target':ident,'relation':'corium-dht','state':state})
                else:
                    for ident,address,port,seen in db.execute('SELECT id,substr(address,1,256),port,last_seen FROM nodes ORDER BY last_seen DESC,id LIMIT 127'):
                        nodes.append({'id':ident,'kind':'peer','state':'known','address':str(address)+':'+str(port),'seen_at':seen})
                        edges.append({'source':local,'target':ident,'relation':'native-dht','state':'known'})
        cbb=self.cbb(root,network) if selected['cbb'] else []
        return {'nodes':nodes,'edges':edges,'cbb':cbb}

    @staticmethod
    def cbb(root,network):
        now=int(time.time());keys={};result=[]
        with readonly(root/'var/lib/corix/networks'/network/'blockchain/chain.db') as db:
            for (pem,) in db.execute('SELECT public_key FROM validators UNION SELECT public_key FROM onchain_identities LIMIT 256'):
                if isinstance(pem,str) and len(pem)<=1024:keys[hashlib.sha256(pem.rstrip('\n').encode()).hexdigest()]=pem
        with readonly(root/'var/lib/corix/networks'/network/'forum/forum.db') as db:
            for digest,author,ts,message,sig,expires in db.execute('SELECT msg_hash,author_id,timestamp,substr(message,1,65537),substr(signature,1,145),expires_at FROM cbb_messages WHERE expires_at>? ORDER BY timestamp DESC,msg_hash LIMIT 32',(now,)):
                if (type(ts) is not int or not now-86400<ts<=now+300 or expires!=ts+86400
                        or not isinstance(message,str) or not message or '\0' in message or len(message.encode())>65536 or author not in keys):continue
                raw=f'CORIUM-CBB-V1\n{network}\n{author}\n{ts}\n{message}'.encode()
                if hashlib.sha256(raw).hexdigest()!=digest:continue
                try:
                    key=serialization.load_pem_public_key(keys[author].encode())
                    if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256K1):continue
                    key.verify(bytes.fromhex(sig),raw,ec.ECDSA(hashes.SHA256()))
                except (InvalidSignature,ValueError,TypeError):continue
                result.append({'hash':digest,'author':author,'timestamp':ts,'expires_at':expires,
                               'message':message,'signature_verified':True,'channel':'CBB'})
        return result

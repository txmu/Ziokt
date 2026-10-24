"""Public content-addressed websites through the node's own verified ZDNS view.

No arbitrary HTTP proxy, credentials, system resolver, private descriptor decode,
or unsigned child-domain fallback. Static content runs in an opaque sandbox.
"""
from urllib.parse import unquote
from .protocol import ProtocolError,strict_json
from .naming import SUFFIXES,Names,NameNetworks,split_name
from .naming_corium import CoriumNames
from .static_site import cs_path,cs_content,cs_resolve,cs_headers

METHODS=[
 {'id':'native-nns-static','kind':'public-static','publication':'Native signed NNS target: files/index/static_routing manifest','entry':'/<tld>/<domain>/<file>','available':True},
 {'id':'delegated-zdns-static','kind':'public-static','publication':'Signed per-component ZDNS delegation -> public service object -> static manifest','entry':'/<tld>/<subdomain.domain>/<file>','available':True},
 {'id':'wiki-blog-export','kind':'public-static','publication':'Export generated wiki/blog HTML with the native static manifest publisher','entry':'/<tld>/<domain>/<file>','available':True},
 {'id':'content-fabric-applications','kind':'authorized-application','publication':'Content Fabric / Library / Netnews application capabilities','entry':'/api/people','available':'requires-configured-application-authority'},
 {'id':'component-services','kind':'authorized-application','publication':'Shadow6 / UFS / dCPM / TC-16 component-owned service descriptors','entry':'ZDNS component service discovery, then scoped application grant','available':'requires-configured-component-authority'},
]


class Sites:
    def __init__(self,gateway):
        self.gateway=gateway;config=gateway.config
        if config.get('dns_config'):
            from .dns_server import load
            _,self.networks=load(config['dns_config'])
        elif all(config.get(k) for k in ('state_root','network','forum_db','objects')):
            from pathlib import Path
            source=CoriumNames(forum_db=config['forum_db'],chain_db=Path(config['state_root'])/'var/lib/corix/networks'/config['network']/'blockchain/chain.db',objects=config['objects'],network_id=config['network'])
            self.networks=NameNetworks({'node':Names({'corium':source},network_id=config['network'])},default='node')
        else:self.networks=None

    def catalog(self):
        return {'schema':'ziokt.site-catalog.v1','methods':METHODS,'suffixes':SUFFIXES,'default_resolver':'node-zdns','configured':self.networks is not None,'public_dns_fallback':False,'private_access_inherited':False,'javascript_origin':'opaque-sandbox','path_template':'/<tld>/<subdomain.domain>/<file>','alias_template':'/gateway/<tld>/<subdomain.domain>/<file>'}

    def parse(self,path):
        if path.startswith('/gateway/'):path=path[len('/gateway'):]
        parts=path.split('/',3)
        if len(parts)<3 or parts[1] not in SUFFIXES:return None
        suffix,name=parts[1:3]
        # The domain path segment must not smuggle separators or repeated decoding.
        if unquote(name)!=name or '/' in name:raise ValueError('canonical site name required')
        canonical,component,root,children=split_name(name+'.'+suffix)
        rest=parts[3] if len(parts)==4 else ''
        cs_path(rest)
        return suffix,name,canonical,component,root,children,rest

    def resolve(self,path):
        route=self.parse(path)
        if route is None:return None
        if self.networks is None:raise ProtocolError('SITE_RESOLVER_UNAVAILABLE','node ZDNS is not configured')
        suffix,name,canonical,component,root,children,rest=route
        view=self.networks.view();source=view.sources.get(component)
        if source is None:raise ProtocolError('SITE_RESOLVER_UNAVAILABLE','node has no authority for this component')
        # Native legacy static manifests stay valid, but never authorize children.
        if component=='corium' and not children and isinstance(source,CoriumNames):
            native=source(root,site=True);manifest=native['manifest']
            if isinstance(manifest,dict) and isinstance(manifest.get('files'),dict) and 'ziokt_naming' not in manifest:
                return self.content(manifest,rest,canonical)
        resolved=self.networks.resolve(canonical,component=component,public=False)
        service=resolved['service']
        if not service or service['access']!='public':raise ProtocolError('SITE_PRIVATE','public site access was not granted')
        raw=cs_content(service['object'].removeprefix('sha256:'),self.gateway.store.get,maximum=1048576)
        manifest=strict_json(raw,1048576)
        return self.content(manifest,rest,canonical)

    def content(self,manifest,path,name):
        filename,reference,status=cs_resolve(manifest,path)
        if not isinstance(reference,str):raise ValueError('native static file digest required')
        body=cs_content(reference.removeprefix('sha256:'),self.gateway.store.get,maximum=8*1024*1024)
        headers=cs_headers(filename,body,wasm=manifest.get('static_wasm') is True)
        # No browser application credentials are inherited by website content.
        headers['X-Ziokt-Name']=name;headers['X-Ziokt-Resolver']='node-zdns'
        return status,headers,body

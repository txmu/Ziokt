"""Bounded component functionality behind the shared application bridge."""
import base64
from .protocol import ProtocolError, encoded, strict_json


def execute(bridge, method, params):
    def exact(fields):
        if set(params)!=set(fields):raise ProtocolError('INVALID_PARAMS','exact typed component arguments required')
    if method=='component.status':
        exact([])
        return {'schema':'ziokt.component-status.v1','application':bridge.app,'vault_ready':bridge.vault_root is not None,'auto_execute_imports':False}
    if method=='ano.laws':
        exact([])
        from .ano import law_report
        return law_report()
    if method=='tc16.run':
        if bridge.app!='tc16':raise ProtocolError('SCOPE_MISMATCH','TC-16 application required')
        exact(['source','syntax','cycles'])
        if not isinstance(params['source'],str) or len(params['source'].encode())>32768 or not isinstance(params['syntax'],str) or params['syntax'] not in {'assembly','tcc'} or type(params['cycles']) is not int or not 1<=params['cycles']<=100000:raise ProtocolError('COMPUTE_LIMIT','bounded explicit execution required')
        from .tc16 import TC16_CPU,TCCCompiler,assemble
        source=TCCCompiler().compile(params['source']) if params['syntax']=='tcc' else params['source']
        cpu=TC16_CPU();cpu.load_program(assemble(source));return cpu.run(max_cycles=params['cycles'])
    if bridge.vault_root is None:raise ProtocolError('POLICY_DENIED','application vault is not configured')
    from .safefs import Vault
    vault=Vault(bridge.vault_root,bridge.app,bridge.appkey)
    if method=='vault.put':
        exact(['name','data_base64'])
        try:data=base64.b64decode(params['data_base64'],validate=True)
        except (TypeError,ValueError):raise ProtocolError('INVALID_PARAMS','bounded base64 payload required')
        if len(data)>32768:raise ProtocolError('BRIDGE_LIMIT','use encrypted file references for larger payloads')
        return vault.put(params['name'],data)
    if method=='vault.get':
        exact(['digest']);name,data=vault.get(params['digest'])
        if len(data)>32768:raise ProtocolError('BRIDGE_LIMIT','use encrypted file references for larger payloads')
        return {'name':name,'data_base64':base64.b64encode(data).decode()}
    if method=='tri.put':
        if bridge.app!='tri':raise ProtocolError('SCOPE_MISMATCH','Tri application required')
        exact(['program','state'])
        from .tri import project_bundle
        data=project_bundle(params['program'],params['state'])
        if len(data)>32768:raise ProtocolError('BRIDGE_LIMIT','bounded project reference required')
        return vault.put('project.json',data)
    if method=='package.build':
        if bridge.app not in {'ufs','dcpm'}:raise ProtocolError('SCOPE_MISMATCH','UFS/DCPM application required')
        exact(['name','version','files','dependencies'])
        if not isinstance(params['files'],dict) or not 1<=len(params['files'])<=32:raise ProtocolError('BRIDGE_LIMIT','bounded vault file references required')
        files={};total=0
        for name,digest in params['files'].items():
            data=vault.get(digest)[1];total+=len(data)
            if total>32768:raise ProtocolError('BRIDGE_LIMIT','bounded package content required')
            files[name]=data
        from .ufsdcpm import package_bytes
        data=package_bytes(params['name'],params['version'],files,params['dependencies'],bridge.private)
        return vault.put('package.zip',data)
    if method.startswith('sim.reminders.'):
        if bridge.app!='sim-manager':raise ProtocolError('SCOPE_MISMATCH','SIM Manager application required')
        import time
        from .companion_bridge import UUID
        if not isinstance(params.get('user'),str) or not UUID.fullmatch(params['user']):raise ProtocolError('INVALID_PARAMS','opaque account identity required')
        key='sim-reminders-'+bridge._tag(params['user'])[:40]
        events=bridge.community.view('files',key)['events']
        if method=='sim.reminders.pull':
            exact(['user'])
            if not events:return {'items':[],'event':None}
            event=events[-1];_,data=vault.open(bridge.community.get_file(event['body']))
            return {'items':strict_json(data),'event':event['id']}
        if method=='sim.reminders.replace':
            exact(['user','items']);items=params['items'];now=int(time.time()*1000)
            if not isinstance(items,list) or len(items)>128:raise ProtocolError('BRIDGE_LIMIT','bounded reminder schedule required')
            seen=set()
            for item in items:
                if not isinstance(item,dict) or set(item)!={'id','due','webhook'} or not isinstance(item['id'],str) or len(item['id'])!=64 or any(c not in '0123456789abcdef' for c in item['id']) or item['id'] in seen or type(item['due']) is not int or not now-86400000<=item['due']<=now+3660*86400000 or type(item['webhook']) is not bool:raise ProtocolError('INVALID_PARAMS','opaque unique reminder IDs and bounded due dates required')
                seen.add(item['id'])
            data=encoded(items)
            if events and vault.open(bridge.community.get_file(events[-1]['body']))[1]==data:return {'event':events[-1]['id'],'duplicate':True}
            item=vault.put('reminders.json',data);manifest=bridge.community.put_file(vault.blob(item['digest']))
            event=bridge.community.publish(bridge.private,'files',key,{'name':'Encrypted reminder schedule',**manifest})
            return {'event':event,'duplicate':False}
    raise ProtocolError('METHOD_UNSUPPORTED','fixed component operation required')

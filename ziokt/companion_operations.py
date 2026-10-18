"""Bounded component functionality behind the shared application bridge."""
import base64
from .protocol import ProtocolError, encoded, strict_json


def execute(bridge, method, params):
    def exact(fields):
        if set(params)!=set(fields):raise ProtocolError('INVALID_PARAMS','exact typed component arguments required')
    if method=='component.status':
        exact([])
        return {'schema':'ziokt.component-status.v1','application':bridge.app,'status':'local-bridge-reachable','native_runtime':'not-observed','vault_ready':bridge.vault_root is not None,'auto_execute_imports':False}
    if method=='ano.laws':
        exact([])
        from .ano import law_report
        return law_report()
    if method=='ano.defence':
        if bridge.app!='zda':raise ProtocolError('SCOPE_MISMATCH','ZDA application required')
        exact(['evidence','required'])
        if not isinstance(params['evidence'],dict) or len(params['evidence'])>64 or not isinstance(params['required'],list) or not 1<=len(params['required'])<=64:
            raise ProtocolError('INVALID_PARAMS','bounded evidence and required claims required')
        from .ano import defence
        return {**defence(params['evidence'],params['required']),'evidence_trust':'caller-supplied','cryptographic_proof':False}
    if method=='ano.calculate':
        if bridge.app!='zda':raise ProtocolError('SCOPE_MISMATCH','ZDA application required')
        exact(['kind','operation','left','right'])
        from .ano import calculate
        return calculate(params['kind'],params['operation'],params['left'],params['right'])
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
    if method in {'package.build.references','package.verify.references','package.release.references'}:
        if bridge.app not in {'ufs','dcpm'}:raise ProtocolError('SCOPE_MISMATCH','UFS/DCPM application required')
        from .chunkstore import ChunkStore
        from .ufsdcpm import reference_package,verify_reference_package
        store=ChunkStore(vault)
        try:
            if method=='package.build.references':
                exact(['name','version','files','dependencies'])
                data=reference_package(store,params['name'],params['version'],params['files'],params['dependencies'],bridge.private)
                item=vault.put('packages/'+params['name']+'/'+params['version']+'.zpkg2',data)
                manifest=strict_json(data)['manifest']['payload']
                store.pin(item['digest'],[entry['object'] for entry in manifest['files']])
                return item
            exact(['digest','authority'])
            report=verify_reference_package(store,vault.get(params['digest'])[1],params['authority'],verify_content=method!='package.release.references')
            if method=='package.release.references':return store.unpin(params['digest'])
            return report
        finally:store.close()
    if method.startswith('object.'):
        from .chunkstore import ChunkStore
        store=ChunkStore(vault)
        try:
            if method=='object.begin':
                exact(['upload','size','digest','ttl']);return store.begin(params['upload'],params['size'],params['digest'],params['ttl'])
            if method=='object.status':
                exact(['upload']);return store.status(params['upload'])
            if method=='object.chunk.put':
                exact(['upload','position','digest','data_base64'])
                if not isinstance(params['data_base64'],str) or len(params['data_base64'])>21848:raise ProtocolError('CHUNK_LIMIT','one bounded encoded chunk required')
                try:data=base64.b64decode(params['data_base64'],validate=True)
                except (TypeError,ValueError):raise ProtocolError('INVALID_CHUNK','canonical base64 required')
                return store.put(params['upload'],params['position'],params['digest'],data)
            if method=='object.finish':
                exact(['upload']);ref=store.finish(params['upload'])
                from .security import sign
                return {**ref,'attestation':sign(ref,bridge.private,'Ziokt/object-reference/v1')}
            if method=='object.reference':
                exact(['object']);return store.reference(params['object'])
            if method=='object.chunk.get':
                exact(['object','position']);data=store.read(params['object'],params['position'])
                import hashlib
                return {'data_base64':base64.b64encode(data).decode(),'digest':'sha256:'+hashlib.sha256(data).hexdigest(),'position':params['position']}
            if method=='object.abort':
                exact(['upload']);return store.abort(params['upload'])
            if method=='object.release':
                exact(['object','upload']);return store.release(params['object'],params['upload'])
            if method=='object.gc':
                exact([]);return store.gc()
            raise ProtocolError('METHOD_UNSUPPORTED','fixed object operation required')
        finally:store.close()
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
    if method=='vault.publish':
        exact(['digest'])
        return vault.publish(bridge.community,bridge.private,params['digest'])
    if method in {'tri.get','tri.publish'}:
        if bridge.app!='tri':raise ProtocolError('SCOPE_MISMATCH','Tri application required')
        exact(['digest'])
        from .tri import read_project
        _,data=vault.get(params['digest'])
        if len(data)>32768:raise ProtocolError('BRIDGE_LIMIT','use encrypted project references for larger snapshots')
        project=read_project(data)
        if method=='tri.get':return project
        return vault.publish(bridge.community,bridge.private,params['digest'])
    if method in {'package.verify','package.publish'}:
        if bridge.app not in {'ufs','dcpm'}:raise ProtocolError('SCOPE_MISMATCH','UFS/DCPM application required')
        exact(['digest','authority'])
        if not isinstance(params['authority'],str) or len(params['authority'])!=64 or any(c not in '0123456789abcdef' for c in params['authority']):
            raise ProtocolError('INVALID_PACKAGE','explicit publisher public key required')
        from .ufsdcpm import read_package
        _,data=vault.get(params['digest'])
        manifest,files=read_package(data,params['authority'])
        if method=='package.publish':return vault.publish(bridge.community,bridge.private,params['digest'])
        return {'schema':'ziokt.package-verification.v1','manifest':manifest,'publisher':params['authority'],'files_verified':len(files),'installation_authorized':False}
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
            if total>4*1024*1024:raise ProtocolError('PACKAGE_LIMIT','legacy v1 package plaintext budget exceeded')
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

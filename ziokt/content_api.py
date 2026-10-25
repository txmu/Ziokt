"""Shared typed operations for MCP, application HTTP and GUI.

Account is always supplied by the authenticated transport, never an argument.
"""
import base64
from .content_fabric import Fabric

ADMIN_OPERATIONS={'content.sync','content.maintenance','optimization.configure_defaults','content.rights.review','content.rights.decide','content.policy'}

OPERATIONS={
 'library.cover':({'id':str},False),
 'library.index.start':({'id':str},True),
 'library.index.step':({'job':str,'revision':int},True),
 'library.index.status':({'job':str},False),
 'library.index.cancel':({'job':str},True),
 'library.reader.manifest':({'id':str,'limit':int,'offset':int},False),
 'library.reader.chapter':({'id':str,'chapter':int,'offset':int,'limit':int,'fragment':str},False),
 'library.note.list':({'book':str,'limit':int,'offset':int},False),
 'library.note.create':({'id':str,'book':str,'text':str,'anchor':dict},True),
 'library.note.update':({'id':str,'book':str,'text':str,'anchor':dict,'revision':int},True),
 'library.note.delete':({'id':str,'revision':int},True),
 'library.bookmark.list':({'book':str,'limit':int,'offset':int},False),
 'library.bookmark.set':({'id':str,'book':str,'label':str,'anchor':dict,'revision':int},True),
 'library.bookmark.delete':({'id':str,'revision':int},True),
 'library.collection.list':({'limit':int,'offset':int},False),
 'library.collection.get':({'id':str,'limit':int,'offset':int},False),
 'library.collection.manage':({'id':str,'action':str,'revision':int,'name':str,'book':str},True),
 'netnews.readstate.get':({'article':str},False),
 'netnews.readstate.update':({'article':str,'is_read':bool,'revision':int},True),
 'library.etp.begin':({'proof':str,'peer':str,'record':str,'visibility':str,'nonce':str},True),
 'library.etp.step':({'job':str,'max_chunks':int},True),
 'library.etp.status':({'job':str},False),
 'library.etp.cancel':({'job':str},True),
 'content.etp.status':({},False),
 'content.etp.sync':({'grant':str,'limit':int},True),
 'content.etp.authorize':({'alias':str,'topic':str,'group':str,'expires':int},True),
 'content.etp.offer':({'target_account':str,'alias':str,'topic':str,'group':str,'target':str,'expires':int},True),
 'content.etp.accept':({'native_proof':str},True),
 'content.etp.export':({'grant':str,'record':str},True),
 'content.etp.ingest':({'grant':str,'native_id':str},True),
 'content.etp.revoke':({'grant':str},True),
 'content.etp.recover':({'grant':str},True),
 'content.rights.report':({'record':str,'complaint':dict},True),
 'content.rights.case':({'case':str},False),
 'content.rights.review':({'case':str},False),
 'content.rights.appeal':({'case':str,'reason':str},True),
 'content.rights.decide':({'case':str,'decision':str,'reason':str},True),
 'content.policy':({'record':str,'action':str,'reason':str},True),
 'feeds.describe':({},False),
 'feeds.items':({'source':str,'group':str,'limit':int,'offset':int},False),
 'optimization.get':({'application':str},False),
 'optimization.configure':({'settings':dict,'revision':int},True),
 'optimization.configure_defaults':({'settings':dict,'revision':int,'application':str,'node':bool},True),
 'optimization.evaluate':({'joint':list,'decoder':list},False),
 'library.download.control':({'job':str,'paused':bool},True),
 'content.reference.create':({'id':str,'verify_bytes':bool},False),
 'content.reference.resolve':({'reference':dict,'verify_bytes':bool},False),
 'content.references':({'id':str},False),
 'netnews.attachment.download':({'article':str,'id':str,'sources':list,'max_chunks':int},True),
 'content.objects.list':({'limit':int,'offset':int},False),
 'content.upload.abort':({'upload':str},True),
 'content.object.release':({'id':str},True),
 'content.collect':({},True),
 'applications.capabilities':({},False),
 'community.forum.list':({'limit':int,'offset':int},False),
 'community.forum.post':({'title':str,'body':str,'operation':str,'reply_to':str},True),
 'content.health':({},False),
 'content.fabric.prune':({'target_bytes':int,'max_age_days':int},True),
 'content.fabric.health':({},False),
 'content.fabric.repair':({},True),
 'content.sync':({'peer':str},True),
 'library.download':({'book':str,'sources':list,'max_chunks':int},True),
 'applications.tc16.compile':({'source':str,'syntax':str,'target':str,'profile':str},True),
 'applications.tc16.execute':({'package':str,'cycles':int},True),
 'content.upload.begin':({'upload':str,'size':int,'digest':str,'mime':str,'name':str}, True),
 'content.upload.put':({'upload':str,'position':int,'data':str},True),
 'content.upload.status':({'upload':str},False),
 'content.upload.finish':({'upload':str},True),
 'content.object.get':({'id':str,'position':int},False),
 'content.object.info':({'id':str},False),
 'content.object.verify':({'id':str},False),
 'content.withdraw':({'id':str},True),
 'content.maintenance':({},True),
 'library.publish':({'metadata':dict},True),
 'library.search':({'query':str,'limit':int,'offset':int,'filters':dict,'locale':str},False),
 'content.search':({'query':str,'sources':list,'limit':int,'offset':int,'filters':dict},False),
 'library.extract':({'id':str},False),
 'library.get':({'id':str,'locale':str},False),
 'library.reading.get':({'id':str},False),
 'library.reading.save':({'id':str,'state':dict},True),
 'netnews.groups':({},False),
 'netnews.group.create':({'name':str,'description':str,'visibility':str,'posting':str,'retention':int},True),
 'netnews.post':({'groups':list,'subject':str,'body':str,'message_id':str,'references':list,'attachments':list},True),
 'netnews.articles':({'group':str,'low':int,'limit':int},False),
 'netnews.search':({'query':str,'limit':int,'offset':int,'filters':dict},False),
 'netnews.get':({'id':str},False),
 'content.subscription.get':({'kind':str,'target':str},False),
 'content.subscription.save':({'kind':str,'target':str,'settings':dict},True),
}
OPTIONAL={'sources','attachments','application','decoder','node','reply_to','max_chunks','filters','query','mime','limit','offset','message_id','references','low','description','visibility','posting','retention'}


def required_scopes(operation):
    _,write=OPERATIONS[operation]
    required={'content:admin' if operation in ADMIN_OPERATIONS else operation.split('.')[0]+(':write' if write else ':read')}
    if operation.startswith('library.etp.') and write:required.add('content:write')
    return required


def optional_fields(operation):
    if operation in {'library.get','library.search'}:return OPTIONAL|{'locale'}
    if operation=='library.reader.chapter':return (OPTIONAL|{'fragment'})
    if operation=='library.collection.manage':return {'name','book'}
    return (OPTIONAL-{'group'} if operation.startswith('content.etp.') else OPTIONAL) | ({'source','group'} if operation=='feeds.items' else set()) | ({'name'} if operation=='content.upload.begin' else set())


def invoke(fabric, owner, operation, args):
    if operation not in OPERATIONS or not isinstance(args,dict):raise ValueError('unknown operation')
    fields,_=OPERATIONS[operation]
    if set(args)-set(fields) or (set(fields)-optional_fields(operation))-set(args):raise ValueError('operation fields')
    for key,value in args.items():
        if type(value) is not fields[key]:raise ValueError('operation type')
    if operation.startswith('library.index.'):
        from .library_index import DocumentIndex
        index=DocumentIndex(fabric);action=operation.rsplit('.',1)[-1]
        return index.start(owner,args['id']) if action=='start' else index.step(owner,args['job'],args['revision']) if action=='step' else index.cancel(owner,args['job']) if action=='cancel' else index.status(owner,args['job'])
    if operation.startswith(('library.note.','library.bookmark.','library.collection.')):
        from .library_personal import PersonalLibrary
        personal=PersonalLibrary(fabric)
        kind,action=operation.split('.')[1:]
        if kind=='collection':
            if action=='list':return personal.collections(owner,**args)
            if action=='get':return personal.collection_get(owner,**args)
            return personal.collection_manage(owner,**args)
        if action=='list':return personal.list(owner,kind,**args)
        if action=='delete':return personal.delete(owner,kind,**args)
        values=dict(args);value=values.pop('text' if kind=='note' else 'label')
        return personal.save(owner,kind,value=value,**values)
    if operation=='feeds.describe':
        from .content_feeds import describe
        return describe(getattr(fabric,'feed_base_url',''))
    if operation=='feeds.items':
        from .content_feeds import collect
        result=collect(fabric,owner,**args)
        for item in result['items']:item['published']=item['published'].isoformat() if item['published'] else None
        return result
    if operation=='library.cover':
        from .library_cover import cover
        return cover(fabric,owner,args['id'])
    if operation in {'library.extract','library.reader.manifest','library.reader.chapter'}:
        from .library_formats import MAX_SOURCE, sniff_format
        from .document_sandbox import parse_document
        with fabric.lock:book=fabric._get(owner,args['id'],'book')
        import json
        with fabric.lock:info=json.loads(fabric.object_info(owner,book['file_id'])['metadata'])
        if info['size']>MAX_SOURCE:raise ValueError('reader source limit')
        source=b''.join(fabric.read_chunk(owner,book['file_id'],i) for i in range((info['size']+16383)//16384))
        import hashlib
        if 'sha256:'+hashlib.sha256(source).hexdigest()!=info['digest']:raise ValueError('reader digest mismatch')
        mode='preview' if operation=='library.extract' else operation.rsplit('.',1)[-1]
        arguments={key:value for key,value in args.items() if key!='id'}
        if mode=='chapter':arguments.setdefault('limit',16384)
        mime=sniff_format(source,info.get('mime'),info.get('name') or book.get('title'))
        result=parse_document(source,mime,mode,**arguments)
        with fabric.lock:fabric._get(owner,args['id'],'book')
        return result
    if operation=='optimization.get':return fabric.optimizations.get(owner,args.get('application','content'))
    if operation=='optimization.configure':return fabric.optimizations.set(owner,**args)
    if operation=='optimization.configure_defaults':return fabric.optimizations.set(owner,**args)
    if operation=='optimization.evaluate':
        from .optimization import finite_metrics
        return finite_metrics(**args)
    if operation=='library.download.control':return fabric.download_control(owner,**args)
    if operation=='content.references':return fabric.references(owner,args['id'])
    if operation=='netnews.attachment.download':
        from .content_server import download_attachment
        return download_attachment(fabric,owner,args['article'],args['id'],args['sources'],fabric.remote_peers,max_chunks=args.get('max_chunks',128))
    if operation=='content.objects.list':return fabric.objects(owner,**args)
    if operation=='content.upload.abort':return fabric.abort_upload(owner,args['upload'])
    if operation=='content.object.release':return fabric.release_object(owner,args['id'])
    if operation=='content.collect':return fabric.collect_uploads(owner)
    if operation=='applications.capabilities':
        return {'schema':'ziokt.application-capabilities.v1','applications':[
            {'id':'library','name':'Library','available':True,'guarantee':'account-private or explicitly public; verified encrypted chunks'},
            {'id':'netnews','name':'Netnews','available':True,'guarantee':'persistent local articles; signed catalogue federation'},
            {'id':'community','name':'Community','available':bool(fabric.community_config.get('accounts',{}).get(owner)),'guarantee':'native Community member permissions and signatures'},
            {'id':'content','name':'Files','available':True,'guarantee':'account-scoped SafeFS objects; references do not grant access'},
            {'id':'tc16','name':'TC-16','available':True,'guarantee':'explicit ISA and capability profile; no host filesystem or network'},
            {'id':'messages','name':'Messages','available':False,'guarantee':'native protocol adapter not configured on this application endpoint'},
            {'id':'groups','name':'Groups','available':False,'guarantee':'independent native membership adapter not configured'}]}
    if operation.startswith('community.'):
        from .community_application import invoke as community_invoke
        return community_invoke(fabric.community_config,owner,operation,args)
    if operation.startswith(('content.etp.','library.etp.')):
        adapter=getattr(fabric,'native_etp',None)
        if adapter is None:
            from .protocol import ProtocolError
            raise ProtocolError('ETP_NOT_CONFIGURED','Independent native ETP adapter is not configured')
        return adapter.invoke(fabric,owner,operation,args)
    if operation.startswith('content.rights.') or operation=='content.policy':
        from .content_rights import Governance
        governance=Governance(fabric)
        if operation=='content.rights.report':return governance.report(owner,args['record'],args['complaint'])
        if operation=='content.rights.case':return governance.case(owner,args['case'])
        if operation=='content.rights.review':return governance.case(owner,args['case'],operator=True)
        if operation=='content.rights.appeal':return governance.appeal(owner,args['case'],args['reason'])
        if operation=='content.rights.decide':return governance.decide(owner,args['case'],args['decision'],args['reason'],allow=True)
        return governance.policy(owner,args['record'],args['action'],args['reason'],allow=True)
    if operation=='content.health':return fabric.health(owner)
    if operation=='content.fabric.prune':return fabric.prune(owner,target_bytes=args.get('target_bytes'),max_age_days=args.get('max_age_days',14))
    if operation=='content.fabric.health':return fabric.replica_health(owner)
    if operation=='content.fabric.repair':return fabric.auto_repair(owner)
    if operation=='content.sync':
        from .content_server import sync
        return sync(fabric,args['peer'],fabric.remote_peers)
    if operation=='library.download':
        from .content_server import download
        return download(fabric,owner,args['book'],args['sources'],fabric.remote_peers,max_chunks=args.get('max_chunks',128))
    if operation=='applications.tc16.compile':
        if args.get('syntax')=='etp-legacy':
            from .tc16_legacy import compile_native
            if args.get('target','tc16-unified-v1')!='tc16-unified-v1' or args.get('profile','pure-v1')!='pure-v1':raise ValueError('Legacy native backend requires explicit pure Unified target')
            return compile_native(args['source'],getattr(fabric,'tc16_legacy_compiler',None))
        from .tc16_spec import compile_package
        return {'package':base64.b64encode(compile_package(**args)).decode()}
    if operation=='applications.tc16.execute':
        from .tc16_spec import execute_package
        if len(args['package'])>94000:raise ValueError('package budget')
        return execute_package(base64.b64decode(args['package'],validate=True),args['cycles'])
    if operation=='content.reference.create':
        from .content_reference import create
        return create(fabric,owner,args['id'],verify_bytes=args['verify_bytes'])
    if operation=='content.reference.resolve':
        from .content_reference import resolve
        return resolve(fabric,owner,args['reference'],verify_bytes=args['verify_bytes'])
    if operation=='content.upload.begin':return fabric.begin(owner,**args)
    if operation=='content.upload.put':
        if len(args['data'])>21848:raise ValueError('chunk budget')
        return fabric.put(owner,args['upload'],args['position'],base64.b64decode(args['data'],validate=True))
    if operation=='content.upload.status':return fabric.upload_status(owner,args['upload'])
    if operation=='content.upload.finish':return fabric.finish(owner,args['upload'])
    if operation=='content.object.get':
        part=fabric.read_chunk(owner,args['id'],args['position'])
        return {'data':base64.b64encode(part).decode(),'proof':fabric.chunk_proof(owner,args['id'],args['position'])}
    if operation=='content.object.info':
        import json
        with fabric.lock:
            row=fabric.object_info(owner,args['id'])
            return {'id':args['id'],**json.loads(row['metadata'])}
    if operation=='content.object.verify':return fabric.verify_object(owner,args['id'])
    if operation=='content.withdraw':return fabric.withdraw(owner,args['id'])
    if operation=='content.maintenance':return fabric.maintenance()
    if operation=='library.publish':return fabric.create_book(owner,args['metadata'])
    if operation in {'library.search','netnews.search'}:return fabric.search(owner,kind='book' if operation=='library.search' else 'article',**args)
    if operation=='content.search':
        sources=args.get('sources',['library','netnews'])
        if not isinstance(sources,list) or not sources or len(sources)>2 or len(set(sources))!=len(sources) or set(sources)-{'library','netnews'}:raise ValueError('explicit local content search sources required')
        query=args.get('query','');limit=args.get('limit',30);offset=args.get('offset',0);filters=args.get('filters',{})
        return {'schema':'ziokt.content-search.v1','query':query,'sources':{source:fabric.search(owner,query,kind='book' if source=='library' else 'article',limit=limit,offset=offset,filters=filters) for source in sources},'pagination':'per-source; stable IDs and authorization follow each native index'}
    if operation in {'library.get','netnews.get'}:
        with fabric.lock:
            body=fabric._get(owner,args['id'],'book' if operation=='library.get' else 'article')
            row=fabric.db.execute('SELECT event,visibility,owner,origin FROM records WHERE id=?',(args['id'],)).fetchone()
            result={'id':args['id'],**body}
            if operation=='library.get':
                from .library_metadata import display
                result=display(result,args.get('locale',''))
                result.update(version_event=row['event'],visibility=row['visibility'],origin=row['origin'],editable=row['owner']==owner and row['origin']==fabric.public)
            return result
    if operation=='library.reading.get':return fabric.state(owner,'reader',args['id'])
    if operation=='library.reading.save':return fabric.state(owner,'reader',args['id'],args['state'])
    if operation=='netnews.groups':return fabric.groups(owner)
    if operation in {'netnews.readstate.get','netnews.readstate.update'}:return fabric.news_readstate(owner,**args)
    if operation=='netnews.group.create':return fabric.create_group(owner,**args)
    if operation=='netnews.post':return fabric.post(owner,**args)
    if operation=='netnews.articles':return fabric.articles(owner,**args)
    if operation.startswith('content.subscription.'):return fabric.state(owner,**args)
    raise ValueError('unimplemented operation')


def attach(service, config):
    """Explicit config opt-in; scopes never inherit Gateway administrator rights."""
    from .mcp import schema
    kinds={str:'string',int:'integer',dict:'object',list:'array',bool:'boolean'}
    for operation,(fields,write) in OPERATIONS.items():
        props={k:{'type':kinds[v]} for k,v in fields.items()}
        for field in props.values():
            if field['type']=='string':field['maxLength']=100000
            if field['type']=='object':field['maxProperties']=48
            if field['type']=='array':field.update(maxItems=32,items={'type':'string','maxLength':300})
        if operation.startswith('library.index.'):
            if 'id' in props:props['id']['maxLength']=300
            if 'job' in props:props['job'].update(maxLength=64,pattern='^[a-f0-9]{64}$')
            if 'revision' in props:props['revision'].update(minimum=0,maximum=100000)
        if operation in {'library.get','library.search'}:props['locale'].update(maxLength=63)
        if operation=='content.search':props['sources']={'type':'array','minItems':1,'maxItems':2,'uniqueItems':True,'items':{'type':'string','enum':['library','netnews']}}
        if operation.startswith('netnews.readstate.'):
            props['article']['maxLength']=300
            if 'revision' in props:props['revision'].update(minimum=0,maximum=2**63-2)
        if operation.startswith('library.reader.'):
            if 'limit' in props:props['limit'].update(minimum=1,maximum=128 if operation.endswith('.manifest') else 16384)
            if 'offset' in props:props['offset'].update(minimum=0,maximum=16*1024*1024)
            if 'chapter' in props:props['chapter'].update(minimum=0,maximum=1023)
            if 'fragment' in props:props['fragment']['maxLength']=128
        if operation.startswith(('library.note.','library.bookmark.','library.collection.')):
            for key in ('id','book'):
                if key in props:props[key]['maxLength']=300
            if 'limit' in props:props['limit'].update(minimum=1,maximum=100)
            if 'offset' in props:props['offset'].update(minimum=0,maximum=10000)
            if 'revision' in props:props['revision'].update(minimum=0,maximum=2**63-2)
            if 'text' in props:props['text']['maxLength']=8192
            if 'label' in props:props['label']['maxLength']=512
            if 'anchor' in props:props['anchor']={'type':'object','properties':{'chapter':{'type':'integer','minimum':0,'maximum':2**31-1},'offset':{'type':'integer','minimum':0,'maximum':2**31-1},'quote':{'type':'string','maxLength':2048}},'required':[],'additionalProperties':False}
            if 'action' in props:props['action']['enum']=['create','rename','add','remove','delete']
        if operation=='netnews.post':
            props['attachments']={'type':'array','maxItems':8,'items':{'type':'object','properties':{'id':{'type':'string','maxLength':68},'name':{'type':'string','maxLength':255}},'required':['id','name'],'additionalProperties':False}}
        if operation=='optimization.evaluate':
            props['joint']={'type':'array','minItems':1,'maxItems':4096,'items':{'type':'object','maxProperties':4}}
            props['decoder']={'type':'array','maxItems':4096,'items':{'type':'object','maxProperties':3}}
        name=operation.replace('.','_')
        service.add(name,'Content application: '+operation,schema(props,set(fields)-optional_fields(operation)),write,('content:admin' if operation in ADMIN_OPERATIONS else operation.split('.')[0]+(':write' if write else ':read')),('content-fabric',operation))
        service.tools[name]['securitySchemes'][0]['scopes']=sorted(required_scopes(operation))

"""Shared typed operations for MCP, application HTTP and GUI.

Account is always supplied by the authenticated transport, never an argument.
"""
import base64
from .content_fabric import Fabric

OPERATIONS={
 'applications.capabilities':({},False),
 'community.forum.list':({'limit':int,'offset':int},False),
 'community.forum.post':({'title':str,'body':str,'operation':str,'reply_to':str},True),
 'content.health':({},False),
 'content.sync':({'peer':str},True),
 'library.download':({'book':str,'sources':list,'max_chunks':int},True),
 'applications.tc16.compile':({'source':str,'syntax':str,'target':str,'profile':str},True),
 'applications.tc16.execute':({'package':str,'cycles':int},True),
 'content.upload.begin':({'upload':str,'size':int,'digest':str,'mime':str}, True),
 'content.upload.put':({'upload':str,'position':int,'data':str},True),
 'content.upload.status':({'upload':str},False),
 'content.upload.finish':({'upload':str},True),
 'content.object.get':({'id':str,'position':int},False),
 'content.object.info':({'id':str},False),
 'content.object.verify':({'id':str},False),
 'content.withdraw':({'id':str},True),
 'content.maintenance':({},True),
 'library.publish':({'metadata':dict},True),
 'library.search':({'query':str,'limit':int,'offset':int,'filters':dict},False),
 'library.get':({'id':str},False),
 'library.reading.get':({'id':str},False),
 'library.reading.save':({'id':str,'state':dict},True),
 'netnews.groups':({},False),
 'netnews.group.create':({'name':str,'description':str,'visibility':str,'posting':str,'retention':int},True),
 'netnews.post':({'groups':list,'subject':str,'body':str,'message_id':str,'references':list},True),
 'netnews.articles':({'group':str,'low':int,'limit':int},False),
 'netnews.search':({'query':str,'limit':int,'offset':int,'filters':dict},False),
 'netnews.get':({'id':str},False),
 'content.subscription.get':({'kind':str,'target':str},False),
 'content.subscription.save':({'kind':str,'target':str,'settings':dict},True),
}
OPTIONAL={'reply_to','max_chunks','filters','query','mime','limit','offset','message_id','references','low','description','visibility','posting','retention'}


def invoke(fabric, owner, operation, args):
    if operation not in OPERATIONS or not isinstance(args,dict):raise ValueError('unknown operation')
    fields,_=OPERATIONS[operation]
    if set(args)-set(fields) or (set(fields)-OPTIONAL)-set(args):raise ValueError('operation fields')
    for key,value in args.items():
        if type(value) is not fields[key]:raise ValueError('operation type')
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
    if operation=='content.health':return fabric.health(owner)
    if operation=='content.sync':
        from .content_server import sync
        return sync(fabric,args['peer'],fabric.remote_peers)
    if operation=='library.download':
        from .content_server import download
        return download(fabric,owner,args['book'],args['sources'],fabric.remote_peers,max_chunks=args.get('max_chunks',128))
    if operation=='applications.tc16.compile':
        from .tc16_spec import compile_package
        return {'package':base64.b64encode(compile_package(**args)).decode()}
    if operation=='applications.tc16.execute':
        from .tc16_spec import execute_package
        if len(args['package'])>94000:raise ValueError('package budget')
        return execute_package(base64.b64decode(args['package'],validate=True),args['cycles'])
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
    if operation in {'library.get','netnews.get'}:
        with fabric.lock:return {'id':args['id'],**fabric._get(owner,args['id'],'book' if operation=='library.get' else 'article')}
    if operation=='library.reading.get':return fabric.state(owner,'reader',args['id'])
    if operation=='library.reading.save':return fabric.state(owner,'reader',args['id'],args['state'])
    if operation=='netnews.groups':return fabric.groups(owner)
    if operation=='netnews.group.create':return fabric.create_group(owner,**args)
    if operation=='netnews.post':return fabric.post(owner,**args)
    if operation=='netnews.articles':return fabric.articles(owner,**args)
    if operation.startswith('content.subscription.'):return fabric.state(owner,**args)
    raise ValueError('unimplemented operation')


def attach(service, config):
    """Explicit config opt-in; scopes never inherit Gateway administrator rights."""
    from .mcp import schema
    kinds={str:'string',int:'integer',dict:'object',list:'array'}
    for operation,(fields,write) in OPERATIONS.items():
        props={k:{'type':kinds[v]} for k,v in fields.items()}
        for field in props.values():
            if field['type']=='string':field['maxLength']=100000
            if field['type']=='object':field['maxProperties']=48
            if field['type']=='array':field.update(maxItems=32,items={'type':'string','maxLength':300})
        service.add(operation.replace('.','_'),'Content application: '+operation,schema(props,set(fields)-OPTIONAL),write,('content:admin' if operation in {'content.sync','content.maintenance'} else operation.split('.')[0]+(':write' if write else ':read')),('content-fabric',operation))

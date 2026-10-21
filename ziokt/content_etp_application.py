"""Opt-in authenticated application binding for the real native content adapter."""
import json
import threading
from .content_etp import EtpNews
from .etp import EtpGateway,_forum_name,_forum_id,_forum_text
from .protocol import ProtocolError,strict_json


class EtpApplications:
    def __init__(self,config,*,transport=None,file_policy=None):
        if not isinstance(config,dict) or set(config)!={'gateway','accounts'}:raise ValueError('exact native ETP configuration required')
        gateway=config['gateway']
        if not isinstance(gateway,dict) or set(gateway)!={'binary','digest','config'}:raise ValueError('pinned native ETP gateway required')
        self.config=config;self.lock=threading.RLock();self.instance=None;self.transport=transport;self.file_policy=file_policy or (lambda account:self.config['accounts'].get(account,{}).get('fileshare'))
        accounts=config['accounts']
        if not isinstance(accounts,dict) or len(accounts)>128:raise ValueError('native account policy budget')
        for owner,policy in accounts.items():
            from .content_fabric import ident,GROUP
            ident(owner)
            if not isinstance(policy,dict) or not {'aliases','topics','groups','remote_authors'}<=set(policy) or set(policy)-{'aliases','topics','groups','remote_authors','fileshare'}:raise ValueError('explicit native identity/topic/group policy required')
            for field in ('aliases','topics','groups','remote_authors'):
                if not isinstance(policy[field],list) or len(policy[field])>64 or any(not isinstance(item,str) for item in policy[field]) or len(set(policy[field]))!=len(policy[field]):raise ValueError('native account allowlist budget')
            for alias in policy['aliases']:_forum_name(alias)
            for topic in policy['topics']:_forum_text(topic,256)
            for group in policy['groups']:
                if not isinstance(group,str) or not GROUP.fullmatch(group):raise ValueError('native mapped group')
            for author in policy['remote_authors']:_forum_id(author)
            if 'fileshare' in policy:
                file_policy=policy['fileshare']
                if not isinstance(file_policy,dict) or set(file_policy)!={'authors','topics','peers'}:raise ValueError('separate native file source delegation required')
                for field in file_policy:
                    if not isinstance(file_policy[field],list) or len(file_policy[field])>32 or any(not isinstance(v,str) for v in file_policy[field]) or len(set(file_policy[field]))!=len(file_policy[field]):raise ValueError('file source allowlist budget')
                for author in file_policy['authors']:_forum_id(author)
                for topic in file_policy['topics']:_forum_text(topic,256)
                from .etp_fileshare import params as file_params
                for peer in file_policy['peers']:file_params('etp.fileshare.request',{'hash':'0'*64,'peer':peer})

    def call(self,method,params):
        if self.transport is not None:return self.transport(method,params)
        with self.lock:
            if self.instance is None:
                try:self.instance=EtpGateway(**self.config['gateway'])
                except OSError:raise ProtocolError('ETP_UNAVAILABLE','Configured native component is offline or unavailable') from None
            return self.instance.call(method,params)

    def close(self):
        with self.lock:
            if self.instance is not None:self.instance.close();self.instance=None

    def invoke(self,fabric,owner,operation,args):
        policy=self.config['accounts'].get(owner)
        if operation.startswith('library.etp.'):
            from .content_etp_library import EtpLibrary
            intake=EtpLibrary(fabric,self,self.file_policy)
            if operation=='library.etp.status':return intake.status(owner,args['job'])
            if operation=='library.etp.cancel':return intake.cancel(owner,args['job'])
            if not policy or 'fileshare' not in policy:raise PermissionError('native Library source delegation not configured')
            if operation=='library.etp.begin':return intake.begin(owner,args['proof'],args['peer'],args['record'],args.get('visibility','private'),args['nonce'])
            if operation=='library.etp.step':return intake.step(owner,args['job'],args.get('max_chunks',8))
            raise ValueError('unknown Library native operation')
        if policy is None:raise PermissionError('native account delegation not configured')
        bridge=EtpNews(fabric,self)
        if operation=='content.etp.status':
            with fabric.lock:
                grants=[]
                for row in fabric.db.execute('SELECT id,proof,revoked FROM etp_content_grants WHERE owner=? ORDER BY id LIMIT 100',(owner,)):
                    grant=json.loads(row['proof'])['payload']['grant']
                    grants.append({'id':row['id'],'revoked':bool(row['revoked']),**{key:grant[key] for key in ('expires','native_author','topic','group')}})
                jobs=[dict(row) for row in fabric.db.execute('SELECT j.id,j.record,j.state,j.native_id,j.error FROM etp_content_jobs j JOIN etp_content_grants g ON g.id=j.grant_id WHERE g.owner=? ORDER BY j.timestamp DESC LIMIT 100',(owner,))]
            return {'grants':grants,'jobs':jobs,'inventory_endpoint':'content.etp.sync','native_capability_probe_required':True,'automatic_background_polling':False,'attachments_transferred':False}
        if operation=='content.etp.revoke':return bridge.revoke(owner,args['grant'])
        if operation in {'content.etp.authorize','content.etp.offer'}:
            if args['alias'] not in policy['aliases'] or args['topic'] not in policy['topics'] or args['group'] not in policy['groups']:raise PermissionError('native identity/topic/group delegation denied')
            if operation=='content.etp.authorize':return bridge.authorize(owner,**args,allow=True)
            if args['target']!=fabric.public and args['target'] not in fabric.peers:raise PermissionError('target content service is not pinned')
            parameters=dict(args);target_owner=parameters.pop('target_account')
            return bridge.offer_authorization(target_owner,**parameters,allow=True)
        if operation=='content.etp.accept':
            post,content=bridge.native(args['native_proof']);grant=strict_json(content,8192)
            if not isinstance(grant,dict):raise PermissionError('typed native authorization offer required')
            if post['author_id'] not in policy['remote_authors'] or grant.get('topic') not in policy['topics'] or grant.get('group') not in policy['groups']:raise PermissionError('remote native identity/topic/group not delegated')
            return bridge.accept_authorization(owner,args['native_proof'],allow=True)
        grant=bridge.grant(owner,args['grant'],require_signer=(operation not in {'content.etp.ingest','content.etp.sync'}))
        if grant['topic'] not in policy['topics'] or grant['group'] not in policy['groups']:raise PermissionError('native group delegation revoked')
        if operation in {'content.etp.ingest','content.etp.sync'}:
            if grant['native_author'] not in policy['remote_authors']:raise PermissionError('remote native author delegation revoked')
            if operation=='content.etp.sync':return bridge.sync(owner,args['grant'],args.get('limit',16))
            return bridge.ingest(owner,args['grant'],args['native_id'])
        if grant['alias'] not in policy['aliases']:raise PermissionError('native signer delegation revoked')
        if operation=='content.etp.export':return bridge.export(owner,args['grant'],args['record'])
        if operation=='content.etp.recover':return bridge.recover(owner,args['grant'])
        raise ValueError('unknown native ETP operation')

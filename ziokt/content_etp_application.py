"""Opt-in authenticated application binding for the real native content adapter."""
import json
import threading
from .content_etp import EtpNews
from .etp import EtpGateway,_forum_name,_forum_id,_forum_text
from .protocol import ProtocolError,strict_json


class EtpApplications:
    def __init__(self,config):
        if not isinstance(config,dict) or set(config)!={'gateway','accounts'}:raise ValueError('exact native ETP configuration required')
        gateway=config['gateway']
        if not isinstance(gateway,dict) or set(gateway)!={'binary','digest','config'}:raise ValueError('pinned native ETP gateway required')
        self.config=config;self.lock=threading.RLock();self.instance=None
        accounts=config['accounts']
        if not isinstance(accounts,dict) or len(accounts)>128:raise ValueError('native account policy budget')
        for owner,policy in accounts.items():
            from .content_fabric import ident,GROUP
            ident(owner)
            if not isinstance(policy,dict) or set(policy)!={'aliases','topics','groups','remote_authors'}:raise ValueError('explicit native identity/topic/group policy required')
            for field in policy:
                if not isinstance(policy[field],list) or len(policy[field])>64 or any(not isinstance(item,str) for item in policy[field]) or len(set(policy[field]))!=len(policy[field]):raise ValueError('native account allowlist budget')
            for alias in policy['aliases']:_forum_name(alias)
            for topic in policy['topics']:_forum_text(topic,256)
            for group in policy['groups']:
                if not isinstance(group,str) or not GROUP.fullmatch(group):raise ValueError('native mapped group')
            for author in policy['remote_authors']:_forum_id(author)

    def call(self,method,params):
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
        if policy is None:raise PermissionError('native account delegation not configured')
        bridge=EtpNews(fabric,self)
        if operation=='content.etp.status':
            with fabric.lock:
                grants=[]
                for row in fabric.db.execute('SELECT id,proof,revoked FROM etp_content_grants WHERE owner=? ORDER BY id LIMIT 100',(owner,)):
                    grant=json.loads(row['proof'])['payload']['grant']
                    grants.append({'id':row['id'],'revoked':bool(row['revoked']),**{key:grant[key] for key in ('expires','native_author','topic','group')}})
                jobs=[dict(row) for row in fabric.db.execute('SELECT j.id,j.record,j.state,j.native_id,j.error FROM etp_content_jobs j JOIN etp_content_grants g ON g.id=j.grant_id WHERE g.owner=? ORDER BY j.timestamp DESC LIMIT 100',(owner,))]
            return {'grants':grants,'jobs':jobs,'automatic_native_scan':False,'attachments_transferred':False}
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
        grant=bridge.grant(owner,args['grant'],require_signer=(operation!='content.etp.ingest'))
        if grant['topic'] not in policy['topics'] or grant['group'] not in policy['groups']:raise PermissionError('native group delegation revoked')
        if operation=='content.etp.ingest':
            if grant['native_author'] not in policy['remote_authors']:raise PermissionError('remote native author delegation revoked')
            return bridge.ingest(owner,args['grant'],args['native_id'])
        if grant['alias'] not in policy['aliases']:raise PermissionError('native signer delegation revoked')
        if operation=='content.etp.export':return bridge.export(owner,args['grant'],args['record'])
        if operation=='content.etp.recover':return bridge.recover(owner,args['grant'])
        raise ValueError('unknown native ETP operation')

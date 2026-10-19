"""Narrow user-authorized Community API, independent of Gateway administration.

Local configuration binds each application account to its own Community member
identity. Origin approval alone grants no read or write authority. No caller-
selected paths, policy changes, key exports, execution, or Gateway operations.
"""
import secrets
from .community import Community
from .protocol import secure_read,strict_json,ProtocolError
from .security import sign


class CommunityApplication:
    def __init__(self,config,account,*,write=False):
        grant=config.get('accounts',{}).get(account)
        if not grant:raise PermissionError('community account not delegated')
        self.private=secure_read(grant['signing_key'],32) if write else None
        self.public=grant['public_key']
        if self.private and sign({},self.private,'Ziokt/community-api/identity/v1')['public_key']!=self.public:raise PermissionError('delegated signer mismatch')
        self.community=Community(config['root'],strict_json(secure_read(config['policy'])),config['owner'],secure_read(config['encryption_key'],32),readonly=not write)
        self.community._current();self.community._member(self.public,'forum')
    def close(self):self.community.close()
    def envelope(self,event):
        row=self.community.db.execute('SELECT sealed FROM records WHERE id=?',(event['id'],)).fetchone()
        if row is None:raise ProtocolError('EVENT_NOT_FOUND','native signed event unavailable')
        return strict_json(self.community._open(row[0],'event'))
    def list(self,limit=30,offset=0):
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=100000:raise ValueError('pagination')
        events=self.community.view('forum')['events']
        return {'schema':'ziokt.forum-page.v1','source':'ziokt-community','items':[{'native_id':e['id'],'source':'ziokt-community','author':e['author'],'deleted':e['deleted'],'body':e['body'],'proof':self.envelope(e)} for e in events[offset:offset+limit]],'offset':offset,'limit':limit,'native_permission_checked':True}
    def post(self,title,body,operation,reply_to=''):
        from .content_fabric import ident,text
        ident(operation);text(title,512);text(body,2048)
        if self.private is None:raise PermissionError('write delegation required')
        key='api-'+operation
        prior=self.community.view('forum',key)['events']
        content={'title':title,'text':body,'reply_to':reply_to}
        if prior:
            if len(prior)!=1 or prior[0]['author']!=self.public or prior[0]['body']!=content or prior[0]['deleted']:raise ValueError('operation conflict')
            return {'id':prior[0]['id'],'duplicate':True,'source':'ziokt-community','proof':self.envelope(prior[0])}
        if reply_to:
            found=next((e for e in self.community.view('forum')['events'] if e['id']==reply_to and not e['deleted']),None)
            if found is None:raise ValueError('reply target unavailable')
        event=self.community.publish(self.private,'forum',key,content)
        found=next(e for e in self.community.view('forum',key)['events'] if e['id']==event)
        return {'id':event,'duplicate':False,'source':'ziokt-community','proof':self.envelope(found)}


def invoke(config,account,operation,args):
    adapter=CommunityApplication(config,account,write=operation=='community.forum.post')
    try:
        if operation=='community.forum.list':return adapter.list(**args)
        if operation=='community.forum.post':return adapter.post(**args)
        raise ValueError('community operation')
    finally:adapter.close()

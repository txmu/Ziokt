"""Journaled Netnews <-> signed native ETP Forum adapter, with mutual grants.

The adapter uses the actual ETP Forum signer/store/DHT; it owns no Forum engine,
ETP key, substitute database, or file transfer protocol.
"""
import base64
import hashlib
import json
import secrets
import time
from .protocol import encoded,strict_json,ProtocolError
from .security import sign,verify

DOMAIN='Ziokt/ContentFabric/ETP-authorization/v1'


class EtpNews:
    def __init__(self,fabric,gateway):
        self.fabric,self.gateway=fabric,gateway
        with fabric.transaction():
            fabric.db.execute('CREATE TABLE IF NOT EXISTS etp_content_grants(id TEXT PRIMARY KEY,owner TEXT NOT NULL,proof BLOB NOT NULL,revoked INTEGER NOT NULL DEFAULT 0)')
            fabric.db.execute('CREATE TABLE IF NOT EXISTS etp_content_jobs(id TEXT PRIMARY KEY,grant_id TEXT NOT NULL,record TEXT NOT NULL,event TEXT NOT NULL,content BLOB NOT NULL,timestamp INTEGER NOT NULL,state TEXT NOT NULL,native_id TEXT,error TEXT NOT NULL DEFAULT \'\')')
            fabric.db.execute('CREATE TABLE IF NOT EXISTS etp_content_links(native_id TEXT PRIMARY KEY,record TEXT NOT NULL,grant_id TEXT NOT NULL,direction TEXT NOT NULL,author TEXT NOT NULL)')
            fabric.db.execute('INSERT OR IGNORE INTO migrations VALUES(7,unixepoch())')

    def native(self,identifier):
        post=self.gateway.call('etp.forum.get',{'id':identifier})['post']
        if post is None:raise ProtocolError('ETP_CONTENT_UNAVAILABLE','Native signed post is absent or expired')
        if post['author_id'] is None:raise ProtocolError('ETP_CONTENT_UNSIGNED','Anonymous content cannot authorize identity federation')
        content=b''.join(base64.b64decode(v,validate=True) for v in post['content_base64'])
        return post,content

    def offer_authorization(self,owner,alias,topic,group,*,target,expires,allow=False):
        from .content_fabric import ident,GROUP
        if allow is not True:raise PermissionError('explicit native identity authorization required')
        ident(owner);now=int(time.time())
        if not isinstance(target,str) or len(target)!=64 or any(c not in '0123456789abcdef' for c in target) or not isinstance(group,str) or not GROUP.fullmatch(group):raise ValueError('target service/group')
        if type(expires) is not int or not now<expires<=now+86400:raise ValueError('grant lifetime must be at most one day')
        author=self.gateway.call('etp.forum.identity',{'name':alias})['author_id']
        subscription=self.gateway.call('etp.forum.subscribe',{'topic':topic})
        value={'schema':'ziokt.etp-content-grant.v1','fabric':target,'owner':owner,'native_author':author,'alias':alias,'topic':topic,'topic_hash':subscription['topic_hash'],'group':group,'expires':expires,'nonce':secrets.token_hex(16)}
        publication=self.gateway.call('etp.forum.publish',{'topic':topic,'content':encoded(value).decode(),'author':alias,'parent_id':None,'timestamp':now})
        post,content=self.native(publication['id'])
        if content!=encoded(value) or post['author_id']!=author:raise ProtocolError('ETP_IDENTITY_MISMATCH','Native identity did not sign the requested grant')
        return {'native_proof':publication['id'],'target':target,'expires':expires,'remote_delivery_confirmed':False}

    def accept_authorization(self,owner,native_proof,*,allow=False):
        if allow is not True:raise PermissionError('explicit local account authorization required')
        f=self.fabric;post,content=self.native(native_proof)
        value=strict_json(content,8192)
        fields={'schema','fabric','owner','native_author','alias','topic','topic_hash','group','expires','nonce'}
        if not isinstance(value,dict) or set(value)!=fields or value['schema']!='ziokt.etp-content-grant.v1' or value['fabric']!=f.public or value['owner']!=owner or value['native_author']!=post['author_id'] or value['topic_hash']!=post['topic_hash']:raise PermissionError('native offer does not authorize this service/account')
        now=int(time.time())
        if type(value['expires']) is not int or not now<value['expires']<=now+86400:raise PermissionError('native authorization expired')
        subscription=self.gateway.call('etp.forum.subscribe',{'topic':value['topic']})
        if subscription['topic_hash']!=value['topic_hash']:raise PermissionError('authorization topic mismatch')
        proof=sign({'grant':value,'native_proof':native_proof},f.key,DOMAIN)
        identifier=hashlib.sha256(encoded(proof)).hexdigest()
        with f.transaction():
            policy=f.db.execute('SELECT * FROM groups WHERE name=?',(value['group'],)).fetchone()
            if not policy or policy['owner']!=owner or policy['visibility']!='public':raise PermissionError('owned public group required')
            existing=f.db.execute('SELECT revoked FROM etp_content_grants WHERE id=?',(identifier,)).fetchone()
            if existing and existing['revoked']:raise PermissionError('revoked grant cannot be reactivated; create a fresh offer')
            if not existing and f.db.execute('SELECT count(*) FROM etp_content_grants').fetchone()[0]>=4096:raise ValueError('ETP grant retention limit')
            f.db.execute('INSERT OR IGNORE INTO etp_content_grants VALUES(?,?,?,0)',(identifier,owner,encoded(proof)));f._audit(owner,'etp.authorize',identifier)
        return {'id':identifier,'expires':value['expires'],'native_author':value['native_author'],'native_signature_verified':True,'remote_delivery_confirmed':False}

    def authorize(self,owner,alias,topic,group,*,expires,allow=False):
        offer=self.offer_authorization(owner,alias,topic,group,target=self.fabric.public,expires=expires,allow=allow)
        return self.accept_authorization(owner,offer['native_proof'],allow=allow)

    def grant(self,owner,identifier,*,require_signer=True):
        f=self.fabric
        with f.lock:row=f.db.execute('SELECT * FROM etp_content_grants WHERE id=? AND owner=?',(identifier,owner)).fetchone()
        if not row or row['revoked']:raise PermissionError('ETP grant unavailable or revoked')
        proof=verify(json.loads(row['proof']),f.public,DOMAIN);grant=proof['grant']
        if grant['expires']<=int(time.time()) or grant['fabric']!=f.public:raise PermissionError('ETP grant expired or wrong service')
        if require_signer and self.gateway.call('etp.forum.identity',{'name':grant['alias']})['author_id']!=grant['native_author']:raise PermissionError('native identity rotated; new mutual authorization required')
        post,content=self.native(proof['native_proof'])
        if post['author_id']!=grant['native_author'] or post['topic_hash']!=grant['topic_hash'] or content!=encoded(grant):raise PermissionError('native authorization proof invalid')
        with f.lock:
            policy=f.db.execute('SELECT owner,visibility FROM groups WHERE name=?',(grant['group'],)).fetchone()
            if not policy or policy['owner']!=owner or policy['visibility']!='public':raise PermissionError('public group authorization changed')
        return grant

    def revoke(self,owner,identifier):
        with self.fabric.transaction():
            if self.fabric.db.execute('UPDATE etp_content_grants SET revoked=1 WHERE id=? AND owner=?',(identifier,owner)).rowcount!=1:raise PermissionError('grant unavailable')
            self.fabric._audit(owner,'etp.revoke',identifier)
        return {'id':identifier,'revoked':True,'native_posts_deleted':False}

    def export(self,owner,grant_id,record):
        grant=self.grant(owner,grant_id);f=self.fabric
        with f.transaction():
            row=f.db.execute('SELECT * FROM records WHERE id=?',(record,)).fetchone()
            if not row or row['owner']!=owner or row['origin']!=f.public or row['visibility']!='public':raise PermissionError('owned local public article required')
            if row['kind']!='article':raise ValueError('Netnews article required')
            loop=f.db.execute("SELECT native_id FROM etp_content_links WHERE record=? AND direction='import'",(record,)).fetchone()
            if loop:return {'state':'loop_suppressed','native_id':loop['native_id'],'remote_delivery_confirmed':False}
            previous=f.db.execute("SELECT * FROM etp_content_links WHERE record=? AND grant_id=? AND direction='export'",(record,grant_id)).fetchone()
            body=json.loads(row['body'])
            if row['deleted']:
                if not previous:raise ValueError('article has no native version to withdraw')
                envelope={'schema':'ziokt.etp-news.v1','action':'withdraw','source':{'fabric':f.public,'record':record,'event':row['event']},'native_target':previous['native_id']}
                parent=previous['native_id']
            else:
                if grant['group'] not in body['newsgroups']:raise PermissionError('article is outside authorized group')
                if f.db.execute('SELECT 1 FROM local_content_policies WHERE record=? AND distribution_stopped=1',(record,)).fetchone():raise PermissionError('local distribution stopped')
                parent=None
                if body['references']:
                    mapping=f.db.execute('SELECT native_id FROM etp_content_links WHERE record=? ORDER BY native_id LIMIT 1',(body['references'][-1],)).fetchone()
                    if not mapping:raise ProtocolError('ETP_PARENT_PENDING','Parent article must synchronize before reply')
                    parent=mapping['native_id']
                envelope={'schema':'ziokt.etp-news.v1','action':'publish','source':{'fabric':f.public,'record':record,'event':row['event']},'subject':body['subject'],'body':body['body'],'references':body['references'],'content_references':body.get('attachments',[])}
            original=f.db.execute('SELECT envelope FROM events WHERE id=?',(row['event'],)).fetchone()
            if not original:raise ProtocolError('ETP_SOURCE_EVENT','Original signed source event is absent')
            envelope['source_event']=json.loads(original['envelope'])
            raw=encoded(envelope)
            if len(raw)>32768:raise ValueError('native Forum content limit')
            job=hashlib.sha256((grant_id+'\0'+row['event']).encode()).hexdigest()
            existing=f.db.execute('SELECT * FROM etp_content_jobs WHERE id=?',(job,)).fetchone()
            if existing and existing['state']=='native_stored':return {'state':'native_stored','job':job,'native_id':existing['native_id'],'duplicate':True,'remote_delivery_confirmed':False}
            if not existing:
                if f.db.execute('SELECT count(*) FROM etp_content_jobs').fetchone()[0]>=10000:raise ValueError('ETP journal retention limit')
                f.db.execute('INSERT INTO etp_content_jobs(id,grant_id,record,event,content,timestamp,state) VALUES(?,?,?,?,?,?,\'prepared\')',(job,grant_id,record,row['event'],encoded({'payload':envelope,'parent':parent}),int(time.time())))
            entry=f.db.execute('SELECT * FROM etp_content_jobs WHERE id=?',(job,)).fetchone();intent=json.loads(entry['content'])
        # Native timestamp and signed bytes are journaled before the external call.
        try:
            published=self.gateway.call('etp.forum.publish',{'topic':grant['topic'],'content':encoded(intent['payload']).decode(),'author':grant['alias'],'parent_id':intent['parent'],'timestamp':entry['timestamp']})
            post,content=self.native(published['id'])
            if content!=encoded(intent['payload']) or post['author_id']!=grant['native_author'] or post['topic_hash']!=grant['topic_hash'] or post['parent_id']!=intent['parent']:raise ProtocolError('ETP_CONTENT_MISMATCH','Native readback differs from journaled content')
            self.grant(owner,grant_id)
            with f.transaction():
                current=f.db.execute('SELECT event FROM records WHERE id=?',(record,)).fetchone()
                if not current or current['event']!=entry['event']:raise ProtocolError('ETP_SOURCE_CHANGED','Source changed during native publication; reconcile the journal')
                f.db.execute("UPDATE etp_content_jobs SET state='native_stored',native_id=?,error='' WHERE id=?",(published['id'],job))
                f.db.execute('INSERT OR IGNORE INTO etp_content_links VALUES(?,?,?,?,?)',(published['id'],record,grant_id,'export',grant['native_author']))
                f._audit(owner,'etp.native-stored',job)
            return {'state':'native_stored','job':job,'native_id':published['id'],'native_signature_verified':True,'remote_delivery_confirmed':False,'native_original_deleted':False}
        except Exception as error:
            with f.transaction():f.db.execute("UPDATE etp_content_jobs SET state='failed',error=? WHERE id=?",(getattr(error,'code',type(error).__name__),job))
            raise

    def ingest(self,owner,grant_id,native_id):
        grant=self.grant(owner,grant_id,require_signer=False);post,content=self.native(native_id);f=self.fabric
        if post['author_id']!=grant['native_author'] or post['topic_hash']!=grant['topic_hash']:raise PermissionError('native author/topic is outside mutual authorization')
        with f.transaction():
            linked=f.db.execute('SELECT * FROM etp_content_links WHERE native_id=?',(native_id,)).fetchone()
            if linked:
                if linked['grant_id']!=grant_id:raise PermissionError('native object belongs to another grant')
                return {'state':'already_linked','record':linked['record'],'duplicate':True}
            parent=[]
            if post['parent_id']:
                linked_parent=f.db.execute('SELECT record FROM etp_content_links WHERE native_id=?',(post['parent_id'],)).fetchone()
                if not linked_parent:raise ProtocolError('ETP_PARENT_PENDING','Native reply parent must synchronize first')
                parent=[linked_parent['record']]
            # Native Forum text stays text. A signed bridge envelope is separately typed.
            subject='ETP Forum '+native_id[:16];body=content.decode();source=None
            try:value=strict_json(content,32768,string_limit=16384)
            except (ValueError,ProtocolError):value=None
            if isinstance(value,dict) and value.get('schema')=='ziokt.etp-news.v1':
                source=value.get('source')
                if not isinstance(source,dict) or set(source)!={'fabric','record','event'}:raise ValueError('source reference')
                from .content_fabric import EVENT_DOMAIN
                if source['fabric']!=f.public and source['fabric'] not in f.peers:raise PermissionError('source Content Fabric publisher is not pinned')
                signed=value.get('source_event')
                event=verify(signed,source['fabric'],EVENT_DOMAIN)
                if hashlib.sha256(encoded(signed)).hexdigest()!=source['event'] or event['record']!=source['record'] or event['kind']!='article' or event['visibility']!='public':raise PermissionError('native envelope source event mismatch')
                if source['fabric']==f.public:raise ProtocolError('ETP_LOOP','Unreconciled local source; recover outgoing journal instead of copying')
                if value.get('action')=='withdraw':
                    if event['deleted'] is not True:raise PermissionError('signed source withdrawal required')
                    target=value.get('native_target')
                    if target!=post['parent_id']:raise PermissionError('withdrawal parent mismatch')
                    link=f.db.execute('SELECT * FROM etp_content_links WHERE native_id=?',(target,)).fetchone()
                    if not link or link['author']!=post['author_id'] or link['grant_id']!=grant_id:raise PermissionError('withdrawal authority mismatch')
                    f.withdraw(owner,link['record']);record=link['record']
                elif value.get('action')=='publish':
                    if event['deleted'] is not False or any(event['body'].get(field)!=value.get(field) for field in ('subject','body','references')) or event['body'].get('attachments',[])!=value.get('content_references',[]):raise PermissionError('signed source body mismatch')
                    subject=value['subject'];body=value['body']
                    if value.get('content_references'):raise ProtocolError('ETP_ATTACHMENT_SOURCE_REQUIRED','Native object sources must be authorized and retrieved before attachment import')
                    record=source['record']
                    f.post(owner,[grant['group']],subject,body,message_id=record,references=parent,sender=event['body']['from'])
                else:raise ValueError('bridge action')
            else:
                record='<etp-'+native_id+'@etp.invalid>'
                f.post(owner,[grant['group']],subject,body,message_id=record,references=parent,sender='ETP '+post['author_id'])
            f.db.execute('INSERT INTO etp_content_links VALUES(?,?,?,?,?)',(native_id,record,grant_id,'import',post['author_id']))
            f._audit(owner,'etp.content-import',native_id)
            return {'state':'imported','record':record,'native_signature_verified':True,'remote_delivery_confirmed':False}

    def recover(self,owner,grant_id):
        self.grant(owner,grant_id)
        with self.fabric.lock:rows=self.fabric.db.execute("SELECT id,record,event FROM etp_content_jobs WHERE grant_id=? AND state IN ('prepared','failed') ORDER BY timestamp LIMIT 32",(grant_id,)).fetchall()
        results=[]
        for row in rows:
            with self.fabric.transaction():
                current=self.fabric.db.execute('SELECT event FROM records WHERE id=?',(row['record'],)).fetchone()
                if not current or current['event']!=row['event']:
                    self.fabric.db.execute("UPDATE etp_content_jobs SET state='conflict',error='ETP_SOURCE_CHANGED' WHERE id=?",(row['id'],))
                    results.append({'state':'conflict','record':row['record'],'error':'ETP_SOURCE_CHANGED'});continue
            try:results.append(self.export(owner,grant_id,row['record']))
            except Exception as error:results.append({'state':'failed','record':row['record'],'error':getattr(error,'code',type(error).__name__)})
        return {'results':results,'all_recovered':all(value['state']=='native_stored' for value in results)}

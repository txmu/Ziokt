"""Durable Library intake from signed native Forum sources and FileShare bytes.

Native FileShare owns wire/peer/chunk verification. Fabric owns resumable uploads,
SHA-256/Merkle objects, local book versions and permissions. No key translation.
"""
import base64
import hashlib
import json
import time
from .protocol import ProtocolError,encoded,strict_json
from .content_fabric import ident
from .etp_fileshare import native_hash

SCHEMA='ziokt.etp-library-source.v1'


class EtpLibrary:
    def __init__(self,fabric,gateway,policy):
        self.fabric,self.gateway,self.policy=fabric,gateway,policy
        with fabric.transaction():
            fabric.db.execute('''CREATE TABLE IF NOT EXISTS etp_library_jobs(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,record TEXT NOT NULL,proof TEXT NOT NULL,peer TEXT NOT NULL,
                visibility TEXT NOT NULL,source BLOB NOT NULL,post BLOB NOT NULL,upload TEXT NOT NULL,
                state TEXT NOT NULL,object TEXT,error TEXT NOT NULL,updated INTEGER NOT NULL)''')
            fabric.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS active_etp_library_record ON etp_library_jobs(owner,record) WHERE state NOT IN ('cancelled','complete')")
            fabric.db.execute('INSERT OR IGNORE INTO migrations VALUES(9,unixepoch())')

    def authorize(self,owner,source,post,peer):
        policy=self.policy(owner)
        if not isinstance(policy,dict) or post.get('author_id') is None or post['author_id'] not in policy.get('authors',[]) or source.get('topic') not in policy.get('topics',[]) or peer not in policy.get('peers',[]):
            raise PermissionError('native Library author/topic/peer delegation unavailable or revoked')

    def source(self,owner,proof,peer):
        native_hash(proof)
        post=self.gateway.call('etp.forum.get',{'id':proof})['post']
        if post is None:raise ProtocolError('ETP_SOURCE_UNAVAILABLE','Signed source announcement absent or expired')
        raw=b''.join(base64.b64decode(part,validate=True) for part in post['content_base64'])
        value=strict_json(raw,8192)
        fields={'schema','topic','hash','digest','size','mime','book','public'}
        if not isinstance(value,dict) or set(value)!=fields or value['schema']!=SCHEMA or value['public'] is not True:raise ProtocolError('ETP_LIBRARY_SOURCE','Explicitly public versioned source announcement required')
        native_hash(value['hash'])
        if type(value['size']) is not int or not 1<=value['size']<=16777216 or not isinstance(value['digest'],str) or len(value['digest'])!=71 or not value['digest'].startswith('sha256:'):raise ValueError('native source size/digest')
        native_hash(value['digest'][7:])
        if not isinstance(value['mime'],str) or not 1<=len(value['mime'].encode())<=128 or any(ord(c)<32 for c in value['mime']):raise ValueError('native source mime')
        book=value['book']
        allowed={'work_id','edition_id','title','subtitle','authors','translators','editors','publisher','year','language','isbn','doi','tags','description','pages','format','license','rights'}
        if not isinstance(book,dict) or set(book)-allowed or not {'work_id','edition_id','title','authors','license'}<=set(book):raise ValueError('source bibliographic metadata')
        self.authorize(owner,value,post,peer)
        topic=self.gateway.call('etp.forum.subscribe',{'topic':value['topic']})
        if topic['topic_hash']!=post['topic_hash']:raise PermissionError('signed source is outside its declared authorized topic')
        return value,post

    def job(self,owner,job):
        native_hash(job)
        with self.fabric.lock:row=self.fabric.db.execute('SELECT * FROM etp_library_jobs WHERE id=? AND owner=?',(job,owner)).fetchone()
        if row is None:raise PermissionError('owned Library import required')
        return row

    def status(self,owner,job):
        row=self.job(owner,job)
        return {'job':job,'record':row['record'],'state':row['state'],'object':row['object'],'error':row['error'],
                'source_proof':row['proof'],'native_delivery_verified':row['state']=='complete'}

    def begin(self,owner,proof,peer,record,visibility,nonce):
        ident(owner);ident(record);ident(nonce)
        if visibility not in {'private','public'}:raise ValueError('explicit Library visibility')
        value,post=self.source(owner,proof,peer)
        job=hashlib.sha256(encoded({'owner':owner,'proof':proof,'peer':peer,'record':record,'visibility':visibility,'nonce':nonce})).hexdigest()
        f=self.fabric
        with f.transaction():
            old=f.db.execute('SELECT * FROM etp_library_jobs WHERE id=? AND owner=?',(job,owner)).fetchone()
            if old:
                if bytes(old['source'])!=encoded(value) or bytes(old['post'])!=encoded(post):raise ProtocolError('ETP_SOURCE_CHANGED','Signed source changed across recovery')
                return self.status(owner,job)
            if f.db.execute('SELECT 1 FROM records WHERE id=?',(record,)).fetchone():raise ProtocolError('ETP_LIBRARY_CONFLICT','Import must not overwrite an existing record')
            if f.db.execute("SELECT 1 FROM etp_library_jobs WHERE owner=? AND record=? AND state NOT IN ('cancelled','complete')",(owner,record)).fetchone():raise ProtocolError('ETP_LIBRARY_CONFLICT','Another import owns this record reservation')
            if f.db.execute('SELECT count(*) FROM etp_library_jobs WHERE owner=?',(owner,)).fetchone()[0]>=256:raise ValueError('native Library import retention budget')
            self.authorize(owner,value,post,peer)
            upload='etp-lib-'+job[:48]
            f.begin(owner,upload,value['size'],value['digest'],value['mime'])
            f.db.execute("INSERT INTO etp_library_jobs VALUES(?,?,?,?,?,?,?,?,?,'prepared',NULL,'',?)",(job,owner,record,proof,peer,visibility,encoded(value),encoded(post),upload,int(time.time())))
            f._audit(owner,'etp.library-prepare',job)
        return self.status(owner,job)

    def step(self,owner,job,max_chunks=8):
        if type(max_chunks) is not int or not 1<=max_chunks<=32:raise ValueError('native Library step budget')
        row=self.job(owner,job)
        if row['state'] in {'complete','cancelled','conflict'}:return self.status(owner,job)
        f=self.fabric
        try:
            source,post=self.source(owner,row['proof'],row['peer'])
            if encoded(source)!=bytes(row['source']) or encoded(post)!=bytes(row['post']):raise ProtocolError('ETP_SOURCE_CHANGED','Signed source changed across intake')
            status=self.gateway.call('etp.fileshare.status',{'hash':source['hash']})
            if status['state']!='locally_indexed':
                if status['state'] in {'absent','timed_out'}:self.gateway.call('etp.fileshare.request',{'hash':source['hash'],'peer':row['peer']})
                with f.transaction():
                    live=self.job(owner,job)
                    if live['state']=='cancelled':return self.status(owner,job)
                    self.authorize(owner,source,post,row['peer'])
                    f.db.execute("UPDATE etp_library_jobs SET state='waiting_native',error='',updated=? WHERE id=?",(int(time.time()),job))
                return self.status(owner,job)
            manifest=self.gateway.call('etp.fileshare.manifest',{'hash':source['hash']})
            if manifest['size']!=source['size'] or manifest['chunk_bytes']!=16384:raise ProtocolError('ETP_SOURCE_SIZE','Native manifest differs from signed source size')
            for _ in range(max_chunks):
                progress=f.upload_status(owner,row['upload'])
                if progress['expired']:raise ProtocolError('ETP_UPLOAD_EXPIRED','Native Fabric upload expired; cancel and authorize a fresh intake')
                if progress['next_missing']>=progress['total_chunks']:break
                index=progress['next_missing']
                part=self.gateway.call('etp.fileshare.chunk',{'hash':source['hash'],'index':index})
                data=b''.join(base64.b64decode(value,validate=True) for value in part['data_base64'])
                if len(data)!=min(16384,source['size']-index*16384):raise ProtocolError('ETP_SOURCE_CHUNK','Native chunk length differs from signed source')
                with f.transaction():
                    live=self.job(owner,job)
                    if live['state']=='cancelled':return self.status(owner,job)
                    self.authorize(owner,source,post,row['peer'])
                    f.put(owner,row['upload'],index,data)
                    f.db.execute("UPDATE etp_library_jobs SET state='receiving',error='',updated=? WHERE id=?",(int(time.time()),job))
            progress=f.upload_status(owner,row['upload'])
            if progress['next_missing']<progress['total_chunks']:return self.status(owner,job)
            with f.transaction():
                live=self.job(owner,job)
                if live['state']=='cancelled':return self.status(owner,job)
                if live['state']=='complete':return self.status(owner,job)
                self.authorize(owner,source,post,row['peer'])
                if f.db.execute('SELECT 1 FROM records WHERE id=?',(row['record'],)).fetchone():
                    f.db.execute("UPDATE etp_library_jobs SET state='conflict',error='ETP_LIBRARY_CONFLICT' WHERE id=?",(job,))
                    return self.status(owner,job)
                obj=f.finish(owner,row['upload'])  # Native full SHA-256 + Merkle validation.
                f.verify_object(owner,obj['id'])
                metadata={**source['book'],'id':row['record'],'file_id':obj['id'],'visibility':row['visibility'],
                          'provenance':'ETP Forum '+row['proof']+' author '+post['author_id']+' / native FileShare '+source['hash']}
                f.create_book(owner,metadata)
                f.db.execute("UPDATE etp_library_jobs SET state='complete',object=?,error='',updated=? WHERE id=?",(obj['id'],int(time.time()),job))
                f._audit(owner,'etp.library-complete',job)
            return self.status(owner,job)
        except Exception as error:
            with f.transaction():
                f.db.execute("UPDATE etp_library_jobs SET state='failed',error=?,updated=? WHERE id=? AND state NOT IN ('complete','cancelled','conflict')",(getattr(error,'code',type(error).__name__),int(time.time()),job))
            raise

    def cancel(self,owner,job):
        f=self.fabric
        with f.transaction():
            row=self.job(owner,job)
            if row['state']=='complete':raise ValueError('withdraw the Library version separately; completed intake cannot be cancelled')
            if row['state']=='cancelled':return self.status(owner,job)
            f.discard_staged_upload(owner,row['upload'])
            f.db.execute("UPDATE etp_library_jobs SET state='cancelled',error='',updated=? WHERE id=?",(int(time.time()),job))
            f._audit(owner,'etp.library-cancel',job)
        return self.status(owner,job)

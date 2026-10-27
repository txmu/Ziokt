"""Private account-vault sharing and reading-state replication.

Account vaults are the encryption endpoints. Hosting nodes process plaintext for
their authenticated local accounts; intermediate peers receive only ciphertext.
"""
import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey,X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from .content_fabric import ident,CHUNK_BYTES
from .protocol import encoded,secure_read,strict_json
from .security import sign,verify
from .cli import write_binary_exclusive
from .safefs import _private_dir

IDENTITY='Ziokt/ContentFabric/private-identity/v1'
GRANT='Ziokt/ContentFabric/private-grant/v1'
PACKET='Ziokt/ContentFabric/private-packet/v1'
RECEIPT='Ziokt/ContentFabric/private-receipt/v1'
LEASE=60
READ_KINDS={'reader','news','personal.note','personal.bookmark','personal.collection','collection.member'}


def b64(data):return base64.b64encode(data).decode()
def un64(value):return base64.b64decode(value,validate=True)
def raw(key):return key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())
def pub(key):return key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
def key_for(secret,salt):return HKDF(hashes.SHA256(),32,salt,b'Ziokt/ContentFabric/private-share/v1').derive(secret)


class PrivateFabric:
    def __init__(self,fabric):
        self.f=fabric;self.db=fabric.db;self.files=_private_dir(fabric.root/'private-packets')
        with fabric.transaction():
            for sql in (
                'CREATE TABLE IF NOT EXISTS cf_private_keys(owner TEXT PRIMARY KEY,epoch INTEGER,public TEXT,secret BLOB,created INTEGER)',
                'CREATE TABLE IF NOT EXISTS cf_private_contacts(owner TEXT,alias TEXT,node TEXT,account TEXT,epoch INTEGER,public TEXT,peer TEXT,sync INTEGER,cursor INTEGER DEFAULT 0,PRIMARY KEY(owner,alias))',
                'CREATE TABLE IF NOT EXISTS cf_private_shares(id TEXT PRIMARY KEY,owner TEXT,contact TEXT,source TEXT,revision INTEGER,state TEXT,expires INTEGER,metadata BLOB,secret BLOB,envelope BLOB,delivered INTEGER DEFAULT 0)',
                'CREATE TABLE IF NOT EXISTS cf_private_share_objects(id TEXT PRIMARY KEY,object TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS cf_private_inbox(id TEXT PRIMARY KEY,owner TEXT,node TEXT,sender TEXT,revision INTEGER,state TEXT,expires INTEGER,envelope BLOB,lease INTEGER DEFAULT 0)',
                'CREATE TABLE IF NOT EXISTS cf_private_packets(id TEXT,revision INTEGER,position INTEGER,path TEXT,digest TEXT,PRIMARY KEY(id,revision,position))',
                'CREATE TABLE IF NOT EXISTS cf_reading_state(owner TEXT,kind TEXT,target TEXT,clock INTEGER,device TEXT,body BLOB,PRIMARY KEY(owner,kind,target))',
                'CREATE TABLE IF NOT EXISTS cf_gc_candidates(object TEXT PRIMARY KEY,seen INTEGER)',
                'CREATE TABLE IF NOT EXISTS cf_replica_checks(object TEXT PRIMARY KEY,verified INTEGER,state TEXT,error TEXT)',
                'CREATE TABLE IF NOT EXISTS cf_background_jobs(id TEXT PRIMARY KEY,state TEXT,attempts INTEGER,next_at INTEGER,error TEXT)',
            ):self.db.execute(sql)
            self.db.execute('INSERT OR IGNORE INTO migrations VALUES(13,unixepoch())')

    def _vault_key(self,owner):
        with self.f.store(owner) as store:
            return HKDF(hashes.SHA256(),32,None,b'Ziokt/ContentFabric/private-local/v1').derive(store.vault.key)

    def _seal(self,owner,data,aad):
        nonce=secrets.token_bytes(12);return nonce+AESGCM(self._vault_key(owner)).encrypt(nonce,data,encoded(aad))

    def _open(self,owner,data,aad):return AESGCM(self._vault_key(owner)).decrypt(data[:12],data[12:],encoded(aad))

    def identity(self,owner,rotate=False):
        ident(owner)
        with self.f.transaction():
            row=self.db.execute('SELECT * FROM cf_private_keys WHERE owner=?',(owner,)).fetchone()
            if row is None or rotate:
                epoch=(row['epoch'] if row else 0)+1;key=X25519PrivateKey.generate()
                self.db.execute('INSERT OR REPLACE INTO cf_private_keys VALUES(?,?,?,?,?)',
                                (owner,epoch,pub(key),self._seal(owner,raw(key),['identity',owner,epoch]),int(time.time())))
                row=self.db.execute('SELECT * FROM cf_private_keys WHERE owner=?',(owner,)).fetchone()
            self.backfill(owner)
            return sign({'schema':'ziokt.private-identity.v1','node':self.f.public,'account':owner,'epoch':row['epoch'],'box_public':row['public']},self.f.key,IDENTITY)

    def contact(self,owner,alias,identity,peer='',sync=False):
        ident(owner);ident(alias)
        if type(sync)is not bool:raise ValueError('reading synchronization permission')
        node=self.f.public if not peer else self.f.remote_peers[peer]['public_key']
        value=verify(identity,node,IDENTITY)
        if set(value)!={'schema','node','account','epoch','box_public'} or value['schema']!='ziokt.private-identity.v1' or value['node']!=node:raise ValueError('identity fields')
        ident(value['account'])
        if type(value['epoch'])is not int or not 1<=value['epoch']<2**53 or len(bytes.fromhex(value['box_public']))!=32:raise ValueError('identity key or epoch')
        with self.f.transaction():
            old=self.db.execute('SELECT * FROM cf_private_contacts WHERE owner=? AND alias=?',(owner,alias)).fetchone()
            if old and (old['node']!=node or old['account']!=value['account'] or value['epoch']<old['epoch'] or (value['epoch']==old['epoch'] and value['box_public']!=old['public'])):raise ValueError('contact identity substitution or rollback')
            cursor=old['cursor'] if old else 0
            self.db.execute('INSERT OR REPLACE INTO cf_private_contacts VALUES(?,?,?,?,?,?,?,?,?)',
                            (owner,alias,node,value['account'],value['epoch'],value['box_public'],peer,int(sync),cursor))
            if old and old['sync'] and not sync:
                for row in self.db.execute("SELECT id FROM cf_private_shares WHERE owner=? AND contact=? AND source='@reading-state' AND state<>'revoked'",(owner,alias)).fetchall():self.revoke(owner,row['id'])
            return {'alias':alias,'node':node,'account':value['account'],'epoch':value['epoch'],'reading_sync':sync}

    def create(self,owner,source,contact,expires,share=None,revision=1,snapshot=None):
        ident(owner);ident(contact);now=int(time.time())
        if type(expires)is not int or not now<expires<=now+90*86400:raise ValueError('private grant expiration')
        with self.f.transaction():
            target=self.db.execute('SELECT * FROM cf_private_contacts WHERE owner=? AND alias=?',(owner,contact)).fetchone()
            if not target:raise PermissionError('pinned recipient contact required')
            if source=='@reading-state':
                if not target['sync'] or snapshot is None:raise PermissionError('explicit reading synchronization contact required')
                meta={'kind':'reading-state','entries':snapshot};total=0;oid=''
            else:
                record=self.db.execute('SELECT * FROM records WHERE id=?',(source,)).fetchone()
                if record:
                    if record['owner']!=owner or record['origin']!=self.f.public or record['deleted']:raise PermissionError('owned active source required')
                    body=self.f._get(owner,source);oid=body.get('file_id')
                    if not oid:raise ValueError('record has no shareable file')
                else:body={};oid=source
                obj=self.f.object_info(owner,oid)
                if obj['owner']!=owner:raise PermissionError('only owner can grant a private object')
                metadata=json.loads(obj['metadata']);total=(metadata['size']+CHUNK_BYTES-1)//CHUNK_BYTES
                meta={'kind':'object','object':metadata,'record':body}
            if len(encoded(meta))>49152:raise ValueError('private metadata budget')
            if self.db.execute('SELECT count(*) FROM cf_private_shares WHERE owner=? AND state<>\'revoked\'',(owner,)).fetchone()[0]>=1024 and share is None:raise ValueError('private grant quota')
            share=share or secrets.token_hex(24);ident(share)
            eph=X25519PrivateKey.generate();salt=secrets.token_bytes(16)
            key=key_for(eph.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(target['public']))),salt)
            header={'schema':'ziokt.private-grant.v1','id':share,'revision':revision,'node':self.f.public,'sender':owner,
                    'recipient_node':target['node'],'recipient':target['account'],'key_epoch':target['epoch'],
                    'expires':expires,'total':total,'ephemeral':pub(eph),'salt':b64(salt),'state':'staging'}
            header['metadata']=b64(self._encrypt(key,header,-1,encoded(meta)))
            sealed=self._seal(owner,key,['share',share,revision])
            self.db.execute('INSERT OR REPLACE INTO cf_private_shares VALUES(?,?,?,?,?,?,?,?,?,?,0)',
                            (share,owner,contact,source,revision,'staging',expires,encoded(header),sealed,b''))
            if oid:self.db.execute('INSERT OR REPLACE INTO cf_private_share_objects VALUES(?,?)',(share,oid))
            return {'id':share,'revision':revision,'state':'staging','total':total}

    @staticmethod
    def _aad(header,position):return encoded([header['id'],header['revision'],header['recipient_node'],header['recipient'],position])

    @classmethod
    def _encrypt(cls,key,header,position,data):
        nonce=secrets.token_bytes(12);return nonce+AESGCM(key).encrypt(nonce,data,cls._aad(header,position))

    @classmethod
    def _decrypt(cls,key,header,position,data):return AESGCM(key).decrypt(data[:12],data[12:],cls._aad(header,position))

    def _write(self,id,revision,position,envelope):
        data=encoded(envelope);digest=hashlib.sha256(data).hexdigest();path=self.files/digest
        old=self.db.execute('SELECT 1 FROM cf_private_packets WHERE id=? AND revision=? AND position=?',(id,revision,position)).fetchone()
        if old is None and self.db.execute('SELECT count(*) FROM cf_private_packets').fetchone()[0]*(CHUNK_BYTES+2048)>=self.f.quota:raise ValueError('private ciphertext storage quota')
        if path.is_symlink():raise ValueError('private packet symlink')
        if path.exists() and hashlib.sha256(secure_read(path,65536)).hexdigest()!=digest:
            temporary=self.files/(digest+'.repair-'+secrets.token_hex(8))
            try:write_binary_exclusive(temporary,data);os.replace(temporary,path)
            finally:temporary.unlink(missing_ok=True)
        elif not path.exists():write_binary_exclusive(path,data)
        self.db.execute('INSERT OR REPLACE INTO cf_private_packets VALUES(?,?,?,?,?)',(id,revision,position,digest,digest))

    def step(self,owner,id):
        with self.f.transaction():
            row=self.db.execute('SELECT * FROM cf_private_shares WHERE id=? AND owner=?',(id,owner)).fetchone()
            if not row or row['expires']<=int(time.time()) or row['state']=='revoked':raise PermissionError('private grant unavailable')
            header=json.loads(row['metadata'])
            if row['state']=='ready':return {'id':id,'state':'ready'}
            key=self._open(owner,row['secret'],['share',id,row['revision']])
            done={r[0] for r in self.db.execute('SELECT position FROM cf_private_packets WHERE id=? AND revision=?',(id,row['revision']))}
            pending=[i for i in range(header['total']) if i not in done][:16]
            source=self.db.execute('SELECT object FROM cf_private_share_objects WHERE id=?',(id,)).fetchone()
            for i in pending:
                if self.db.execute('SELECT count(*) FROM cf_private_packets').fetchone()[0]*(CHUNK_BYTES+2048)>=self.f.quota:raise ValueError('private ciphertext storage quota')
                data=self.f.read_chunk(owner,source['object'],i)
                packet=sign({'id':id,'revision':row['revision'],'position':i,'ciphertext':b64(self._encrypt(key,header,i,data))},self.f.key,PACKET)
                self._write(id,row['revision'],i,packet);done.add(i)
            state='ready' if len(done)==header['total'] else 'staging'
            if state=='ready':
                header['state']='ready';envelope=sign(header,self.f.key,GRANT)
                self.db.execute('UPDATE cf_private_shares SET state=?,metadata=?,envelope=? WHERE id=?',('ready',encoded(header),encoded(envelope),id))
            return {'id':id,'state':state,'completed':len(done),'total':header['total']}

    def revoke(self,owner,id):
        with self.f.transaction():
            row=self.db.execute('SELECT * FROM cf_private_shares WHERE id=? AND owner=?',(id,owner)).fetchone()
            if not row:raise PermissionError('owned grant required')
            if row['state']=='revoked':return {'id':id,'state':'revoked'}
            header=json.loads(row['metadata']);header.update(state='revoked',revision=row['revision']+1,metadata='')
            envelope=sign(header,self.f.key,GRANT)
            self.db.execute("UPDATE cf_private_shares SET revision=?,state='revoked',secret=?,envelope=?,metadata=?,delivered=0 WHERE id=?",(header['revision'],b'',encoded(envelope),encoded(header),id))
            return {'id':id,'state':'revoked','revision':header['revision']}

    def rotate_share(self,owner,id):
        with self.f.transaction():
            row=self.db.execute('SELECT * FROM cf_private_shares WHERE id=? AND owner=?',(id,owner)).fetchone()
            if not row or row['state']=='revoked' or row['source']=='@reading-state':raise PermissionError('active object grant required')
            return self.create(owner,row['source'],row['contact'],row['expires'],id,row['revision']+1)

    def status(self,id,challenge):
        ident(id);ident(challenge)
        with self.f.lock:
            row=self.db.execute('SELECT revision,state,expires FROM cf_private_shares WHERE id=?',(id,)).fetchone()
            if not row:raise PermissionError('grant unavailable')
            return sign({'id':id,'revision':row['revision'],'state':row['state'],'expires':row['expires'],'challenge':challenge,'at':int(time.time())},self.f.key,RECEIPT)

    def deliver(self,envelope):
        node=envelope.get('public_key')
        if node!=self.f.public and node not in self.f.peers:raise PermissionError('pinned sending node required')
        header=verify(envelope,node,GRANT);id=header['id'];ident(id)
        fields={'schema','id','revision','node','sender','recipient_node','recipient','key_epoch','expires','total','ephemeral','salt','state','metadata'}
        if set(header)!=fields or header['schema']!='ziokt.private-grant.v1' or header['node']!=node or header['recipient_node']!=self.f.public:raise ValueError('private grant identity')
        ident(header['sender']);ident(header['recipient'])
        if any(type(header[k])is not int for k in ('revision','key_epoch','expires','total')) or not 1<=header['revision']<2**53 or not 0<=header['total']<=32768 or header['state'] not in {'ready','revoked'}:raise ValueError('private grant bounds')
        if header['state']=='ready':self._check_live(node,id,header['revision'])
        with self.f.transaction():
            old=self.db.execute('SELECT * FROM cf_private_inbox WHERE id=?',(id,)).fetchone()
            if old and (old['node']!=node or old['owner']!=header['recipient'] or old['sender']!=header['sender']):raise PermissionError('grant identity changed')
            if old and old['revision']==header['revision'] and old['envelope']==encoded(envelope):return sign({'id':id,'revision':header['revision'],'recipient':header['recipient']},self.f.key,RECEIPT)
            if old and (old['revision']>header['revision'] or old['state']=='revoked' or old['revision']==header['revision']):raise ValueError('grant rollback or revision conflict')
            if old is None and self.db.execute('SELECT count(*) FROM cf_private_inbox WHERE owner=?',(header['recipient'],)).fetchone()[0]>=4096:raise ValueError('private inbox quota')
            keyrow=self.db.execute('SELECT * FROM cf_private_keys WHERE owner=?',(header['recipient'],)).fetchone()
            if header['state']=='ready' and (not keyrow or keyrow['epoch']!=header['key_epoch'] or header['expires']<=int(time.time())):raise PermissionError('recipient key epoch or grant expired')
            if header['state']=='ready':
                secret=self._open(header['recipient'],keyrow['secret'],['identity',header['recipient'],keyrow['epoch']])
                key=key_for(X25519PrivateKey.from_private_bytes(secret).exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(header['ephemeral']))),un64(header['salt']))
                meta=strict_json(self._decrypt(key,header,-1,un64(header['metadata'])),65536)
                if meta.get('kind')=='reading-state':
                    allowed=self.db.execute('SELECT 1 FROM cf_private_contacts WHERE owner=? AND node=? AND account=? AND sync=1',(header['recipient'],node,header['sender'])).fetchone()
                    if not allowed:raise PermissionError('reciprocal reading sync consent required')
                    self.merge_reading(header['recipient'],meta['entries'])
            self.db.execute('INSERT OR REPLACE INTO cf_private_inbox VALUES(?,?,?,?,?,?,?,?,?)',
                            (id,header['recipient'],node,header['sender'],header['revision'],header['state'],header['expires'],encoded(envelope),int(time.time())+LEASE))
            return sign({'id':id,'revision':header['revision'],'recipient':header['recipient']},self.f.key,RECEIPT)

    def packet(self,id,revision,position):
        with self.f.lock:
            share=self.db.execute('SELECT state,expires,revision FROM cf_private_shares WHERE id=?',(id,)).fetchone()
            if not share or share['state']!='ready' or share['expires']<=int(time.time()) or share['revision']!=revision:raise PermissionError('active current grant required')
            row=self.db.execute('SELECT path,digest FROM cf_private_packets WHERE id=? AND revision=? AND position=?',(id,revision,position)).fetchone()
            if not row:raise ValueError('packet unavailable')
            blob=secure_read(self.files/row['path'],65536)
            if hashlib.sha256(blob).hexdigest()!=row['digest']:raise ValueError('private packet corruption')
            return strict_json(blob,65536)

    def _peer(self,node):
        return next((p for p in self.f.remote_peers.values() if p['public_key']==node),None)

    def _check_live(self,node,id,revision):
        challenge=secrets.token_hex(16)
        if node==self.f.public:proof=self.status(id,challenge)
        else:
            from .content_server import remote
            peer=self._peer(node)
            if not peer:raise PermissionError('origin peer unavailable')
            proof=remote(peer,{'operation':'private.status','arguments':{'id':id,'challenge':challenge}})
        status=verify(proof,node,RECEIPT)
        if (status['challenge']!=challenge or status['id']!=id or status['revision']!=revision
            or status['state']!='ready' or status['expires']<=int(time.time()) or abs(int(time.time())-status['at'])>LEASE):raise PermissionError('grant revoked, rekeyed or status stale')

    def read(self,owner,id,position=-1):
        ident(owner);ident(id)
        with self.f.lock:
            row=self.db.execute('SELECT * FROM cf_private_inbox WHERE id=? AND owner=?',(id,owner)).fetchone()
            if not row or row['state']!='ready' or row['expires']<=int(time.time()):raise PermissionError('private grant unavailable')
            header=verify(json.loads(row['envelope']),row['node'],GRANT)
            keyrow=self.db.execute('SELECT * FROM cf_private_keys WHERE owner=?',(owner,)).fetchone()
            if not keyrow or keyrow['epoch']!=header['key_epoch']:raise PermissionError('private identity rotated; grant must be rekeyed')
        self._check_live(row['node'],id,row['revision'])
        secret=self._open(owner,keyrow['secret'],['identity',owner,keyrow['epoch']])
        key=key_for(X25519PrivateKey.from_private_bytes(secret).exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(header['ephemeral']))),un64(header['salt']))
        if position==-1:return strict_json(self._decrypt(key,header,-1,un64(header['metadata'])),65536)
        if type(position)is not int or not 0<=position<header['total']:raise ValueError('private packet position')
        if row['node']==self.f.public:packet=self.packet(id,row['revision'],position)
        else:
            from .content_server import remote
            peer=self._peer(row['node'])
            with self.f.lock:cached=self.db.execute('SELECT path,digest FROM cf_private_packets WHERE id=? AND revision=? AND position=?',(id,row['revision'],position)).fetchone()
            packet=None
            if cached:
                try:
                    blob=secure_read(self.files/cached['path'],65536)
                    if hashlib.sha256(blob).hexdigest()==cached['digest']:packet=strict_json(blob,65536)
                except (OSError,ValueError):pass
            if packet is None:
                packet=remote(peer,{'operation':'private.packet','arguments':{'id':id,'revision':row['revision'],'position':position}})
                checked=verify(packet,row['node'],PACKET)
                if checked['id']!=id or checked['revision']!=row['revision'] or checked['position']!=position:raise ValueError('private packet scope')
                with self.f.transaction():self._write(id,row['revision'],position,packet)
        value=verify(packet,row['node'],PACKET)
        if value['id']!=id or value['revision']!=row['revision'] or value['position']!=position:raise ValueError('private packet scope')
        return {'data':b64(self._decrypt(key,header,position,un64(value['ciphertext']))),'position':position}

    def record_reading(self,owner,kind,target,value):
        if kind not in READ_KINDS:raise ValueError('reading state kind')
        if len(encoded(value))>16384:raise ValueError('reading state budget')
        count,size=self.db.execute('SELECT count(*),coalesce(sum(length(body)),0) FROM cf_reading_state WHERE owner=?',(owner,)).fetchone()
        prior=self.db.execute('SELECT length(body) FROM cf_reading_state WHERE owner=? AND kind=? AND target=?',(owner,kind,target)).fetchone()
        if (prior is None and count>=150000) or size-(prior[0] if prior else 0)+len(encoded(value))+28>64*1024**2:raise ValueError('reading synchronization quota')
        clock=self.db.execute('SELECT coalesce(max(clock),0)+1 FROM cf_reading_state WHERE owner=?',(owner,)).fetchone()[0]
        sealed=self._seal(owner,encoded(value),['reading',kind,target,clock,self.f.public])
        self.db.execute('INSERT OR REPLACE INTO cf_reading_state VALUES(?,?,?,?,?,?)',(owner,kind,target,clock,self.f.public,sealed))

    def snapshot(self,owner,after=0):
        with self.f.lock:
            cursor=(after,'','','') if type(after)is int else tuple(json.loads(after))
            if len(cursor)!=4:raise ValueError('reading cursor')
            rows=self.db.execute('SELECT * FROM cf_reading_state WHERE owner=? AND (clock,device,kind,target)>(?,?,?,?) ORDER BY clock,device,kind,target LIMIT 32',(owner,*cursor)).fetchall();entries=[]
            for row in rows:
                value=json.loads(self._open(owner,row['body'],['reading',row['kind'],row['target'],row['clock'],row['device']]))
                item={'kind':row['kind'],'target':row['target'],'clock':row['clock'],'device':row['device'],'value':value}
                if len(encoded(entries+[item]))>45000:break
                entries.append(item)
            return entries

    def backfill(self,owner):
        for kind,sql in (
            ('reader',"SELECT s.target,s.settings FROM subscriptions s WHERE s.owner=? AND s.kind='reader' AND NOT EXISTS(SELECT 1 FROM cf_reading_state c WHERE c.owner=s.owner AND c.kind='reader' AND c.target=s.target) LIMIT 32"),
            ('news',"SELECT n.article,n.is_read FROM news_readstate n WHERE n.owner=? AND NOT EXISTS(SELECT 1 FROM cf_reading_state c WHERE c.owner=n.owner AND c.kind='news' AND c.target=n.article) LIMIT 32")):
            for target,value in self.db.execute(sql,(owner,)).fetchall():self.record_reading(owner,kind,target,json.loads(value) if kind=='reader' else {'is_read':bool(value)})
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='library_personal'").fetchone():
            from .library_personal import PersonalLibrary
            library=PersonalLibrary(self.f)
            for row in self.db.execute("SELECT p.* FROM library_personal p WHERE p.owner=? AND NOT EXISTS(SELECT 1 FROM cf_reading_state c WHERE c.owner=p.owner AND c.kind='personal.'||p.kind AND c.target=p.id) LIMIT 32",(owner,)).fetchall():
                self.record_reading(owner,'personal.'+row['kind'],row['id'],{'book':row['book'],'body':library._open(row) if not row['deleted'] else {},'deleted':bool(row['deleted'])})
            added=0
            for row in self.db.execute('SELECT collection,book FROM library_collection_members WHERE owner=? LIMIT 4096',(owner,)).fetchall():
                target=hashlib.sha256((row['collection']+'\0'+row['book']).encode()).hexdigest()
                if not self.db.execute("SELECT 1 FROM cf_reading_state WHERE owner=? AND kind='collection.member' AND target=?",(owner,target)).fetchone():
                    self.record_reading(owner,'collection.member',target,{'collection':row['collection'],'book':row['book'],'present':True});added+=1
                    if added>=32:break

    def merge_reading(self,owner,entries):
        if type(entries)is not list or len(entries)>32:raise ValueError('reading sync page')
        for item in entries:
            if type(item)is not dict or set(item)!={'kind','target','clock','device','value'} or item['kind'] not in READ_KINDS:raise ValueError('reading sync fields')
            if type(item['clock'])is not int or not 1<=item['clock']<2**53 or type(item['device'])is not str or len(bytes.fromhex(item['device']))!=32 or type(item['target'])is not str or len(item['target'])>300 or type(item['value'])is not dict or len(encoded(item['value']))>16384:raise ValueError('reading sync bounds')
            old=self.db.execute('SELECT * FROM cf_reading_state WHERE owner=? AND kind=? AND target=?',(owner,item['kind'],item['target'])).fetchone()
            version=(item['clock'],item['device'])
            if item['kind'].startswith('personal.'):
                value=item['value']
                if set(value)!={'book','body','deleted'} or type(value['book'])is not str or len(value['book'])>300 or type(value['body'])is not dict or type(value['deleted'])is not bool:raise ValueError('personal sync payload')
                if old:
                    previous=json.loads(self._open(owner,old['body'],['reading',old['kind'],old['target'],old['clock'],old['device']]))
                    if previous['deleted'] and not value['deleted']:continue
                    if value['deleted'] and not previous['deleted'] and version<=(old['clock'],old['device']):
                        version=(self.db.execute('SELECT coalesce(max(clock),0)+1 FROM cf_reading_state WHERE owner=?',(owner,)).fetchone()[0],self.f.public)
            if old and version==(old['clock'],old['device']):
                prior=json.loads(self._open(owner,old['body'],['reading',old['kind'],old['target'],old['clock'],old['device']]))
                if prior!=item['value']:raise ValueError('reading event equivocation')
                continue
            if old and version<(old['clock'],old['device']):continue
            sealed=self._seal(owner,encoded(item['value']),['reading',item['kind'],item['target'],*version])
            self.db.execute('INSERT OR REPLACE INTO cf_reading_state VALUES(?,?,?,?,?,?)',(owner,item['kind'],item['target'],*version,sealed))
            if item['kind']=='reader':self.db.execute('INSERT OR REPLACE INTO subscriptions VALUES(?,?,?,?)',(owner,'reader',item['target'],encoded(item['value'])))
            elif item['kind']=='news':
                value=item['value']
                if set(value)!={'is_read'} or type(value['is_read'])is not bool:raise ValueError('news reading value')
                current=self.db.execute('SELECT revision FROM news_readstate WHERE owner=? AND article=?',(owner,item['target'])).fetchone()
                self.db.execute('INSERT OR REPLACE INTO news_readstate VALUES(?,?,?,?)',(owner,item['target'],int(value['is_read']),(current[0] if current else 0)+1))
            elif item['kind'].startswith('personal.'):
                from .library_personal import PersonalLibrary,MAX_ROWS,MAX_BYTES
                library=PersonalLibrary(self.f);kind=item['kind'].split('.')[1];ident(item['target'])
                prior=library._row(owner,kind,item['target']);value=item['value'];revision=(prior['revision'] if prior else 0)+1
                if prior and prior['book']!=value['book']:raise ValueError('personal sync identity changed book')
                if kind in {'note','bookmark'} and not value['deleted']:
                    body=value['body'];field='text' if kind=='note' else 'label'
                    if set(body)!={field,'anchor'} or type(body[field])is not str or len(body[field])>(8192 if kind=='note' else 512):raise ValueError('personal body')
                    library._anchor(body['anchor'])
                if kind=='collection' and not value['deleted'] and (set(value['body'])!={'name'} or type(value['body']['name'])is not str or len(value['body']['name'])>512):raise ValueError('collection body')
                body=b''
                if not value['deleted']:
                    nonce=secrets.token_bytes(12);body=nonce+AESGCM(library._key(owner)).encrypt(nonce,encoded(value['body']),library._aad(owner,kind,item['target'],value['book'],revision))
                count,size=self.db.execute('SELECT count(*),coalesce(sum(length(body)),0) FROM library_personal WHERE owner=?',(owner,)).fetchone()
                if (prior is None and count>=MAX_ROWS) or size-(len(prior['body']) if prior else 0)+len(body)>MAX_BYTES:raise ValueError('personal sync quota')
                self.db.execute('INSERT OR REPLACE INTO library_personal VALUES(?,?,?,?,?,?,?)',(owner,kind,item['target'],value['book'],revision,int(value['deleted']),body))
                if kind=='collection' and value['deleted']:self.db.execute('DELETE FROM library_collection_members WHERE owner=? AND collection=?',(owner,item['target']))
            elif item['kind']=='collection.member':
                from .library_personal import PersonalLibrary,MAX_MEMBERS
                PersonalLibrary(self.f);value=item['value']
                if set(value)!={'collection','book','present'} or type(value['present'])is not bool:raise ValueError('collection member sync')
                ident(value['collection'])
                if type(value['book'])is not str or not 1<=len(value['book'])<=300:raise ValueError('collection book')
                collection=self.db.execute("SELECT deleted FROM library_personal WHERE owner=? AND kind='collection' AND id=?",(owner,value['collection'])).fetchone()
                if collection and collection[0]:continue
                if value['present']:
                    if self.db.execute('SELECT count(*) FROM library_collection_members WHERE owner=? AND collection=?',(owner,value['collection'])).fetchone()[0]>=MAX_MEMBERS:raise ValueError('collection member quota')
                    self.db.execute('INSERT OR IGNORE INTO library_collection_members VALUES(?,?,?)',(owner,value['collection'],value['book']))
                else:self.db.execute('DELETE FROM library_collection_members WHERE owner=? AND collection=? AND book=?',(owner,value['collection'],value['book']))

    def collect(self,owner=None,grace=14*86400):
        now=int(time.time());removed=0;objects=0
        with self.f.transaction():
            rows=self.db.execute('SELECT p.* FROM cf_private_packets p LEFT JOIN cf_private_shares s ON s.id=p.id LEFT JOIN cf_private_inbox i ON i.id=p.id WHERE (s.id IS NULL AND i.id IS NULL) OR (s.id IS NOT NULL AND (s.state=\'revoked\' OR s.expires<=? OR s.revision<>p.revision)) OR (s.id IS NULL AND i.id IS NOT NULL AND (i.state=\'revoked\' OR i.expires<=? OR i.revision<>p.revision))',(now,now)).fetchall()
            for row in rows[:256]:
                if owner and not (self.db.execute('SELECT 1 FROM cf_private_shares WHERE id=? AND owner=?',(row['id'],owner)).fetchone() or self.db.execute('SELECT 1 FROM cf_private_inbox WHERE id=? AND owner=?',(row['id'],owner)).fetchone()):continue
                self.db.execute('DELETE FROM cf_private_packets WHERE id=? AND revision=? AND position=?',(row['id'],row['revision'],row['position']))
                if not self.db.execute('SELECT 1 FROM cf_private_packets WHERE path=?',(row['path'],)).fetchone():
                    path=self.files/row['path']
                    if path.is_file() and not path.is_symlink():path.unlink();removed+=1
            cursor=getattr(self.f,'_private_gc_object_cursor',{});offset=cursor.get(owner,0)
            candidates=self.db.execute('SELECT id,owner FROM objects'+(' WHERE owner=?' if owner else '')+' ORDER BY id LIMIT 128 OFFSET ?',((owner,offset) if owner else (offset,))).fetchall()
            cursor[owner]=offset+128 if len(candidates)==128 else 0;self.f._private_gc_object_cursor=cursor
            for obj in candidates:
                live=self.db.execute("SELECT 1 FROM content_references c JOIN records r ON r.id=c.record WHERE (c.object=? OR c.object IN(SELECT remote FROM locations WHERE local=?)) AND r.deleted=0 AND (r.expires=0 OR r.expires>?)",(obj['id'],obj['id'],now)).fetchone()
                granted=self.db.execute("SELECT 1 FROM cf_private_shares s JOIN cf_private_share_objects o ON o.id=s.id WHERE o.object=? AND s.state<>'revoked' AND s.expires>?",(obj['id'],now)).fetchone()
                if live or granted:self.db.execute('DELETE FROM cf_gc_candidates WHERE object=?',(obj['id'],));continue
                self.db.execute('INSERT OR IGNORE INTO cf_gc_candidates VALUES(?,?)',(obj['id'],now))
                seen=self.db.execute('SELECT seen FROM cf_gc_candidates WHERE object=?',(obj['id'],)).fetchone()[0]
                if now-seen>=grace:
                    try:self.f.release_object(obj['owner'],obj['id']);objects+=1
                    except ValueError:continue
                    self.db.execute('DELETE FROM cf_gc_candidates WHERE object=?',(obj['id'],))
            # A crash after writing an encrypted packet but before journaling it
            # leaves an unreferenced immutable file; reclaim only aged files.
            scanner=getattr(self.f,'_private_gc_scan',None)
            if scanner is None:scanner=os.scandir(self.files);self.f._private_gc_scan=scanner
            for _ in range(512):
                try:path=Path(next(scanner).path)
                except StopIteration:
                    scanner.close();self.f._private_gc_scan=None;break
                if path.is_file() and not path.is_symlink() and now-path.stat().st_mtime>=3600 and not self.db.execute('SELECT 1 FROM cf_private_packets WHERE path=?',(path.name,)).fetchone():path.unlink();removed+=1
            # Expired signed grants cannot authorize any future ready delivery.
            # Retain tombstones through an extra day before compacting them.
            self.db.execute('DELETE FROM cf_private_shares WHERE expires<? AND NOT EXISTS(SELECT 1 FROM cf_private_packets p WHERE p.id=cf_private_shares.id)'+(' AND owner=?' if owner else ''),((now-86400,owner) if owner else (now-86400,)))
            self.db.execute('DELETE FROM cf_private_inbox WHERE expires<? AND NOT EXISTS(SELECT 1 FROM cf_private_packets p WHERE p.id=cf_private_inbox.id)'+(' AND owner=?' if owner else ''),((now-86400,owner) if owner else (now-86400,)))
            self.db.execute('DELETE FROM cf_private_share_objects WHERE id NOT IN(SELECT id FROM cf_private_shares)')
            self.db.execute('DELETE FROM cf_gc_candidates WHERE object NOT IN(SELECT id FROM objects)')
            self.db.execute('DELETE FROM cf_replica_checks WHERE object NOT IN(SELECT id FROM objects)')
        return {'ciphertext_files_removed':removed,'objects_released':objects,'tombstones_retained':True}

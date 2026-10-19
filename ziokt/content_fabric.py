"""Opt-in durable content applications. No implicit native component or network access.

Chunk bytes use the existing SafeFS/ChunkStore formats. Each account has an
independent confidentiality/deduplication domain. Public catalogue federation
uses pinned node signatures; private records never enter the export log.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from email.utils import formatdate

from .chunkstore import ChunkStore, CHUNK_BYTES
from .safefs import Vault, _private_dir
from .protocol import encoded, secure_read, ProtocolError
from .security import sign, verify
from .cli import write_binary_exclusive

EVENT_DOMAIN = 'Ziokt/ContentFabric/event/v1'
ID = re.compile(r'[a-zA-Z0-9_-]{1,128}\Z')
GROUP = re.compile(r'[a-z0-9][a-z0-9+_-]*(?:\.[a-z0-9][a-z0-9+_-]*)+\Z')
MESSAGE = re.compile(r'<[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]{1,160}@[A-Za-z0-9.-]{1,120}>\Z')


def text(value, limit=4096, empty=False):
    if not isinstance(value, str) or len(value.encode()) > limit or '\x00' in value or (not value and not empty):
        raise ValueError('bounded text required')
    return value


def ident(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('invalid identifier')
    return value


def header(value, limit=512):
    text(value, limit)
    if '\r' in value or '\n' in value:raise ValueError('header injection')
    return value


def isbn(value):
    value = str(value).replace('-', '').replace(' ', '')
    if not value:return ''
    if len(value) == 13 and value.isdigit() and sum(int(c)*(1 if i%2==0 else 3) for i,c in enumerate(value))%10==0:return value
    if len(value) == 10 and value[:9].isdigit() and (value[-1].isdigit() or value[-1]=='X') and sum((10-i)*(10 if c=='X' else int(c)) for i,c in enumerate(value))%11==0:return value
    raise ValueError('invalid ISBN checksum')


def merkle_level(hashes):
    return [hashlib.sha256(b'node:'+bytes.fromhex(hashes[i])+bytes.fromhex(hashes[min(i+1,len(hashes)-1)])).hexdigest() for i in range(0,len(hashes),2)]


def merkle_root(hashes):
    hashes=list(hashes)
    if not hashes:return hashlib.sha256(b'empty').hexdigest()
    while len(hashes)>1:hashes=merkle_level(hashes)
    return hashes[0]


def merkle_verify(data, position, proof, root):
    if not isinstance(proof,list) or len(proof)>32:raise ValueError('Merkle proof')
    value=hashlib.sha256(data).hexdigest()
    for sibling in proof:
        if not isinstance(sibling,str) or not re.fullmatch('[a-f0-9]{64}',sibling):raise ValueError('Merkle sibling')
        a,b=(sibling,value) if position%2 else (value,sibling)
        value=hashlib.sha256(b'node:'+bytes.fromhex(a)+bytes.fromhex(b)).hexdigest()
        position//=2
    if value!=root:raise ValueError('chunk proof rejected')


class Fabric:
    def __init__(self, root, *, quota=2*1024**3, max_object=512*1024**2, peers=None):
        self.root = _private_dir(root)
        self.quota, self.max_object = quota, max_object
        self.remote_peers={}
        self.community_config={}
        self.peers = peers or {}  # public key -> explicit authority settings
        self.lock = threading.RLock()
        keypath = self.root/'node.key'
        if not keypath.exists():write_binary_exclusive(keypath, secrets.token_bytes(32))
        self.key = secure_read(keypath, 32)
        self.public = sign({}, self.key, EVENT_DOMAIN)['public_key']
        path = self.root/'content.sqlite'
        if path.is_symlink():raise ValueError('database symlink rejected')
        self.db = sqlite3.connect(path, timeout=15, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA recursive_triggers=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS source_health(alias TEXT PRIMARY KEY,successes INTEGER,failures INTEGER,quarantined_until INTEGER,verified INTEGER);
        CREATE TABLE IF NOT EXISTS locations(remote TEXT PRIMARY KEY,local TEXT NOT NULL,owner TEXT NOT NULL,verified INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS downloads(id TEXT PRIMARY KEY,owner TEXT NOT NULL,remote TEXT NOT NULL,upload TEXT NOT NULL,metadata BLOB NOT NULL,state TEXT NOT NULL,error TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY, applied INTEGER NOT NULL);
        INSERT OR IGNORE INTO migrations VALUES(1,unixepoch());
        CREATE TABLE IF NOT EXISTS objects(id TEXT PRIMARY KEY,owner TEXT NOT NULL,reference TEXT NOT NULL,metadata BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY,owner TEXT NOT NULL,metadata BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,kind TEXT NOT NULL,owner TEXT NOT NULL,visibility TEXT NOT NULL,body BLOB NOT NULL,origin TEXT NOT NULL,event TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0,expires INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS record_lookup ON records(kind,visibility,deleted,expires);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,envelope BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS cursors(peer TEXT PRIMARY KEY,cursor INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS conflicts(id INTEGER PRIMARY KEY,record TEXT,event TEXT,reason TEXT,at INTEGER);
        CREATE TABLE IF NOT EXISTS groups(name TEXT PRIMARY KEY,owner TEXT NOT NULL,description TEXT NOT NULL,visibility TEXT NOT NULL,posting TEXT NOT NULL,retention INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS group_articles(name TEXT,number INTEGER,message TEXT,PRIMARY KEY(name,number),UNIQUE(name,message));
        CREATE INDEX IF NOT EXISTS article_message ON group_articles(message);
        CREATE TABLE IF NOT EXISTS subscriptions(owner TEXT,kind TEXT,target TEXT,settings BLOB NOT NULL,PRIMARY KEY(owner,kind,target));
        CREATE TABLE IF NOT EXISTS reader(owner TEXT,book TEXT,state BLOB NOT NULL,PRIMARY KEY(owner,book));
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at INTEGER,owner TEXT,action TEXT,resource TEXT);
        CREATE TABLE IF NOT EXISTS rates(owner TEXT,action TEXT,window INTEGER,count INTEGER,PRIMARY KEY(owner,action));
        CREATE TABLE IF NOT EXISTS replication(peer TEXT,event TEXT,state TEXT,updated INTEGER,error TEXT,PRIMARY KEY(peer,event));
        ''')
        if not self.db.execute('SELECT 1 FROM migrations WHERE version=2').fetchone():
            self.db.executescript("""
            BEGIN IMMEDIATE;
            CREATE VIRTUAL TABLE IF NOT EXISTS record_search USING fts5(record UNINDEXED,text,tokenize='unicode61');
            CREATE TRIGGER IF NOT EXISTS record_search_insert AFTER INSERT ON records BEGIN
              INSERT INTO record_search(record,text) VALUES(new.id,CAST(new.body AS TEXT));
            END;
            CREATE TRIGGER IF NOT EXISTS record_search_delete AFTER DELETE ON records BEGIN
              DELETE FROM record_search WHERE record=old.id;
            END;
            CREATE TRIGGER IF NOT EXISTS record_search_update AFTER UPDATE ON records BEGIN
              DELETE FROM record_search WHERE record=old.id;
              INSERT INTO record_search(record,text) VALUES(new.id,CAST(new.body AS TEXT));
            END;
            INSERT INTO record_search(record,text) SELECT id,CAST(body AS TEXT) FROM records;
            INSERT INTO migrations VALUES(2,unixepoch());
            COMMIT;
            """)
        from .optimization import Profiles
        self.optimizations=Profiles(self.db,self.lock)
        with self.db:self.db.execute('INSERT OR IGNORE INTO migrations VALUES(3,unixepoch())')
        if not self.db.execute('SELECT 1 FROM migrations WHERE version=4').fetchone():
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                self.db.execute('CREATE TABLE IF NOT EXISTS content_references(record TEXT NOT NULL,object TEXT NOT NULL,role TEXT NOT NULL,name TEXT NOT NULL,PRIMARY KEY(record,object,role),FOREIGN KEY(record) REFERENCES records(id) ON DELETE CASCADE)')
                self.db.execute('CREATE INDEX IF NOT EXISTS reference_object ON content_references(object,record)')
                for row in self.db.execute('SELECT id,kind,body FROM records').fetchall():self._index_references(row['id'],row['kind'],json.loads(row['body']))
                self.db.execute('INSERT INTO migrations VALUES(4,unixepoch())')
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS feed_observations(owner TEXT,source TEXT,native TEXT,observed INTEGER NOT NULL,PRIMARY KEY(owner,source,native))')
            self.db.execute('INSERT OR IGNORE INTO migrations VALUES(5,unixepoch())')
        os.chmod(path,0o600)

    def close(self):
        with self.lock:self.db.close()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    @contextmanager
    def store(self, owner):
        ident(owner)
        domain=hashlib.sha256(owner.encode()).hexdigest()
        root=_private_dir(self.root/'accounts'/domain)
        keypath=root/'vault.key'
        if not keypath.exists():write_binary_exclusive(keypath,secrets.token_bytes(32))
        store=ChunkStore(Vault(root,'content',secure_read(keypath,32)),max_object=self.max_object,disk_bytes=self.quota)
        profile=self.optimizations.get(owner)['effective']
        store.db.execute('PRAGMA cache_size=-'+str(profile['sqlite_cache_kib']))
        try:yield store
        finally:store.close()

    def _rate(self, owner, action, maximum=120):
        now=int(time.time())//60
        row=self.db.execute('SELECT window,count FROM rates WHERE owner=? AND action=?',(owner,action)).fetchone()
        count=row['count']+1 if row and row['window']==now else 1
        if count>maximum:raise ValueError('rate limit')
        self.db.execute('INSERT OR REPLACE INTO rates VALUES(?,?,?,?)',(owner,action,now,count))

    def _audit(self, owner, action, resource):
        self.db.execute('INSERT INTO audit(at,owner,action,resource) VALUES(?,?,?,?)',(int(time.time()),owner,action,resource))

    def _get(self, owner, record, kind=None):
        row=self.db.execute('SELECT * FROM records WHERE id=? AND deleted=0 AND (expires=0 OR expires>?)',(record,int(time.time()))).fetchone()
        if row is None or (row['visibility']!='public' and row['owner']!=owner) or (kind and row['kind']!=kind):raise PermissionError('record unavailable')
        return json.loads(row['body'])

    def _event(self, owner, kind, record, body, visibility='private', deleted=False, expires=0):
        if visibility not in {'public','private'}:raise ValueError('visibility')
        if len(encoded(body))>65536:raise ValueError('record budget')
        old=self.db.execute('SELECT * FROM records WHERE id=?',(record,)).fetchone()
        if old and (old['origin']!=self.public or old['owner']!=owner or old['kind']!=kind):raise PermissionError('record ownership')
        if old and old['deleted'] and not deleted:raise ValueError('withdrawn identity cannot be republished')
        # Publishing a private record under the same ID is forbidden: use an explicit new public record.
        if old and old['visibility']!=visibility:raise ValueError('visibility immutable')
        previous=old['event'] if old else ''
        payload={'v':1,'record':record,'kind':kind,'owner':owner,'body':body,'visibility':visibility,'deleted':bool(deleted),'expires':expires,'previous':previous,'at':int(time.time())}
        envelope=sign(payload,self.key,EVENT_DOMAIN)
        event=hashlib.sha256(encoded(envelope)).hexdigest()
        self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?,?,?,?)',(record,kind,owner,visibility,encoded(body),self.public,event,int(deleted),expires))
        self._index_references(record,kind,body)
        if visibility=='public':self.db.execute('INSERT OR IGNORE INTO events(id,envelope) VALUES(?,?)',(event,encoded(envelope)))
        self._audit(owner,'withdraw' if deleted else kind+'.write',record)
        return {'id':record,'event':event,'origin':self.public,**body}

    def _index_references(self,record,kind,body):
        self.db.execute('DELETE FROM content_references WHERE record=?',(record,))
        if kind=='book' and isinstance(body.get('file_id'),str):
            self.db.execute('INSERT INTO content_references VALUES(?,?,?,?)',(record,body['file_id'],'book',''))
        attachments=body.get('attachments',[])
        if not isinstance(attachments,list) or len(attachments)>8:raise ValueError('attachment count')
        seen=set()
        for item in attachments:
            if not isinstance(item,dict) or set(item)!={'id','name','size','digest','mime','merkle_root','v'}:raise ValueError('attachment descriptor')
            if item['v']!=1 or type(item['size']) is not int or not 0<=item['size']<=self.max_object:raise ValueError('attachment size/version')
            if not isinstance(item['id'],str) or not re.fullmatch(r'cf1-[a-f0-9]{64}',item['id']) or item['id'] in seen:raise ValueError('attachment ID')
            seen.add(item['id']);self._attachment_name(item['name']);header(item['mime'],128)
            if not re.fullmatch(r'sha256:[a-f0-9]{64}',item['digest']) or not re.fullmatch(r'[a-f0-9]{64}',item['merkle_root']):raise ValueError('attachment digest')
            self.db.execute('INSERT INTO content_references VALUES(?,?,?,?)',(record,item['id'],'attachment',item['name']))

    @staticmethod
    def _attachment_name(value):
        header(value,255)
        if value in {'.','..'} or '/' in value or chr(92) in value or any(ord(c)<32 or ord(c)==127 for c in value):raise ValueError('attachment filename')
        return value

    def references(self,owner,oid):
        with self.lock:
            self.object_info(owner,oid)
            rows=self.db.execute("SELECT r.id,r.kind,r.origin,r.visibility,c.role,c.name FROM content_references c JOIN records r ON r.id=c.record WHERE c.object=? AND r.deleted=0 AND (r.expires=0 OR r.expires>?) AND (r.visibility='public' OR r.owner=?) ORDER BY r.id LIMIT 100",(oid,int(time.time()),owner)).fetchall()
            return {'object':oid,'items':[dict(row) for row in rows]}

    def begin(self, owner, upload, size, digest, mime='application/octet-stream', name=None):
        ident(owner);ident(upload);header(mime,128)
        if self.optimizations.get(owner)['effective']['collect_expired_uploads']:self.collect_uploads(owner)
        if not isinstance(digest,str) or not re.fullmatch('sha256:[a-f0-9]{64}',digest):raise ValueError('digest')
        if type(size) is not int or not 0<=size<=self.max_object:raise ValueError('size')
        with self.transaction():
            self._rate(owner,'upload',30)
            old=self.db.execute('SELECT owner,metadata FROM uploads WHERE id=?',(upload,)).fetchone()
            meta={'size':size,'digest':digest,'mime':mime}
            if name is not None:meta['name']=text(name,512)
            if old and (old['owner']!=owner or json.loads(old['metadata'])!=meta):raise ValueError('upload conflict')
            # Conservative node-wide reservation across accounts, persisted through crashes.
            used=self.db.execute("SELECT coalesce(sum(((json_extract(metadata,'$.size')+16383)/16384)*32768),0) FROM uploads").fetchone()[0]
            if not old and (used+((size+16383)//16384)*32768>self.quota or self.db.execute('SELECT count(*) FROM uploads').fetchone()[0]>=4096):raise ValueError('node storage quota (includes encryption overhead)')
            if shutil.disk_usage(self.root).free < size*2+1048576:raise ValueError('disk space')
            with self.store(owner) as store:result=store.begin(upload,size,digest,86400)
            self.db.execute('INSERT OR IGNORE INTO uploads VALUES(?,?,?)',(upload,owner,encoded(meta)))
            return result

    def _upload_owner(self, owner, upload):
        row=self.db.execute('SELECT * FROM uploads WHERE id=? AND owner=?',(upload,owner)).fetchone()
        if row is None:raise PermissionError('upload unavailable')
        return json.loads(row['metadata'])

    def upload_status(self, owner, upload):
        with self.lock:
            self._upload_owner(owner,upload)
            with self.store(owner) as store:return store.status(upload)

    def put(self, owner, upload, position, data):
        with self.lock:
            self._upload_owner(owner,upload)
            with self.store(owner) as store:return store.put(upload,position,'sha256:'+hashlib.sha256(data).hexdigest(),data)

    def finish(self, owner, upload):
        with self.transaction():
            meta=self._upload_owner(owner,upload)
            with self.store(owner) as store:
                reference=store.finish(upload)
                hashes=[r[0][7:] for r in store.db.execute('SELECT c.digest FROM members m JOIN chunks c ON c.tag=m.tag WHERE m.object=? ORDER BY m.position',(reference['manifest_digest'],))]
                meta={**meta,'merkle_root':merkle_root(hashes),'created_at':int(time.time())}
            # Opaque account-scoped ID: no cross-account plaintext existence oracle.
            oid='cf1-'+hashlib.sha256((owner+'\0'+reference['manifest_digest']).encode()).hexdigest()
            self.db.execute('INSERT OR IGNORE INTO objects VALUES(?,?,?,?)',(oid,owner,reference['manifest_digest'],encoded(meta)))
            self._audit(owner,'object.finish',oid)
            return {'id':oid,**meta,'chunk_bytes':CHUNK_BYTES}

    def object_info(self, owner, oid):
        alias=self.db.execute('SELECT local FROM locations WHERE remote=?',(oid,)).fetchone()
        row=self.db.execute('SELECT * FROM objects WHERE id=?',(alias[0] if alias else oid,)).fetchone()
        if row is None:raise PermissionError('object unavailable')
        if row['owner']!=owner:
            permitted=self.db.execute("SELECT 1 FROM content_references c JOIN records r ON r.id=c.record WHERE ((r.origin=? AND r.owner=? AND c.object=?) OR (? AND c.object=?)) AND r.deleted=0 AND r.visibility='public' AND (r.expires=0 OR r.expires>?) LIMIT 1",(self.public,row['owner'],row['id'],bool(alias),oid,int(time.time()))).fetchone()
            if not permitted:raise PermissionError('object unavailable')
        return dict(row)

    def read_chunk(self, owner, oid, position):
        with self.lock:
            row=self.object_info(owner,oid)
            if type(position) is not int or position<0:raise ValueError('position')
            with self.store(row['owner']) as store:
                member=store.db.execute('SELECT tag FROM members WHERE object=? AND position=?',(row['reference'],position)).fetchone()
                if not member:raise ValueError('chunk unavailable')
                return store._read(member[0])

    def chunk_proof(self, owner, oid, position):
        with self.lock:
            row=self.object_info(owner,oid)
            with self.store(row['owner']) as store:
                hashes=[r[0][7:] for r in store.db.execute('SELECT c.digest FROM members m JOIN chunks c ON c.tag=m.tag WHERE m.object=? ORDER BY m.position',(row['reference'],))]
            if type(position) is not int or not 0<=position<len(hashes):raise ValueError('chunk position')
            proof=[]
            while len(hashes)>1:
                proof.append(hashes[min(position^1,len(hashes)-1)])
                position//=2;hashes=merkle_level(hashes)
            return proof

    def verify_object(self, owner, oid):
        with self.lock:
            row=self.object_info(owner,oid)
            with self.store(row['owner']) as store:
                size=sum(len(part) for part in store.stream(row['reference']))
            return {'id':oid,'verified':True,'size':size}

    def create_book(self, owner, metadata):
        if not isinstance(metadata,dict):raise ValueError('metadata')
        allowed={'id','work_id','edition_id','file_id','title','subtitle','authors','translators','editors','publisher','year','language','isbn','doi','tags','description','cover','pages','format','license','provenance','relations','visibility','text'}
        if set(metadata)-allowed:raise ValueError('unknown book fields')
        value=dict(metadata)
        record=ident(value.pop('id',secrets.token_hex(16)))
        visibility=value.pop('visibility','private')
        for field in ('title','work_id','edition_id','file_id','license'):text(value.get(field),2048)
        for field in ('subtitle','publisher','language','doi','description','format','provenance','cover'):text(value.get(field,''),8192,empty=True)
        for field in ('authors','translators','editors','tags'):
            entries=value.setdefault(field,[])
            if not isinstance(entries,list) or len(entries)>64:raise ValueError('metadata list')
            for entry in entries:text(entry,512)
        for field in ('year','pages'):
            if field in value and (type(value[field]) is not int or not 0<=value[field]<=100000):raise ValueError(field)
        value['isbn']=isbn(value.get('isbn',''))
        text(value.get('text',''),8192,empty=True)
        with self.transaction():
            self._rate(owner,'book')
            obj=self.object_info(owner,value['file_id'])
            if obj['owner']!=owner:raise PermissionError('only owned objects may be published')
            value['file']=json.loads(obj['metadata'])
            value['updated_at']=int(time.time())
            return self._event(owner,'book',record,value,visibility)

    def search(self, owner, query='', kind='book', limit=30, offset=0, filters=None):
        text(query,256,empty=True)
        if kind not in {'book','article'} or type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=100000:raise ValueError('search bounds')
        profile=self.optimizations.get(owner,'library' if kind=='book' else 'netnews')['effective']
        limit=min(limit,profile['search_page_limit'])
        filters=filters or {}
        if not isinstance(filters,dict) or set(filters)-{'language','year','format','isbn','work_id','edition_id','author','tag'}:raise ValueError('search filters')
        clauses=["r.kind=?","r.deleted=0","(r.expires=0 OR r.expires>?)","(r.visibility='public' OR r.owner=?)"]
        values=[kind,int(time.time()),owner]
        for key,value in filters.items():
            if key=='year':
                if type(value) is not int or not 0<=value<=100000:raise ValueError('year filter')
            else:text(value,256)
            if key in {'author','tag'}:
                field='authors' if key=='author' else 'tags'
                clauses.append("EXISTS(SELECT 1 FROM json_each(r.body,'$."+field+"') WHERE value=?)")
            else:clauses.append("json_extract(r.body,'$."+key+"')=?")
            values.append(isbn(value) if key=='isbn' else value)
        join=''
        if query.strip():
            tokens=re.findall(r'[^\W_]+',query,flags=re.UNICODE)
            if not tokens:return {'items':[],'offset':offset,'limit':limit}
            expression=' AND '.join('"'+token.replace('"','""')+('"*' if profile['search_prefix'] else '"') for token in tokens[:16])
            join=' JOIN record_search s ON s.record=r.id'
            clauses.append('s.text MATCH ?');values.append(expression)
        with self.lock:
            rows=self.db.execute('SELECT r.* FROM records r'+join+' WHERE '+' AND '.join(clauses)+' ORDER BY r.id LIMIT ? OFFSET ?',(*values,limit,offset)).fetchall()
            fuzzy=False
            if not rows and query and profile['search_fuzzy']:
                import difflib
                base=[clause for clause in clauses if clause!='s.text MATCH ?']
                candidates=self.db.execute('SELECT r.* FROM records r WHERE '+' AND '.join(base)+' ORDER BY r.id LIMIT 1000',values[:-1]).fetchall()
                scored=[(difflib.SequenceMatcher(None,query.casefold(),str(json.loads(row['body']).get('title',json.loads(row['body']).get('subject',''))).casefold()).ratio(),row) for row in candidates]
                rows=[row for score,row in sorted(scored,key=lambda pair:(-pair[0],pair[1]['id'])) if score>=0.5][offset:offset+limit];fuzzy=True
            items=[{'id':r['id'],'origin':r['origin'],'visibility':r['visibility'],'local':r['origin']==self.public,**json.loads(r['body'])} for r in rows]
            result={'items':items,'offset':offset,'limit':limit,'index':'sqlite-fts5','fuzzy_fallback':fuzzy}
            if kind=='book' and profile['search_group_works']:
                works={}
                for item in items:works.setdefault((item['origin'],item.get('work_id',item['id'])),[]).append({'id':item['id'],'edition_id':item.get('edition_id'),'file_id':item.get('file_id')})
                result['works']=[{'origin':origin,'work_id':work,'versions':versions} for (origin,work),versions in works.items()];result['aggregation_scope']='current-authorized-page'
            return result

    def create_group(self, owner, name, description='', visibility='public', posting='members', retention=2592000):
        if not isinstance(name,str) or len(name)>160 or not GROUP.fullmatch(name):raise ValueError('hierarchical group required')
        text(description,1024,empty=True)
        if visibility not in {'public','private'} or posting not in {'members','owner'} or type(retention) is not int or not 60<=retention<=31536000:raise ValueError('group policy')
        with self.transaction():
            old=self.db.execute('SELECT * FROM groups WHERE name=?',(name,)).fetchone()
            if old:
                if old['owner']!=owner:raise PermissionError('group owner')
                if (old['description'],old['visibility'],old['posting'],old['retention'])!=(description,visibility,posting,retention):raise ValueError('group policy conflict')
            self.db.execute('INSERT OR IGNORE INTO groups VALUES(?,?,?,?,?,?)',(name,owner,description,visibility,posting,retention))
            return dict(self.db.execute('SELECT * FROM groups WHERE name=?',(name,)).fetchone())

    def groups(self, owner):
        with self.lock:return {'items':[dict(row) for row in self.db.execute("SELECT * FROM groups WHERE visibility='public' OR owner=? ORDER BY name",(owner,))]}

    def post(self, owner, groups, subject, body, message_id=None, references=None, author=None, native_headers=None, raw_article=None, attachments=None):
        if not isinstance(groups,list) or not 1<=len(groups)<=8 or len(set(groups))!=len(groups):raise ValueError('groups')
        header(subject);text(body,8192,empty=True)
        if author is not None and author!=owner:raise PermissionError('From must match authenticated identity')
        references=references or []
        if not isinstance(references,list) or len(references)>32 or any(not isinstance(v,str) or not MESSAGE.fullmatch(v) for v in references):raise ValueError('References')
        mid=message_id or '<'+secrets.token_hex(16)+'@'+self.public[:24]+'.ziokt>'
        if not MESSAGE.fullmatch(mid):raise ValueError('Message-ID')
        with self.transaction():
            self._rate(owner,'post',60)
            policies=[]
            for name in groups:
                policy=self.db.execute('SELECT * FROM groups WHERE name=?',(name,)).fetchone()
                if not policy or (policy['owner']!=owner and (policy['posting']=='owner' or policy['visibility']=='private')):raise PermissionError('posting denied')
                policies.append(policy)
            visibility='private' if any(p['visibility']=='private' for p in policies) else 'public'
            if len({p['visibility'] for p in policies})!=1:raise ValueError('cannot crosspost between privacy domains')
            published_attachments=[]
            if not isinstance(attachments if attachments is not None else [],list) or len(attachments or [])>8:raise ValueError('attachment count')
            for entry in attachments or []:
                if not isinstance(entry,dict) or set(entry)!={'id','name'}:raise ValueError('attachment input')
                name=self._attachment_name(entry['name']);obj=self.object_info(owner,entry['id'])
                if obj['owner']!=owner:raise PermissionError('only owned objects may be attached')
                metadata=json.loads(obj['metadata'])
                published_attachments.append({'v':1,'id':entry['id'],'name':name,**{key:metadata[key] for key in ('size','digest','mime','merkle_root')}})
            value={'message_id':mid,'newsgroups':groups,'subject':subject,'body':body,'from':owner,'date':formatdate(usegmt=True),'references':references,'path':[self.public],'content_type':'text/plain; charset=utf-8'}
            if published_attachments:value['attachments']=published_attachments
            if native_headers is not None:
                if not isinstance(native_headers,dict) or set(native_headers)-{'From','Date','Path','Organization'}:raise ValueError('native headers')
                for field,content in native_headers.items():header(content)
                route=native_headers.get('Path','').split('!')
                if self.public in route:raise ValueError('NNTP propagation loop')
                value.update({'from':native_headers.get('From',owner),'date':native_headers.get('Date',value['date']),'path':[self.public]+[part for part in route if part]})
                if not isinstance(raw_article,bytes) or len(raw_article)>16000:raise ValueError('native article budget')
                value['provenance']={'protocol':'nntp','peer_account':owner,'publisher_signature_verified':False,'headers':native_headers,'raw_sha256':hashlib.sha256(raw_article).hexdigest(),'raw_chunks':[base64.b64encode(raw_article[i:i+3072]).decode() for i in range(0,len(raw_article),3072)]}
            existing=self.db.execute('SELECT * FROM records WHERE id=?',(mid,)).fetchone()
            if existing:
                prior=json.loads(existing['body'])
                if existing['deleted'] or existing['owner']!=owner or prior.get('attachments',[])!=value.get('attachments',[]) or any(prior.get(k)!=value[k] for k in ('newsgroups','subject','body','from','references')):raise ValueError('Message-ID conflict')
                return {'id':mid,**prior,'duplicate':True}
            expiry=int(time.time())+min(p['retention'] for p in policies)
            result=self._event(owner,'article',mid,value,visibility,expires=expiry)
            self._number(mid,groups)
            return result

    def _number(self, mid, groups):
        for name in groups:
            number=self.db.execute('SELECT coalesce(max(number),0)+1 FROM group_articles WHERE name=?',(name,)).fetchone()[0]
            self.db.execute('INSERT OR IGNORE INTO group_articles VALUES(?,?,?)',(name,number,mid))

    def articles(self, owner, group, low=1, limit=100):
        if type(low) is not int or low<1 or type(limit) is not int or not 1<=limit<=1000:raise ValueError('article range')
        with self.lock:
            policy=self.db.execute('SELECT * FROM groups WHERE name=?',(group,)).fetchone()
            if policy is None or (policy['visibility']!='public' and policy['owner']!=owner):raise PermissionError('group unavailable')
            rows=self.db.execute("SELECT a.number,r.id,r.body FROM group_articles a JOIN records r ON r.id=a.message WHERE a.name=? AND a.number>=? AND r.deleted=0 AND (r.visibility='public' OR r.owner=?) AND (r.expires=0 OR r.expires>?) ORDER BY a.number LIMIT ?",(group,low,owner,int(time.time()),limit)).fetchall()
            return {'items':[{'number':r['number'],'id':r['id'],**json.loads(r['body'])} for r in rows]}

    def withdraw(self, owner, record):
        with self.transaction():
            row=self.db.execute('SELECT * FROM records WHERE id=?',(record,)).fetchone()
            if row is None or row['owner']!=owner or row['origin']!=self.public:raise PermissionError('withdrawal authority')
            if row['deleted']:return {'id':record,'deleted':True,'duplicate':True}
            result=self._event(owner,row['kind'],record,{},row['visibility'],True)
            return {**result,'deleted':True}

    def export(self, after=0, limit=64):
        if type(after) is not int or after<0 or type(limit) is not int or not 1<=limit<=64:raise ValueError('sync bounds')
        with self.lock:
            rows=self.db.execute('SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?',(after,limit)).fetchall()
            return {'node':self.public,'events':[json.loads(r['envelope']) for r in rows],'cursor':rows[-1]['seq'] if rows else after}

    def ingest(self, envelopes):
        if not isinstance(envelopes,list) or len(envelopes)>64:raise ValueError('sync batch')
        accepted=0
        with self.transaction():
            for envelope in envelopes:
                origin=envelope.get('public_key')
                if origin!=self.public and origin not in self.peers:raise PermissionError('publisher not pinned')
                value=verify(envelope,origin,EVENT_DOMAIN)
                if set(value)!={'v','record','kind','owner','body','visibility','deleted','expires','previous','at'} or value['v']!=1 or value['kind'] not in {'book','article'} or value['visibility']!='public' or type(value['deleted']) is not bool or type(value['expires']) is not int or value['expires']<0:raise ValueError('event schema')
                text(value['record'],300);ident(value['owner'])
                if not isinstance(value['body'],dict):raise ValueError('body')
                eid=hashlib.sha256(encoded(envelope)).hexdigest()
                if self.db.execute('SELECT 1 FROM events WHERE id=?',(eid,)).fetchone():continue
                old=self.db.execute('SELECT * FROM records WHERE id=?',(value['record'],)).fetchone()
                reason=None
                if old and old['origin']!=origin:reason='identity collision'
                elif old and old['deleted'] and not value['deleted']:reason='tombstone dominates'
                elif old and not value['deleted'] and old['event']!=value['previous']:reason='missing or conflicting predecessor'
                elif not old and value['previous'] and not value['deleted']:raise ValueError('missing predecessor; retry ordered history')
                if reason:
                    self.db.execute('INSERT INTO conflicts(record,event,reason,at) VALUES(?,?,?,?)',(value['record'],eid,reason,int(time.time())))
                    continue
                if value['kind']=='article' and not value['deleted']:
                    body=value['body']
                    if not MESSAGE.fullmatch(value['record']) or body.get('message_id')!=value['record']:raise ValueError('article ID')
                    header(body.get('subject'));text(body.get('body'),8192,empty=True)
                    names=body.get('newsgroups')
                    if not isinstance(names,list) or not 1<=len(names)<=8 or any(not isinstance(n,str) or not GROUP.fullmatch(n) for n in names):raise ValueError('groups')
                    grants=self.peers.get(origin,{})
                    permitted=grants.get('groups',[])
                    if any(n not in permitted for n in names):raise PermissionError('news group not authorized for publisher')
                    for name in names:
                        policy=self.db.execute('SELECT * FROM groups WHERE name=?',(name,)).fetchone()
                        if not policy or policy['visibility']!='public':raise PermissionError('local public group subscription required')
                    self._number(value['record'],names)
                self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?,?,?,?)',(value['record'],value['kind'],value['owner'],'public',encoded(value['body']),origin,eid,int(value['deleted']),value['expires']))
                self._index_references(value['record'],value['kind'],value['body'])
                self.db.execute('INSERT INTO events(id,envelope) VALUES(?,?)',(eid,encoded(envelope)))
                accepted+=1
            return {'accepted':accepted,'durable':True}

    def state(self, owner, kind, target, settings=None):
        ident(owner);text(target,300)
        if kind not in {'library','newsgroup','author','reader'}:raise ValueError('subscription kind')
        with self.transaction():
            if kind=='reader':self._get(owner,target,'book')
            if settings is not None:
                if not isinstance(settings,dict) or len(encoded(settings))>8192:raise ValueError('settings budget')
                self.db.execute('INSERT OR REPLACE INTO subscriptions VALUES(?,?,?,?)',(owner,kind,target,encoded(settings)))
            row=self.db.execute('SELECT settings FROM subscriptions WHERE owner=? AND kind=? AND target=?',(owner,kind,target)).fetchone()
            return {'kind':kind,'target':target,'settings':json.loads(row[0]) if row else {}}

    def maintenance(self):
        # Retain immutable event/tombstone history; old offline peers cannot resurrect it.
        # Physical object collection is explicit until references have been reconciled.
        with self.transaction():
            expired=self.db.execute('SELECT count(*) FROM records WHERE deleted=0 AND expires>0 AND expires<=?',(int(time.time()),)).fetchone()[0]
            self.db.execute('DELETE FROM rates WHERE window<?',(int(time.time())//60-2,))
            integrity=self.db.execute('PRAGMA quick_check').fetchone()[0]
            return {'expired_hidden':expired,'database':integrity,'tombstones_retained':True}

    def health(self,owner):
        with self.lock:
            integrity=self.db.execute('PRAGMA quick_check').fetchone()[0]
            return {'schema':'ziokt.content-health.v1','node':self.public,'native_store':integrity,'account':owner,'objects':self.db.execute('SELECT count(*) FROM objects WHERE owner=?',(owner,)).fetchone()[0],'downloads':[dict(row) for row in self.db.execute('SELECT id,state,error FROM downloads WHERE owner=? ORDER BY id LIMIT 30',(owner,))],'observations':{'database_checked_now':True,'all_objects_verified':False,'end_to_end_verified':False},'guarantees':{'private_catalogue_exported':False,'ciphertext_at_rest':'SafeFS AEAD','metadata_at_rest':'private SQLite, not encrypted','remote_erasure_guaranteed':False}}

    def objects(self,owner,limit=30,offset=0):
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=100000:raise ValueError('object pagination')
        with self.lock:
            rows=self.db.execute('SELECT id,metadata FROM objects WHERE owner=? ORDER BY id LIMIT ? OFFSET ?',(owner,limit,offset)).fetchall()
            return {'items':[{'id':row['id'],**json.loads(row['metadata'])} for row in rows],'offset':offset,'limit':limit}

    def abort_upload(self,owner,upload):
        with self.transaction():
            self._upload_owner(owner,upload)
            with self.store(owner) as store:
                result=store.abort(upload);store.gc()
            self.db.execute('DELETE FROM uploads WHERE owner=? AND id=?',(owner,upload));self._audit(owner,'upload.abort',upload)
            return result

    def discard_staged_upload(self,owner,upload):
        """Drop only a failed MIME staging lease, preserving shared application data."""
        with self.transaction():
            if not self.db.execute('SELECT 1 FROM uploads WHERE id=? AND owner=?',(upload,owner)).fetchone():return {'discarded':False}
            with self.store(owner) as store:
                status=store.status(upload)
                if status['state']=='complete':
                    reference=status['object']
                    active=self.db.execute("SELECT 1 FROM content_references c JOIN records r ON r.id=c.record JOIN objects o ON o.id=c.object WHERE o.owner=? AND o.reference=? AND r.deleted=0 AND (r.expires=0 OR r.expires>?) LIMIT 1",(owner,reference,int(time.time()))).fetchone()
                    other=store.db.execute("SELECT 1 FROM uploads WHERE object=? AND state='complete' AND id!=? UNION SELECT 1 FROM pins WHERE object=? LIMIT 1",(reference,upload,reference)).fetchone()
                    if active and not other:return {'discarded':False,'retained_by_application':True}
                    store.release(reference,upload)
                    if not store.db.execute('SELECT 1 FROM objects WHERE id=?',(reference,)).fetchone():
                        self.db.execute('DELETE FROM locations WHERE local IN (SELECT id FROM objects WHERE owner=? AND reference=?)',(owner,reference))
                        self.db.execute('DELETE FROM objects WHERE owner=? AND reference=?',(owner,reference))
                else:store.abort(upload)
                store.gc()
            self.db.execute('DELETE FROM uploads WHERE id=? AND owner=?',(upload,owner));self._audit(owner,'upload.discard-staged',upload)
            return {'discarded':True}

    def release_object(self,owner,oid):
        with self.transaction():
            row=self.db.execute('SELECT * FROM objects WHERE id=? AND owner=?',(oid,owner)).fetchone()
            if row is None:raise PermissionError('owned object required')
            retained=self.db.execute("SELECT 1 FROM content_references c JOIN records r ON r.id=c.record WHERE c.object=? AND r.owner=? AND r.origin=? AND r.deleted=0 AND (r.expires=0 OR r.expires>?) LIMIT 1",(oid,owner,self.public,int(time.time()))).fetchone()
            if retained:raise ValueError('withdraw local application references before releasing object')
            with self.store(owner) as store:
                if store.db.execute('SELECT 1 FROM pins WHERE object=?',(row['reference'],)).fetchone():raise ValueError('other application retains object')
                leases=[entry[0] for entry in store.db.execute("SELECT id FROM uploads WHERE object=? AND state='complete'",(row['reference'],))]
                for lease in leases:store.release(row['reference'],lease)
                collected=store.gc()
            self.db.executemany('DELETE FROM uploads WHERE id=? AND owner=?',[(lease,owner) for lease in leases])
            self.db.execute('DELETE FROM locations WHERE local=? AND owner=?',(oid,owner));self.db.execute('DELETE FROM objects WHERE id=?',(oid,));self._audit(owner,'object.release',oid)
            return {'id':oid,'released':True,**collected}

    def collect_uploads(self,owner):
        with self.transaction():
            with self.store(owner) as store:
                expired=[row[0] for row in store.db.execute("SELECT id FROM uploads WHERE expires<=? AND state='uploading'",(int(time.time()),))]
                collected=store.gc()
            self.db.executemany('DELETE FROM uploads WHERE id=? AND owner=?',[(upload,owner) for upload in expired])
            return {'expired_uploads':len(expired),**collected}

    def download_control(self,owner,job,paused):
        if type(paused) is not bool:raise ValueError('pause state')
        with self.transaction():
            row=self.db.execute('SELECT state FROM downloads WHERE owner=? AND id=?',(owner,job)).fetchone()
            if not row:raise PermissionError('download unavailable')
            if row[0]=='complete':return {'job':job,'state':'complete'}
            self.db.execute('UPDATE downloads SET state=? WHERE id=?',('paused' if paused else 'running',job))
            return {'job':job,'state':'paused' if paused else 'running'}

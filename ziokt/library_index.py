"""Resumable account-private document indexing, encrypted pages and keyed terms.

No plaintext document body or vocabulary is stored in SQLite. Query term equality
and document sizes remain visible within one account; this is not oblivious search.
"""
import hashlib
import hmac
import json
import re
import secrets
import time
import unicodedata
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from .protocol import encoded

MAX_CHARACTERS=2*1024*1024
MAX_TERMS=32768
ACCOUNT_TERMS=200000
ACCOUNT_BYTES=64*1024*1024
MIMES={'text/plain','text/markdown','text/html','application/epub+zip','application/pdf'}


def initialize(fabric):
    with fabric.transaction():
        statements='''
        CREATE TABLE IF NOT EXISTS library_index_jobs(owner TEXT,id TEXT,book TEXT,file_id TEXT,digest TEXT,state TEXT,chapter INTEGER,offset INTEGER,chapters INTEGER,characters INTEGER,revision INTEGER,lease TEXT,lease_until INTEGER,error TEXT,updated INTEGER,PRIMARY KEY(owner,id));
        CREATE TABLE IF NOT EXISTS library_index_pages(owner TEXT,job TEXT,chapter INTEGER,offset INTEGER,body BLOB NOT NULL,characters INTEGER,PRIMARY KEY(owner,job,chapter,offset),FOREIGN KEY(owner,job) REFERENCES library_index_jobs(owner,id));
        CREATE TABLE IF NOT EXISTS library_index_tails(owner TEXT,job TEXT,body BLOB NOT NULL,PRIMARY KEY(owner,job),FOREIGN KEY(owner,job) REFERENCES library_index_jobs(owner,id));
        CREATE TABLE IF NOT EXISTS library_index_terms(owner TEXT,job TEXT,term BLOB,PRIMARY KEY(owner,job,term),FOREIGN KEY(owner,job) REFERENCES library_index_jobs(owner,id));
        CREATE INDEX IF NOT EXISTS library_index_term_query ON library_index_terms(owner,term,job);
        CREATE TABLE IF NOT EXISTS library_index_documents(owner TEXT,book TEXT,job TEXT,file_id TEXT,digest TEXT,characters INTEGER,PRIMARY KEY(owner,book),FOREIGN KEY(owner,job) REFERENCES library_index_jobs(owner,id));
        '''
        for statement in statements.split(';'):
            if statement.strip():fabric.db.execute(statement)
        fabric.db.execute('INSERT OR IGNORE INTO migrations VALUES(12,unixepoch())')


def words(value):
    normalized=unicodedata.normalize('NFKD',unicodedata.normalize('NFKC',value).casefold())
    normalized=''.join(char for char in normalized if not unicodedata.combining(char))
    return sorted(set(word for word in re.findall(r'[^\W_]+',normalized,flags=re.UNICODE) if len(word)<=128))


class DocumentIndex:
    def __init__(self,fabric):self.fabric=fabric;self.db=fabric.db

    def key(self,owner,domain):
        with self.fabric.lock:
            with self.fabric.store(owner) as store:return HKDF(hashes.SHA256(),32,None,b'Ziokt/Library/fulltext/v1/'+domain).derive(store.vault.key)

    def source(self,owner,book):
        with self.fabric.lock:
            body=self.fabric._get(owner,book,'book');row=self.fabric.object_info(owner,body['file_id']);metadata=json.loads(row['metadata'])
            if metadata['size']>16*1024*1024 or metadata['mime'] not in MIMES:raise ValueError('document index format or source budget')
            return body['file_id'],metadata['digest']

    def row(self,owner,job):
        if not isinstance(job,str) or not re.fullmatch('[a-f0-9]{64}',job):raise ValueError('index job identity')
        row=self.db.execute('SELECT * FROM library_index_jobs WHERE owner=? AND id=?',(owner,job)).fetchone()
        if row is None:raise PermissionError('index job unavailable')
        return row

    def status(self,owner,job):
        with self.fabric.lock:
            row=self.row(owner,job)
            if row['state']!='cancelled':
                if self.source(owner,row['book'])!=(row['file_id'],row['digest']):raise ValueError('document source changed; start a new index')
            return {key:row[key] for key in ('id','book','state','chapter','offset','chapters','characters','revision','error','updated')}|{'encrypted_pages':True,'keyed_terms':True,'publicly_federated':False}

    def start(self,owner,book):
        from .content_api import invoke
        file_id,digest=self.source(owner,book)
        job=hashlib.sha256(encoded(['ziokt.library-index.v1',owner,book,file_id,digest])).hexdigest()
        with self.fabric.lock:existing=self.db.execute('SELECT state FROM library_index_jobs WHERE owner=? AND id=?',(owner,job)).fetchone()
        if existing and existing['state'] not in ('cancelled',):return self.status(owner,job)
        manifest=invoke(self.fabric,owner,'library.reader.manifest',{'id':book,'limit':1,'offset':0})
        chapters=manifest['chapter_count']
        if type(chapters) is not int or not 1<=chapters<=1024:raise ValueError('document index chapter budget')
        with self.fabric.transaction():
            if self.source(owner,book)!=(file_id,digest):raise ValueError('document source changed')
            if not existing and self.db.execute('SELECT count(*) FROM library_index_jobs WHERE owner=?',(owner,)).fetchone()[0]>=10000:raise ValueError('document index job quota')
            self.db.execute("INSERT OR IGNORE INTO library_index_jobs VALUES(?,?,?,?,?,'queued',0,0,?,0,0,'',0,'',?)",(owner,job,book,file_id,digest,chapters,int(time.time())))
            self.db.execute("UPDATE library_index_jobs SET state='queued',chapter=0,offset=0,characters=0,revision=revision+1,error='',updated=? WHERE owner=? AND id=? AND state='cancelled'",(int(time.time()),owner,job))
        return self.status(owner,job)

    def step(self,owner,job,revision):
        from .content_api import invoke
        if type(revision) is not int or not 0<=revision<=100000:raise ValueError('index revision')
        lease=secrets.token_hex(16);now=int(time.time())
        with self.fabric.transaction():
            row=self.row(owner,job)
            if self.source(owner,row['book'])!=(row['file_id'],row['digest']):raise ValueError('document source changed')
            if revision<row['revision'] or row['state']=='complete':return self.status(owner,job)|{'duplicate':True}
            if revision!=row['revision']:raise ValueError('index revision conflict')
            if row['state'] in ('failed','cancelled'):raise ValueError('index job cannot run; cancel and restart explicitly')
            if row['lease'] and row['lease_until']>now:return self.status(owner,job)|{'busy':True}
            tail=self.db.execute('SELECT body FROM library_index_tails WHERE owner=? AND job=?',(owner,job)).fetchone()
            self.db.execute("UPDATE library_index_jobs SET state='indexing',lease=?,lease_until=? WHERE owner=? AND id=?",(lease,now+30,owner,job))
        try:
            result=invoke(self.fabric,owner,'library.reader.chapter',{'id':row['book'],'chapter':row['chapter'],'offset':row['offset'],'limit':16384,'fragment':''})
            value=result['text'];raw=value.encode()
            page_key=self.key(owner,b'pages');term_key=self.key(owner,b'terms')
            carry={'value':'','skip':False}
            if tail:
                blob=tail['body'];carry=json.loads(AESGCM(page_key).decrypt(blob[:12],blob[12:],encoded(['tail',owner,job,revision])))
            normalized=unicodedata.normalize('NFKD',unicodedata.normalize('NFKC',value).casefold())
            normalized=''.join(char for char in normalized if not unicodedata.combining(char))
            combined=carry['value']+normalized;next_carry={'value':'','skip':False}
            if carry['skip']:
                combined=re.sub(r'^[^\W_]+','',combined,flags=re.UNICODE)
                if not combined and result['next_offset'] is not None:next_carry['skip']=True
            if result['next_offset'] is not None:
                suffix=re.search(r'[^\W_]+$',combined,flags=re.UNICODE)
                if suffix:
                    pending=suffix.group();next_carry={'value':pending if len(pending)<=128 else '','skip':len(pending)>128};combined=combined[:suffix.start()]
            terms=words(combined)
            nonce=secrets.token_bytes(12);aad=encoded([owner,job,row['chapter'],row['offset']]);encrypted=nonce+AESGCM(page_key).encrypt(nonce,raw,aad)
            tokens=[hmac.new(term_key,term.encode(),hashlib.sha256).digest() for term in terms]
            next_offset=result['next_offset'];chapter=row['chapter']+(next_offset is None);offset=0 if next_offset is None else next_offset
            if next_offset is not None and (type(next_offset) is not int or next_offset<=row['offset']):raise ValueError('parser index cursor did not advance')
            with self.fabric.transaction():
                current=self.row(owner,job)
                if current['lease']!=lease or current['revision']!=revision:return self.status(owner,job)|{'stale_worker':True}
                if self.source(owner,row['book'])!=(row['file_id'],row['digest']):raise ValueError('document source changed')
                if row['characters']+len(value)>MAX_CHARACTERS:raise ValueError('document text quota')
                used=self.db.execute('SELECT coalesce(sum(length(body)),0) FROM library_index_pages WHERE owner=?',(owner,)).fetchone()[0]
                if used+len(encrypted)>ACCOUNT_BYTES:raise ValueError('account index quota')
                self.db.execute('INSERT INTO library_index_pages VALUES(?,?,?,?,?,?)',(owner,job,row['chapter'],row['offset'],encrypted,len(value)))
                self.db.executemany('INSERT OR IGNORE INTO library_index_terms VALUES(?,?,?)',[(owner,job,token) for token in tokens])
                if self.db.execute('SELECT count(*) FROM library_index_terms WHERE owner=? AND job=?',(owner,job)).fetchone()[0]>MAX_TERMS or self.db.execute('SELECT count(*) FROM library_index_terms WHERE owner=?',(owner,)).fetchone()[0]>ACCOUNT_TERMS:raise ValueError('index vocabulary quota')
                complete=chapter==row['chapters']
                self.db.execute("UPDATE library_index_jobs SET state=?,chapter=?,offset=?,characters=characters+?,revision=revision+1,lease='',lease_until=0,updated=? WHERE owner=? AND id=?",('complete' if complete else 'indexing',chapter,offset,len(value),int(time.time()),owner,job))
                if complete:
                    self.db.execute('INSERT OR REPLACE INTO library_index_documents VALUES(?,?,?,?,?,?)',(owner,row['book'],job,row['file_id'],row['digest'],row['characters']+len(value)))
                    self.db.execute('DELETE FROM library_index_tails WHERE owner=? AND job=?',(owner,job))
                else:
                    tail_nonce=secrets.token_bytes(12);body=tail_nonce+AESGCM(page_key).encrypt(tail_nonce,encoded(next_carry),encoded(['tail',owner,job,revision+1]))
                    self.db.execute('INSERT OR REPLACE INTO library_index_tails VALUES(?,?,?)',(owner,job,body))
            return self.status(owner,job)
        except (ValueError,PermissionError,KeyError,TypeError,InvalidTag) as error:
            with self.fabric.transaction():self.db.execute("UPDATE library_index_jobs SET state='failed',error='source_or_parser_or_quota_rejected',lease='',lease_until=0,updated=? WHERE owner=? AND id=? AND lease=?",(int(time.time()),owner,job,lease))
            if isinstance(error,InvalidTag):raise ValueError('document index integrity rejected') from None
            raise

    def cancel(self,owner,job):
        with self.fabric.transaction():
            self.row(owner,job)
            self.db.execute('DELETE FROM library_index_documents WHERE owner=? AND job=?',(owner,job))
            self.db.execute('DELETE FROM library_index_pages WHERE owner=? AND job=?',(owner,job))
            self.db.execute('DELETE FROM library_index_terms WHERE owner=? AND job=?',(owner,job))
            self.db.execute('DELETE FROM library_index_tails WHERE owner=? AND job=?',(owner,job))
            self.db.execute("UPDATE library_index_jobs SET state='cancelled',lease='',lease_until=0,revision=revision+1,updated=? WHERE owner=? AND id=? AND state!='cancelled'",(int(time.time()),owner,job))
        return self.status(owner,job)

    def predicate(self,owner,query):
        # Never derive/create a vault for anonymous or unindexed readers.
        if owner.startswith('@') or not self.db.execute('SELECT 1 FROM library_index_documents WHERE owner=? LIMIT 1',(owner,)).fetchone():return None,[]
        terms=words(query)
        if not terms:return None,[]
        if len(terms)>16:raise ValueError('index query term budget')
        key=self.key(owner,b'terms');tokens=[hmac.new(key,word.encode(),hashlib.sha256).digest() for word in terms]
        sql="r.id IN (SELECT d.book FROM library_index_documents d JOIN library_index_terms t ON t.owner=d.owner AND t.job=d.job WHERE d.owner=? AND d.file_id=json_extract(r.body,'$.file_id') AND d.digest=json_extract(r.body,'$.file.digest') AND NOT EXISTS(SELECT 1 FROM local_content_policies p WHERE p.record=r.id AND p.distribution_stopped=1) AND EXISTS(SELECT 1 FROM objects o WHERE o.id=coalesce((SELECT local FROM locations WHERE remote=d.file_id),d.file_id) AND (o.owner=? OR EXISTS(SELECT 1 FROM content_references c JOIN records a ON a.id=c.record WHERE ((a.origin=? AND a.owner=o.owner AND c.object=o.id) OR (EXISTS(SELECT 1 FROM locations WHERE remote=d.file_id) AND c.object=d.file_id)) AND a.deleted=0 AND a.visibility='public' AND (a.expires=0 OR a.expires>?) AND NOT EXISTS(SELECT 1 FROM local_content_policies q WHERE q.record=a.id AND q.distribution_stopped=1)))) AND t.term IN ("+','.join('?' for _ in tokens)+") GROUP BY d.book HAVING count(DISTINCT t.term)=?)"
        return sql,[owner,owner,self.fabric.public,int(time.time()),*tokens,len(tokens)]

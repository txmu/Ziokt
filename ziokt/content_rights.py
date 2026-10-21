"""Local copyright records and scoped governance; no global deletion authority."""
import json
import re
import secrets
import time
from urllib.parse import urlsplit
from .protocol import encoded


def metadata(value):
    from .content_fabric import text
    required={'schema','attribution','source','license','public_domain','authorization_proofs'}
    if not isinstance(value,dict) or not required<=set(value) or set(value)-required-{'dispute_status'} or value['schema']!='ziokt.content-rights.v1':raise ValueError('rights schema')
    if value.get('dispute_status','none') not in {'none','disputed','resolved'}:raise ValueError('dispute status')
    if type(value['public_domain']) is not bool:raise ValueError('public domain claim')
    entries=value['attribution']
    if not isinstance(entries,list) or len(entries)>64:raise ValueError('attribution budget')
    for entry in entries:
        if not isinstance(entry,dict) or set(entry)!={'name','role'} or entry['role'] not in {'author','publisher','translator','editor','source'}:raise ValueError('attribution role')
        text(entry['name'],512)
    text(value['source'],2048,empty=True)
    license=value['license']
    if not isinstance(license,dict) or set(license)!={'type','value','url'} or license['type'] not in {'spdx','creative-commons','custom','public-domain','unknown'}:raise ValueError('license type')
    text(license['value'],2048,empty=True);text(license['url'],2048,empty=True)
    if license['url']:
        url=urlsplit(license['url'])
        if url.scheme!='https' or not url.hostname or url.username or url.password:raise ValueError('license URL')
    if license['type']=='spdx' and not re.fullmatch(r'[A-Za-z0-9.()+ :\-]{1,2048}',license['value']):raise ValueError('SPDX metadata syntax')
    if license['type']=='creative-commons' and not re.fullmatch(r'CC(?:0|-(?:BY|BY-SA|BY-ND|BY-NC|BY-NC-SA|BY-NC-ND))-\d\.\d',license['value']):raise ValueError('Creative Commons identifier')
    proofs=value['authorization_proofs']
    if not isinstance(proofs,list) or len(proofs)>16 or any(not isinstance(v,str) or not re.fullmatch(r'sha256:[0-9a-f]{64}',v) for v in proofs):raise ValueError('authorization proof commitments')
    return json.loads(encoded(value))


def initialize(fabric):
    with fabric.transaction():
        fabric.db.execute('CREATE TABLE IF NOT EXISTS rights_cases(id TEXT PRIMARY KEY,record TEXT NOT NULL,reporter TEXT NOT NULL,state TEXT NOT NULL,complaint BLOB NOT NULL,decision TEXT,created INTEGER NOT NULL)')
        fabric.db.execute('CREATE TABLE IF NOT EXISTS rights_events(sequence INTEGER PRIMARY KEY,case_id TEXT NOT NULL,actor TEXT NOT NULL,kind TEXT NOT NULL,body BLOB NOT NULL,created INTEGER NOT NULL,FOREIGN KEY(case_id) REFERENCES rights_cases(id))')
        fabric.db.execute('CREATE TABLE IF NOT EXISTS local_content_policies(record TEXT PRIMARY KEY,deindexed INTEGER NOT NULL DEFAULT 0,distribution_stopped INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL,actor TEXT NOT NULL,updated INTEGER NOT NULL)')
        fabric.db.execute('INSERT OR IGNORE INTO migrations VALUES(6,unixepoch())')


class Governance:
    def __init__(self,fabric):self.fabric=fabric

    def report(self,owner,record,complaint):
        from .content_fabric import text,ident
        ident(owner)
        if not isinstance(complaint,dict) or set(complaint)!={'claim','evidence','contact'}:raise ValueError('complaint fields')
        for key in complaint:text(complaint[key],8192,empty=(key=='contact'))
        if len(encoded(complaint))>16384:raise ValueError('complaint budget')
        f=self.fabric
        with f.transaction():
            f._get(owner,record);f._rate(owner,'rights.report',10)
            if f.db.execute('SELECT count(*) FROM rights_cases').fetchone()[0]>=10000:raise ValueError('complaint retention limit')
            case=secrets.token_hex(16)
            f.db.execute('INSERT INTO rights_cases VALUES(?,?,?,\'submitted\',?,NULL,?)',(case,record,owner,encoded(complaint),int(time.time())))
            f.db.execute('INSERT INTO rights_events(case_id,actor,kind,body,created) VALUES(?,?,?,?,?)',(case,owner,'report',encoded(complaint),int(time.time())))
            f._audit(owner,'rights.report',case)
        return {'id':case,'state':'submitted','legal_claim_verified':False,'distribution_stopped':False}

    def case(self,owner,case,*,operator=False):
        f=self.fabric
        with f.lock:
            row=f.db.execute('SELECT c.*,r.owner AS content_owner FROM rights_cases c LEFT JOIN records r ON r.id=c.record WHERE c.id=?',(case,)).fetchone()
            if not row or not operator and owner not in (row['reporter'],row['content_owner']):raise PermissionError('case unavailable')
            events=[{**dict(entry),'body':json.loads(entry['body'])} for entry in f.db.execute('SELECT * FROM rights_events WHERE case_id=? ORDER BY sequence LIMIT 256',(case,))]
            return {**{k:row[k] for k in ('id','record','reporter','state','decision','created')},'complaint':json.loads(row['complaint']),'events':events,'authority':'this-local-service-only','remote_erasure_guaranteed':False}

    def appeal(self,owner,case,reason):
        from .content_fabric import text
        text(reason,8192)
        f=self.fabric
        with f.transaction():
            self.case(owner,case)
            if f.db.execute('SELECT count(*) FROM rights_events WHERE case_id=?',(case,)).fetchone()[0]>=256:raise ValueError('case history limit')
            f._rate(owner,'rights.appeal',10)
            f.db.execute("UPDATE rights_cases SET state='appealed' WHERE id=?",(case,))
            f.db.execute('INSERT INTO rights_events(case_id,actor,kind,body,created) VALUES(?,?,?,?,?)',(case,owner,'appeal',encoded({'reason':reason}),int(time.time())))
            f._audit(owner,'rights.appeal',case)
        return self.case(owner,case)

    def decide(self,operator,case,decision,reason,*,allow=False):
        from .content_fabric import text
        if allow is not True:raise PermissionError('local operator authorization required')
        if decision not in {'uphold','dismiss'}:raise ValueError('case decision')
        text(reason,8192);f=self.fabric
        with f.transaction():
            self.case(operator,case,operator=True)
            if f.db.execute('SELECT count(*) FROM rights_events WHERE case_id=?',(case,)).fetchone()[0]>=256:raise ValueError('case history limit')
            f.db.execute("UPDATE rights_cases SET state='resolved',decision=? WHERE id=?",(decision,case))
            f.db.execute('INSERT INTO rights_events(case_id,actor,kind,body,created) VALUES(?,?,?,?,?)',(case,operator,'decision',encoded({'decision':decision,'reason':reason}),int(time.time())))
            f._audit(operator,'rights.decision',case)
        return self.case(operator,case,operator=True)

    def policy(self,operator,record,action,reason,*,allow=False):
        from .content_fabric import text
        if allow is not True:raise PermissionError('local operator authorization required')
        if action not in {'deindex','reindex','stop_distribution','resume_distribution'}:raise ValueError('local policy action')
        text(reason,8192);f=self.fabric
        with f.transaction():
            record_row=f.db.execute('SELECT deleted FROM records WHERE id=?',(record,)).fetchone()
            if not record_row:raise ValueError('unknown local record')
            old=f.db.execute('SELECT * FROM local_content_policies WHERE record=?',(record,)).fetchone()
            flags={'deindexed':old['deindexed'] if old else 0,'distribution_stopped':old['distribution_stopped'] if old else 0}
            flags['deindexed' if action in {'deindex','reindex'} else 'distribution_stopped']=int(action in {'deindex','stop_distribution'})
            f.db.execute('INSERT INTO local_content_policies VALUES(?,?,?,?,?,?) ON CONFLICT(record) DO UPDATE SET deindexed=excluded.deindexed,distribution_stopped=excluded.distribution_stopped,reason=excluded.reason,actor=excluded.actor,updated=excluded.updated',(record,flags['deindexed'],flags['distribution_stopped'],reason,operator,int(time.time())))
            f._audit(operator,'local-policy.'+action,record)
            return {'record':record,**{k:bool(v) for k,v in flags.items()},'withdrawn':bool(record_row['deleted']),'physical_bytes_deleted':False,'remote_erasure_guaranteed':False,'authority':'this-local-service-only'}

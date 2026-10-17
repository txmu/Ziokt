"""Owner-approved chain and PoUW registrations; immutable requests, audited transitions."""
import hashlib
import re
import secrets
import time
from .gateway_store import database, encoded

class Registry:
    def __init__(self, path, network):
        from pathlib import Path
        path=Path(path);path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
        self.path,self.network=path,network
        with database(path) as db:
            db.executescript("CREATE TABLE IF NOT EXISTS registrations(id TEXT PRIMARY KEY,applicant TEXT,kind TEXT,target TEXT,payload BLOB,digest TEXT,status TEXT,created INT,updated INT,receipt TEXT); CREATE TABLE IF NOT EXISTS registration_audit(id INTEGER PRIMARY KEY,registration TEXT,actor TEXT,action TEXT,at INT); CREATE UNIQUE INDEX IF NOT EXISTS active_registration ON registrations(kind,target) WHERE status IN ('approved','submitting');")

        path.chmod(0o600)

    def validate(self, entry):
        common={'kind','target','description','weight'}
        if not isinstance(entry,dict) or entry.get('kind') not in {'external_chain','pouw_engine'}:raise ValueError('unknown registration kind')
        fields=common|({'genesis_hash','verifier_hash'} if entry['kind']=='external_chain' else {'pkg_id','compute_program_hash','verifier_script_hash'})
        if set(entry)!=fields:raise ValueError('exact registration fields required')
        if not isinstance(entry['target'],str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,63}',entry['target']):raise ValueError('invalid target')
        if type(entry['weight']) is not int or not 1<=entry['weight']<=1000000:raise ValueError('weight out of bounds')
        if not isinstance(entry['description'],str) or not 1<=len(entry['description'].encode())<=2048 or '\0' in entry['description']:raise ValueError('invalid description')
        for field in fields-common-{'pkg_id'}:
            if not isinstance(entry[field],str) or not re.fullmatch('[a-f0-9]{64}',entry[field]):raise ValueError('invalid hash')
        if 'pkg_id' in entry and (not isinstance(entry['pkg_id'],str) or not re.fullmatch('[a-z0-9-]+/[a-z0-9-]+:[0-9]{1,9}',entry['pkg_id']) or len(entry['pkg_id'])>160):raise ValueError('invalid package')

    def submit(self, applicant, entry):
        self.validate(entry)
        raw=encoded({'network':self.network,'entry':entry});digest=hashlib.sha256(raw).hexdigest()
        now=int(time.time());rid=secrets.token_hex(16)
        with database(self.path) as db:
            if db.execute("SELECT count(*) FROM registrations WHERE applicant=? AND status='pending'",(applicant,)).fetchone()[0]>=20:raise ValueError('pending application limit')
            db.execute('INSERT INTO registrations VALUES (?,?,?,?,?,?,?,?,?,?)',(rid,applicant,entry['kind'],entry['target'],encoded(entry),digest,'pending',now,now,''))
            db.execute('INSERT INTO registration_audit(registration,actor,action,at) VALUES (?,?,?,?)',(rid,applicant,'submit',now))
        return {'id':rid,'digest':digest,'status':'pending','effective':False}

    def list(self, status='approved', applicant=None):
        import json
        if status not in {'approved','pending','rejected','revoked','submitting','all'}:raise ValueError('invalid status')
        clauses=[];params=[]
        if status!='all':clauses.append('status=?');params.append(status)
        if applicant is not None:clauses.append('applicant=?');params.append(applicant)
        with database(self.path) as db:
            rows=db.execute('SELECT id,applicant,payload,digest,status,created,updated,receipt FROM registrations'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY created DESC,id LIMIT 100',params).fetchall()
        return {'network':self.network,'registrations':[dict(id=r[0],applicant=r[1],entry=json.loads(r[2]),digest=r[3],status=r[4],created=r[5],updated=r[6],native_transaction=r[7] or None,effective=r[4]=='approved',activation='native-governance-required' if json.loads(r[2])['kind']=='pouw_engine' else 'gateway-whitelist') for r in rows]}

    def decide(self, actor, rid, digest, decision, native):
        import json
        if decision not in {'approve','reject','revoke'}:raise ValueError('invalid decision')
        with database(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload,digest,status FROM registrations WHERE id=?',(rid,)).fetchone()
            if not row or row[1]!=digest:raise ValueError('application changed or missing')
            if row[2] != ('approved' if decision=='revoke' else 'pending'):raise ValueError('invalid state transition')
            entry=json.loads(row[0]);status={'approve':'approved','reject':'rejected','revoke':'revoked'}[decision]
            if decision=='approve':
                if db.execute("SELECT 1 FROM registrations WHERE kind=? AND target=? AND status IN ('approved','submitting')",(entry['kind'],entry['target'])).fetchone():raise ValueError('target already approved')
                if entry['kind']=='pouw_engine':status='submitting'
            now=int(time.time())
            db.execute('UPDATE registrations SET status=?,updated=? WHERE id=?',(status,now,rid))
            db.execute('INSERT INTO registration_audit(registration,actor,action,at) VALUES (?,?,?,?)',(rid,actor,decision,now))
        receipt=''
        if status=='submitting':
            # Durable uncertain state is never automatically replayed after a crash.
            payload={'description':entry['description'],'pkg_id':entry['pkg_id'],'compute_program_hash':entry['compute_program_hash'],'verifier_script_hash':entry['verifier_script_hash'],'reward_weight':entry['weight']}
            receipt=native('engine-propose',encoded(payload).decode()).strip()
            if not re.fullmatch('[a-f0-9]{64}',receipt):raise ValueError('native proposal receipt unavailable; reconcile submitting state')
            status='approved'
            with database(self.path) as db:db.execute('UPDATE registrations SET status=?,receipt=?,updated=? WHERE id=?',(status,receipt,int(time.time()),rid))
        return {'id':rid,'status':status,'native_transaction':receipt or None,'effective':status=='approved','activation':'native-governance-required' if entry['kind']=='pouw_engine' else 'gateway-whitelist'}

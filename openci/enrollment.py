"""Operator-approved, expiring, one-use enrollment with retry-safe scoped credentials."""
from contextlib import closing
import hashlib
import hmac
import json
import os
import re
import secrets
from .state import Error,identifier,integer,encoded
from ziokt.protocol import secure_read,ProtocolError
from ziokt.security import verify
DOMAIN='OpenCI/worker-enrollment/v1'


def setup(store):
    with store.transaction() as db:
        db.execute('CREATE TABLE IF NOT EXISTS enrollment_invites(digest TEXT PRIMARY KEY,caps TEXT NOT NULL,expires INTEGER NOT NULL,request_digest TEXT,worker TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS enrolled_credentials(worker TEXT PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,invite_digest TEXT NOT NULL,FOREIGN KEY(worker) REFERENCES workers(id))')
    path=store.root/'enrollment.key'
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    except FileExistsError:pass
    else:
        with os.fdopen(fd,'wb') as output:output.write(secrets.token_bytes(32));output.flush();os.fsync(output.fileno())
    secret=secure_read(path,32)
    if len(secret)!=32:raise Error('ENROLLMENT_KEY','Exact protected enrollment key required',503)
    return secret


def invite(store,actor,value):
    fields={'arch','pool','cpu','memory_mb','slots','projects','ttl'}
    if type(value) is not dict or set(value)!=fields:raise Error('INVITE_FIELDS','Exact approved worker limits required')
    if value['arch'] not in {'x86_64','aarch64'} or value['pool'] not in {'community','trusted'}:raise Error('INVITE_CAPS','Explicit supported architecture and pool required')
    for name,low,high in [('cpu',1,64),('memory_mb',64,262144),('slots',1,16),('ttl',60,86400)]:integer(value[name],low,high)
    projects=value['projects']
    if type(projects) is not list or not 1<=len(projects)<=128:raise Error('INVITE_PROJECTS','Approved projects required')
    for project in projects:identifier(project)
    caps={k:v for k,v in value.items() if k!='ttl'};caps['projects']=sorted(set(projects))
    token=secrets.token_urlsafe(32);digest=hashlib.sha256(token.encode()).hexdigest();expires=int(store.clock())+value['ttl']
    with store.transaction() as db:
        db.execute('DELETE FROM enrollment_invites WHERE expires<? AND request_digest IS NULL',(int(store.clock()),))
        if db.execute('SELECT count(*) FROM enrollment_invites WHERE request_digest IS NULL').fetchone()[0]>=256:raise Error('INVITE_LIMIT','Outstanding invitation budget exhausted',429)
        db.execute('INSERT INTO enrollment_invites(digest,caps,expires) VALUES(?,?,?)',(digest,encoded(caps),expires))
        store.event(db,actor,'enrollment.invited',detail={'invite_sha256':digest,'caps':caps,'expires':expires})
    return {'schema':'openci.worker-invite.v1','invite':token,'expires':expires,'caps':caps,'one_use':True,'hardware_attested':False}


def redeem(store,secret,value):
    if type(value) is not dict or set(value)!={'invite','proof'} or type(value['invite']) is not str or not re.fullmatch('[A-Za-z0-9_-]{43}',value['invite']):raise Error('ENROLLMENT_FIELDS','Bounded invitation and signed enrollment required')
    digest=hashlib.sha256(value['invite'].encode()).hexdigest();proof=value['proof']
    try:
        body=verify(proof,proof['public_key'],DOMAIN,maximum=2048)
        if type(body) is not dict or set(body)!={'invite_sha256','worker','nonce'} or body['invite_sha256']!=digest or not re.fullmatch('[a-f0-9]{32}',body['nonce']):raise ValueError()
        identifier(body['worker'])
    except (ProtocolError,KeyError,ValueError,TypeError):raise Error('ENROLLMENT_PROOF','Exact worker signature and invitation binding required',403) from None
    request_digest=hashlib.sha256(encoded({'public_key':proof['public_key'],'payload':body}).encode()).hexdigest()
    credential=hmac.new(secret,('OpenCI/scoped-worker/v1\n'+digest+'\n'+request_digest).encode(),hashlib.sha256).hexdigest()
    token_hash=hashlib.sha256(credential.encode()).hexdigest();worker=body['worker']
    with store.transaction() as db:
        row=db.execute('SELECT * FROM enrollment_invites WHERE digest=?',(digest,)).fetchone()
        if not row or row['expires']<int(store.clock()):raise Error('INVITE_REJECTED','Invitation expired or unavailable',403)
        if row['request_digest']:
            previous=db.execute('SELECT c.token_hash,w.enabled FROM enrolled_credentials c JOIN workers w ON w.id=c.worker WHERE c.worker=? AND c.invite_digest=?',(worker,digest)).fetchone()
            if row['request_digest']!=request_digest or not previous or not previous['enabled'] or not hmac.compare_digest(previous['token_hash'],token_hash):raise Error('INVITE_USED','Invitation already used or worker revoked',409)
        else:
            if db.execute('SELECT 1 FROM workers WHERE id=?',(worker,)).fetchone():raise Error('WORKER_EXISTS','Enrollment cannot replace an existing Worker',409)
            caps=json.loads(row['caps'])
            db.execute('INSERT INTO workers(id,arch,pool,cpu,memory_mb,slots,projects,enabled) VALUES(?,?,?,?,?,?,?,1)',(worker,caps['arch'],caps['pool'],caps['cpu'],caps['memory_mb'],caps['slots'],encoded(caps['projects'])))
            db.execute('INSERT INTO worker_receipt_keys(worker,public,evidence) VALUES(?,?,?)',(worker,proof['public_key'],'sha256:'+request_digest))
            db.execute('INSERT INTO enrolled_credentials VALUES(?,?,?)',(worker,token_hash,digest))
            db.execute('UPDATE enrollment_invites SET request_digest=?,worker=? WHERE digest=?',(request_digest,worker,digest))
            store.event(db,worker,'enrollment.redeemed',detail={'invite_sha256':digest,'public_key':proof['public_key']})
        caps=json.loads(row['caps'])
    return {'schema':'openci.worker-credential.v1','worker':worker,'role':'worker','projects':caps['projects'],'access_token':credential,'receipt_public_key':proof['public_key'],'hardware_attested':False,'build_profile_approval_required':True,'native_reward_authority':False}


def authenticate(store,candidate):
    with closing(store.connect()) as db:
        row=db.execute('SELECT w.id,w.projects FROM enrolled_credentials c JOIN workers w ON w.id=c.worker WHERE c.token_hash=? AND w.enabled=1',(candidate,)).fetchone()
    return (row['id'],{'role':'worker','worker':row['id'],'projects':json.loads(row['projects'])}) if row else None

"""Live build selection, never a consensus activation or a hardware attestation.

Operator evidence binds approved image/failure-domain claims. Authenticated
presence is a short liveness lease and cannot upgrade those claims.
"""
import json
from contextlib import closing
from .state import Error, IMAGE, DIGEST, encoded, identifier, integer


def images(value):
    if not isinstance(value,list) or not 1<=len(value)<=16 or any(not isinstance(v,str) or not IMAGE.fullmatch(v) for v in value) or len(set(value))!=len(value):
        raise Error('BUILD_IMAGES','One to sixteen distinct pinned images required')
    return sorted(value)


def approve(store,actor,worker,domain,approved_images,evidence):
    identifier(worker);identifier(domain);approved_images=images(approved_images)
    if not isinstance(evidence,str) or not DIGEST.fullmatch(evidence):
        raise Error('BUILD_EVIDENCE','Operator verification evidence SHA-256 commitment required')
    with store.transaction() as db:
        if not db.execute('SELECT 1 FROM workers WHERE id=? AND enabled=1',(worker,)).fetchone():
            raise Error('WORKER_NOT_APPROVED','Enable worker before approving build profile',403)
        if db.execute("SELECT 1 FROM tasks WHERE worker=? AND state='running'",(worker,)).fetchone():
            raise Error('WORKER_BUSY','Drain worker before changing build profile',409)
        db.execute('INSERT OR REPLACE INTO worker_build_profiles VALUES(?,?,?,?)',(worker,domain,encoded(approved_images),evidence))
        # Reapproval requires fresh presence; stale credentials cannot count.
        db.execute('DELETE FROM worker_presence WHERE worker=?',(worker,))
        store.event(db,actor,'worker.build_profile',detail={'worker':worker,'domain':domain,'images':approved_images,'evidence':evidence})
    return {'state':'operator_approved','hardware_attested':False}


def presence(store,worker,available_images):
    available_images=images(available_images)
    with store.transaction() as db:
        if not db.execute('SELECT 1 FROM workers WHERE id=? AND enabled=1',(worker,)).fetchone():
            raise Error('WORKER_NOT_APPROVED','Worker disabled or unknown',403)
        now=int(store.clock())
        db.execute('INSERT OR REPLACE INTO worker_presence VALUES(?,?,?)',(worker,now,encoded(available_images)))
    return {'state':'observed','expires':now+60,'resource_claims_verified':False}


def select(store,project,spec,minimum=2):
    identifier(project);integer(minimum,2,8)
    now=int(store.clock());eligible=[]
    with store.transaction() as db:
        rows=db.execute('''SELECT w.*,b.domain,b.images AS approved_images,b.evidence,p.seen,p.images AS available_images
            FROM workers w JOIN worker_build_profiles b ON b.worker=w.id
            JOIN worker_presence p ON p.worker=w.id WHERE w.enabled=1 ORDER BY w.pool DESC,w.id''').fetchall()
        for row in rows:
            if not 0<=now-row['seen']<60 or project not in json.loads(row['projects']):continue
            if row['arch']!=spec['arch'] or row['cpu']<spec['cpu'] or row['memory_mb']<spec['memory_mb']:continue
            if spec['image'] not in json.loads(row['approved_images']) or spec['image'] not in json.loads(row['available_images']):continue
            if any(v['domain']==row['domain'] for v in eligible):continue
            eligible.append({'worker':row['id'],'domain':row['domain'],'pool':row['pool'],'evidence':row['evidence'],'expires':row['seen']+60})
    enabled=len(eligible)>=minimum and any(v['pool']=='trusted' for v in eligible)
    return {'schema':'openci.live-build-selection.v1','multi_build_enabled':enabled,
            'reason':'eligible' if enabled else 'insufficient_independent_workers' if len(eligible)<minimum else 'trusted_verifier_unavailable',
            'workers':eligible[:minimum] if enabled else eligible,'minimum':minimum,'observed_at':now,
            'expires':min([now+60]+[v['expires'] for v in eligible]),
            'consensus_activation':False,'compiler_backdoor_exclusion_verified':False}


def enqueue(store,actor,pid,task,nonce,minimum=2):
    """Recheck membership for each request; retries preserve the exact plan."""
    identifier(nonce);integer(minimum,2,8)
    original=store.inspect(pid);spec=store.task_spec(pid,task)
    if not spec['outputs']:raise Error('VERIFICATION_OUTPUTS','Replica comparison requires declared outputs',409)
    with closing(store.connect()) as db:
        row=db.execute('SELECT body FROM pipelines WHERE id=?',(pid,)).fetchone()
        source=json.loads(row['body'])['source']
        previous=db.execute('SELECT id FROM pipelines WHERE project=? AND nonce=?',(original['project'],nonce)).fetchone()
    # Stable request identity must not become a different plan after membership changes.
    if previous:
        existing=store.inspect(previous['id'])
        with closing(store.connect()) as db:
            body=json.loads(db.execute('SELECT body FROM pipelines WHERE id=?',(previous['id'],)).fetchone()[0])
        tasks=body['tasks']
        expected={k:v for k,v in spec.items() if k not in {'worker','pool','needs','id'}}
        if body['source']!=source or len(tasks)!=minimum or any({k:v for k,v in t.items() if k not in {'worker','pool','needs','id'}}!=expected or t['id']!='replica'+str(i) or 'worker' not in t for i,t in enumerate(tasks)):
            raise Error('IDEMPOTENCY_CONFLICT','Nonce belongs to another build plan',409)
        return {'state':'already_submitted','pipeline':existing['pipeline'],'duplicate':True,'verification':'pending'}
    decision=select(store,original['project'],spec,minimum)
    if not decision['multi_build_enabled']:return {'state':'disabled','selection':decision,'verification':'not_requested'}
    tasks=[]
    for i,worker in enumerate(decision['workers']):
        tasks.append({**spec,'id':'replica'+str(i),'needs':[],'worker':worker['worker'],'pool':worker['pool']})
    request={'schema':'openci.pipeline.v1','project':original['project'],'nonce':nonce,'source':source,'tasks':tasks}
    result=store.submit(actor,request)
    return {'state':'submitted','selection':decision,**result,'verification':'pending'}

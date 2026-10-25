"""Durable DAG scheduling. Build completion, verification and release are distinct.

All lease changes use BEGIN IMMEDIATE so multiple Controller processes cannot
assign the same task. Worker resources are operator-approved caps, never claims
accepted from an unauthenticated remote registration.
"""
from contextlib import closing, contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import sqlite3
import time
from ziokt._verified_guards import within_budget,before_deadline

ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
DIGEST = re.compile(r'sha256:[a-f0-9]{64}\Z')
IMAGE = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9./:_-]{0,190}@sha256:[a-f0-9]{64}\Z')


class Error(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise Error('INVALID_ID', 'Bounded identifier required')
    return value


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def reference(value):
    if not isinstance(value, dict) or set(value) != {'object', 'digest'} or not isinstance(value['object'], str) or not re.fullmatch(r'cf1-[a-f0-9]{64}', value['object']) or not isinstance(value['digest'], str) or not DIGEST.fullmatch(value['digest']):
        raise Error('INVALID_REFERENCE', 'Native Content Fabric object and plaintext SHA-256 required')
    return value


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise Error('INVALID_LIMIT', 'Resource limit outside allowed range')
    return value


def canonical_cache_key(base_key, source_digest=None, image=None, arch=None, argv=None, cache_paths=None, lockfile_digest=None):
    """Deterministically bind cache key to source revision, toolchain, architecture, build command and paths."""
    context = [
        str(base_key or ''),
        str(source_digest or ''),
        str(image or ''),
        str(arch or ''),
        json.dumps(argv or [], sort_keys=True),
        json.dumps(cache_paths or [], sort_keys=True),
        str(lockfile_digest or '')
    ]
    fingerprint = hashlib.sha256('\x00'.join(context).encode('utf-8')).hexdigest()[:32]
    return f"{base_key}--{fingerprint}"


def validate_pipeline(value):
    if not isinstance(value, dict) or set(value) != {'schema', 'project', 'nonce', 'source', 'tasks'} or value['schema'] != 'openci.pipeline.v1':
        raise Error('INVALID_PIPELINE', 'Versioned pipeline with exact fields required')
    identifier(value['project']); identifier(value['nonce']); reference(value['source'])
    if not isinstance(value['tasks'], list) or not 1 <= len(value['tasks']) <= 128:
        raise Error('INVALID_DAG', 'Between one and 128 tasks required')
    tasks = {}
    for task in value['tasks']:
        required={'id', 'needs', 'image', 'argv', 'arch', 'pool', 'cpu', 'memory_mb', 'timeout', 'attempts'}
        if not isinstance(task, dict) or not required<=set(task) or set(task)-required-{'outputs','worker','executor','cache_key','cache_paths','cache_mode'}:
            raise Error('INVALID_TASK', 'Exact task fields required')
        task=dict(task);task.setdefault('outputs',[])
        if 'worker' in task:identifier(task['worker'])
        if 'cache_key' in task:
            if not isinstance(task['cache_key'],str) or not 1<=len(task['cache_key'])<=128 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',task['cache_key']):
                raise Error('INVALID_CACHE_KEY','Bounded alphanumeric cache key required')
        if 'cache_paths' in task:
            paths=task['cache_paths']
            if not isinstance(paths,list) or len(paths)>16 or any(not isinstance(p,str) or not p or len(p)>256 or p.startswith('/') or '..' in p.split('/') or '\\' in p or '\x00' in p or p=='.' or str(PurePosixPath(p))!=p for p in paths):
                raise Error('INVALID_CACHE_PATHS','Bounded relative cache paths required')
            if len(set(paths))!=len(paths):raise Error('INVALID_CACHE_PATHS','Duplicate cache paths')
        if 'cache_mode' in task and (not isinstance(task['cache_mode'],str) or task['cache_mode'] not in {'read-write','read-only','write-only'}):
            raise Error('INVALID_CACHE_MODE','cache_mode must be read-write, read-only, or write-only')
        outputs=task['outputs']
        if not isinstance(outputs,list) or len(outputs)>128 or any(not isinstance(p,str) or not p or len(p)>1024 or p.startswith('/') or '..' in p.split('/') or '\\' in p or p.endswith('/') or str(PurePosixPath(p))!=p or p=='.' for p in outputs):
            raise Error('INVALID_OUTPUTS','Bounded relative output file paths required')
        if len(set(outputs))!=len(outputs):raise Error('INVALID_OUTPUTS','Duplicate output paths')
        name = identifier(task['id'])
        if name in tasks:
            raise Error('INVALID_DAG', 'Duplicate task')
        if not isinstance(task['needs'], list) or len(task['needs']) > 128:
            raise Error('INVALID_DAG', 'Unique dependency list required')
        for dependency in task['needs']: identifier(dependency)
        if len(set(task['needs'])) != len(task['needs']): raise Error('INVALID_DAG', 'Duplicate dependency')
        if not isinstance(task['image'], str) or not IMAGE.fullmatch(task['image']):
            raise Error('UNPINNED_IMAGE', 'Container image must have an immutable sha256 digest')
        argv = task['argv']
        if not isinstance(argv, list) or not 1 <= len(argv) <= 128 or any(not isinstance(a, str) or '\x00' in a or len(a.encode()) > 4096 for a in argv) or not argv[0]:
            raise Error('INVALID_ARGV', 'Bounded argument vector required')
        if task['arch'] not in {'x86_64', 'aarch64'} or task['pool'] not in {'trusted', 'community'}:
            raise Error('INVALID_WORKER_REQUIREMENT', 'Explicit supported architecture and trust pool required')
        integer(task['cpu'], 1, 64); integer(task['memory_mb'], 64, 262144)
        integer(task['timeout'], 1, 10800); integer(task['attempts'], 1, 5)
        if task.get('executor','oci') not in {'oci','light-c'}:raise Error('TASK_EXECUTOR','Known isolated executor required')
        if task.get('executor')=='light-c':
            from .light import validate_task
            validate_task(task)
        tasks[name] = task
    ordered, order = set(), []
    while len(ordered) < len(tasks):
        ready = [name for name, task in tasks.items() if name not in ordered and set(task['needs']) <= ordered]
        if not ready:
            raise Error('INVALID_DAG', 'Cycle or unknown dependency')
        ordered.update(ready);order.extend(ready)
    value=json.loads(encoded(value))
    value['tasks']=[tasks[name] for name in order]
    return json.loads(encoded(value))


class Store:
    def __init__(self, root, clock=time.time):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink(): raise Error('UNSAFE_STATE', 'State root cannot be a symlink')
        self.path = self.root/'controller.sqlite'
        if self.path.is_symlink(): raise Error('UNSAFE_STATE', 'Database symlink rejected')
        self.clock = clock
        with closing(self.connect()) as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1): raise Error('SCHEMA_VERSION', 'Controller database requires another code version')
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS pipelines(id TEXT PRIMARY KEY,project TEXT NOT NULL,nonce TEXT NOT NULL,body TEXT NOT NULL,state TEXT NOT NULL,created INTEGER NOT NULL,UNIQUE(project,nonce));
                CREATE TABLE IF NOT EXISTS tasks(pipeline TEXT NOT NULL,id TEXT NOT NULL,spec TEXT NOT NULL,state TEXT NOT NULL,attempt INTEGER NOT NULL DEFAULT 0,worker TEXT,lease_hash TEXT,lease_until INTEGER,receipt TEXT,verification TEXT,PRIMARY KEY(pipeline,id),FOREIGN KEY(pipeline) REFERENCES pipelines(id));
                CREATE TABLE IF NOT EXISTS workers(id TEXT PRIMARY KEY,arch TEXT NOT NULL,pool TEXT NOT NULL,cpu INTEGER NOT NULL,memory_mb INTEGER NOT NULL,slots INTEGER NOT NULL,projects TEXT NOT NULL,enabled INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS worker_build_profiles(worker TEXT PRIMARY KEY,domain TEXT NOT NULL,images TEXT NOT NULL,evidence TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS worker_receipt_keys(worker TEXT PRIMARY KEY,public TEXT NOT NULL,evidence TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipt_attestations(pipeline TEXT NOT NULL,task TEXT NOT NULL,attempt INTEGER NOT NULL,envelope TEXT NOT NULL,PRIMARY KEY(pipeline,task,attempt));
                CREATE TABLE IF NOT EXISTS worker_presence(worker TEXT PRIMARY KEY,seen INTEGER NOT NULL,images TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts(pipeline TEXT,id TEXT,attempt INTEGER,worker TEXT,state TEXT,started INTEGER,finished INTEGER,receipt TEXT,PRIMARY KEY(pipeline,id,attempt),FOREIGN KEY(pipeline,id) REFERENCES tasks(pipeline,id));
                CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,created INTEGER NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,pipeline TEXT,task TEXT,detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS log_chunks(pipeline TEXT,task TEXT,attempt INTEGER,position INTEGER,body BLOB NOT NULL,PRIMARY KEY(pipeline,task,attempt,position),FOREIGN KEY(pipeline,task) REFERENCES tasks(pipeline,id));
                CREATE TABLE IF NOT EXISTS git_schedules(project TEXT PRIMARY KEY,next_due INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS git_deliveries(project TEXT NOT NULL,delivery TEXT NOT NULL,commit_id TEXT NOT NULL,state TEXT NOT NULL,pipeline TEXT,error TEXT,updated INTEGER NOT NULL,PRIMARY KEY(project,delivery));
                CREATE TABLE IF NOT EXISTS releases(id TEXT PRIMARY KEY,pipeline TEXT NOT NULL,task TEXT NOT NULL,project TEXT NOT NULL,name TEXT NOT NULL,version TEXT NOT NULL,publisher TEXT NOT NULL,state TEXT NOT NULL,request TEXT NOT NULL,publication TEXT,created INTEGER NOT NULL,UNIQUE(name,version,publisher),FOREIGN KEY(pipeline) REFERENCES pipelines(id));
                CREATE TABLE IF NOT EXISTS build_caches(project TEXT NOT NULL,cache_key TEXT NOT NULL,artifact TEXT NOT NULL,created INTEGER NOT NULL,last_accessed INTEGER NOT NULL,size INTEGER NOT NULL,hit_count INTEGER NOT NULL DEFAULT 0,base_key TEXT NOT NULL DEFAULT '',source_digest TEXT NOT NULL DEFAULT '',image TEXT NOT NULL DEFAULT '',arch TEXT NOT NULL DEFAULT '',PRIMARY KEY(project,cache_key));
                CREATE TABLE IF NOT EXISTS pending_package_publications(release_id TEXT PRIMARY KEY,project TEXT NOT NULL,package_name TEXT NOT NULL,version TEXT NOT NULL,payload TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,last_attempt INTEGER NOT NULL DEFAULT 0,last_error TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'pending',created INTEGER NOT NULL);
                PRAGMA user_version=1;
            ''')
            for col, col_def in [('base_key', "TEXT NOT NULL DEFAULT ''"), ('source_digest', "TEXT NOT NULL DEFAULT ''"), ('image', "TEXT NOT NULL DEFAULT ''"), ('arch', "TEXT NOT NULL DEFAULT ''")]:
                try: db.execute(f"ALTER TABLE build_caches ADD COLUMN {col} {col_def}")
                except Exception: pass
        os.chmod(self.path, 0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA busy_timeout=15000')
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self, db, actor, action, pipeline=None, task=None, detail=None):
        db.execute('INSERT INTO events(created,actor,action,pipeline,task,detail) VALUES(?,?,?,?,?,?)',
                   (int(self.clock()), actor, action, pipeline, task, encoded(detail or {})))

    def approve_worker(self, actor, worker, *, arch, pool, cpu, memory_mb, slots, projects):
        identifier(worker)
        if arch not in {'x86_64', 'aarch64'} or pool not in {'trusted', 'community'}:
            raise Error('INVALID_WORKER', 'Explicit architecture and trust pool required')
        integer(cpu, 1, 64); integer(memory_mb, 64, 262144); integer(slots, 1, 16)
        if not isinstance(projects, list) or not projects or len(projects) > 128: raise Error('INVALID_PROJECTS', 'Explicit worker projects required')
        for project in projects: identifier(project)
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM tasks WHERE worker=? AND state='running'", (worker,)).fetchone():
                raise Error('WORKER_BUSY', 'Drain worker before changing approved caps', 409)
            db.execute('INSERT OR REPLACE INTO workers VALUES(?,?,?,?,?,?,?,1)', (worker, arch, pool, cpu, memory_mb, slots, encoded(sorted(set(projects)))))
            db.execute('DELETE FROM worker_build_profiles WHERE worker=?',(worker,))
            db.execute('DELETE FROM worker_presence WHERE worker=?',(worker,))
            self.event(db, actor, 'worker.approved', detail={'worker': worker, 'pool': pool})

    def approve_receipt_key(self,actor,worker,public,evidence):
        identifier(worker)
        if not isinstance(public,str) or not re.fullmatch('[a-f0-9]{64}',public) or not isinstance(evidence,str) or not DIGEST.fullmatch(evidence):
            raise Error('WORKER_SIGNING_KEY','Exact Ed25519 public key and operator evidence required')
        with self.transaction() as db:
            if not db.execute('SELECT 1 FROM workers WHERE id=? AND enabled=1',(worker,)).fetchone():raise Error('WORKER_UNKNOWN','Enabled approved Worker required',404)
            if db.execute("SELECT 1 FROM tasks WHERE worker=? AND state='running'",(worker,)).fetchone():raise Error('WORKER_BUSY','Drain Worker before rotating its receipt key',409)
            db.execute('INSERT OR REPLACE INTO worker_receipt_keys VALUES(?,?,?)',(worker,public,evidence))
            self.event(db,actor,'worker.receipt_key',detail={'worker':worker,'public':public,'evidence':evidence})
        return {'worker':worker,'public':public,'receipt_signature_required':True,'hardware_attested':False}

    def disable_worker(self, actor, worker):
        identifier(worker)
        with self.transaction() as db:
            if db.execute('UPDATE workers SET enabled=0 WHERE id=?', (worker,)).rowcount != 1:
                raise Error('WORKER_UNKNOWN', 'Worker not approved', 404)
            # Revoke outstanding leases atomically: reapproval must never revive them.
            db.execute("UPDATE tasks SET lease_until=? WHERE worker=? AND state='running'",(int(self.clock()),worker))
            self.refresh(db)
            self.event(db, actor, 'worker.disabled', detail={'worker': worker})

    def submit(self, actor, pipeline):
        pipeline = validate_pipeline(pipeline)
        body = encoded(pipeline)
        pid = hashlib.sha256(body.encode()).hexdigest()
        with self.transaction() as db:
            previous = db.execute('SELECT id,body FROM pipelines WHERE project=? AND nonce=?', (pipeline['project'], pipeline['nonce'])).fetchone()
            if previous:
                if previous['body'] != body: raise Error('IDEMPOTENCY_CONFLICT', 'Nonce already describes another pipeline', 409)
                return {'pipeline': previous['id'], 'duplicate': True}
            if db.execute('SELECT count(*) FROM pipelines').fetchone()[0] >= 10000 or db.execute("SELECT count(*) FROM pipelines WHERE project=? AND state NOT IN ('completed','cancelled','failed','published')", (pipeline['project'],)).fetchone()[0] >= 32:
                raise Error('PIPELINE_QUOTA', 'Archive old pipelines or wait for active jobs', 429)
            if db.execute("SELECT count(*) FROM tasks WHERE state IN ('queued','waiting','running','blocked')").fetchone()[0]+len(pipeline['tasks']) > 4096:
                raise Error('QUEUE_FULL', 'Controller active task budget exhausted', 429)
            db.execute('INSERT INTO pipelines VALUES(?,?,?,?,?,?)', (pid, pipeline['project'], pipeline['nonce'], body, 'submitted', int(self.clock())))
            for task in pipeline['tasks']:
                db.execute('INSERT INTO tasks(pipeline,id,spec,state) VALUES(?,?,?,?)', (pid, task['id'], encoded(task), 'waiting' if task['needs'] else 'queued'))
            self.event(db, actor, 'pipeline.submitted', pid)
        return {'pipeline': pid, 'duplicate': False}

    def refresh(self, db):
        now = int(self.clock())
        expired = db.execute("SELECT * FROM tasks WHERE state='running' AND lease_until<=?", (now,)).fetchall()
        for task in expired:
            spec = json.loads(task['spec'])
            state = 'queued' if task['attempt'] < spec['attempts'] else 'failed'
            db.execute('UPDATE tasks SET state=?,worker=NULL,lease_hash=NULL,lease_until=NULL WHERE pipeline=? AND id=?', (state, task['pipeline'], task['id']))
            db.execute("UPDATE attempts SET state='lease_expired',finished=? WHERE pipeline=? AND id=? AND attempt=?", (now, task['pipeline'], task['id'], task['attempt']))
            self.event(db, 'scheduler', 'task.lease_expired', task['pipeline'], task['id'], {'attempt': task['attempt']})
        for row in db.execute("SELECT id FROM pipelines WHERE state IN ('submitted','running')").fetchall():
            pid = row['id']
            tasks = db.execute('SELECT * FROM tasks WHERE pipeline=?', (pid,)).fetchall()
            states = {task['id']: task['state'] for task in tasks}
            for task in tasks:
                if task['state'] not in ('waiting', 'blocked'): continue
                dependencies = json.loads(task['spec'])['needs']
                state = 'queued' if all(states[name] == 'completed' for name in dependencies) else 'blocked' if any(states[name] in ('failed', 'cancelled', 'blocked') for name in dependencies) else 'waiting'
                db.execute('UPDATE tasks SET state=? WHERE pipeline=? AND id=?', (state, pid, task['id']))
                states[task['id']] = state
            values = set(states.values())
            phase = 'failed' if values & {'failed', 'blocked'} else 'completed' if values == {'completed'} else 'running' if 'running' in values else 'submitted'
            db.execute('UPDATE pipelines SET state=? WHERE id=?', (phase, pid))

    def claim(self, worker, lease_seconds=60, *, executor="oci", images=None):
        integer(lease_seconds, 10, 300)
        with self.transaction() as db:
            self.refresh(db)
            approved = db.execute('SELECT * FROM workers WHERE id=? AND enabled=1', (worker,)).fetchone()
            if not approved: raise Error('WORKER_NOT_APPROVED', 'Worker is not enabled by an operator', 403)
            active = db.execute("SELECT spec FROM tasks WHERE worker=? AND state='running'", (worker,)).fetchall()
            cpu_used = sum(json.loads(task['spec'])['cpu'] for task in active)
            mem_used = sum(json.loads(task['spec'])['memory_mb'] for task in active)
            if len(active) >= approved['slots']: return None
            projects = set(json.loads(approved['projects']))
            rows = db.execute("SELECT t.*,p.project,p.body FROM tasks t JOIN pipelines p ON p.id=t.pipeline WHERE t.state='queued' AND p.state NOT IN ('cancelled','published') ORDER BY p.created,t.rowid LIMIT 4096").fetchall()
            for task in rows:
                spec = json.loads(task['spec'])
                if spec.get('executor','oci')!=executor or images is not None and spec['image'] not in images:continue
                if spec.get('worker',worker)!=worker:continue
                if task['project'] not in projects or spec['arch'] != approved['arch'] or spec['pool'] != approved['pool'] or not within_budget(approved['cpu'],cpu_used,spec['cpu']) or not within_budget(approved['memory_mb'],mem_used,spec['memory_mb']): continue
                lease = secrets.token_urlsafe(32)
                until, attempt = int(self.clock())+lease_seconds, task['attempt']+1
                db.execute("UPDATE tasks SET state='running',attempt=?,worker=?,lease_hash=?,lease_until=? WHERE pipeline=? AND id=?", (attempt, worker, hashlib.sha256(lease.encode()).hexdigest(), until, task['pipeline'], task['id']))
                db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,NULL,NULL)', (task['pipeline'], task['id'], attempt, worker, 'running', int(self.clock())))
                db.execute("UPDATE pipelines SET state='running' WHERE id=?", (task['pipeline'],))
                self.event(db, worker, 'task.claimed', task['pipeline'], task['id'], {'attempt': attempt})
                cache_info = None
                if spec.get('cache_key'):
                    source_dict = json.loads(task['body'])['source']
                    source_digest = source_dict.get('digest')
                    mode = spec.get('cache_mode', 'read-write')
                    paths = spec.get('cache_paths', [])
                    canonical_key = canonical_cache_key(spec['cache_key'], source_digest, spec['image'], spec['arch'], spec['argv'], paths)
                    cache_row = None if mode=='write-only' else db.execute('SELECT artifact, size, hit_count FROM build_caches WHERE project=? AND cache_key=?', (task['project'], canonical_key)).fetchone()
                    if cache_row:
                        now = int(self.clock())
                        db.execute('UPDATE build_caches SET hit_count=hit_count+1, last_accessed=? WHERE project=? AND cache_key=?', (now, task['project'], canonical_key))
                        cache_info = {'key': canonical_key, 'base_key': spec['cache_key'], 'reference': json.loads(cache_row[0]), 'size': cache_row[1], 'hit': True, 'paths': paths, 'mode': mode}
                    else:
                        cache_info = {'key': canonical_key, 'base_key': spec['cache_key'], 'reference': None, 'hit': False, 'paths': paths, 'mode': mode}
                res = {'pipeline': task['pipeline'], 'project': task['project'], 'task': spec, 'source': json.loads(task['body'])['source'], 'attempt': attempt, 'worker':worker, 'lease': lease, 'lease_until': until}
                if cache_info is not None: res['cache'] = cache_info
                return res
            return None

    def _lease(self, db, worker, pid, task, lease, active=True):
        row = db.execute('SELECT * FROM tasks WHERE pipeline=? AND id=?', (pid, task)).fetchone()
        candidate = hashlib.sha256(lease.encode()).hexdigest() if isinstance(lease, str) else ''
        if not row or row['worker'] != worker or not row['lease_hash'] or not hmac.compare_digest(row['lease_hash'], candidate):
            raise Error('LEASE_REJECTED', 'Task is not assigned to this lease', 409)
        if active and (row['state'] != 'running' or not before_deadline(int(self.clock()),row['lease_until'])):
            raise Error('LEASE_EXPIRED', 'Task lease is no longer active', 409)
        return row

    def heartbeat(self, worker, pid, task, lease, lease_seconds=60):
        integer(lease_seconds, 10, 300)
        with self.transaction() as db:
            self._lease(db, worker, pid, task, lease)
            until = int(self.clock())+lease_seconds
            db.execute('UPDATE tasks SET lease_until=? WHERE pipeline=? AND id=?', (until, pid, task))
        return {'state': 'running', 'lease_until': until}

    def finish(self, worker, pid, task, lease, *, exit_code, artifact, logs, attestation=None, cache_artifact=None, cache_size=0):
        integer(exit_code, 0, 255); reference(logs)
        if exit_code == 0: reference(artifact)
        elif artifact is not None: raise Error('INVALID_RECEIPT', 'Failed task cannot publish a success artifact')
        if cache_artifact is not None:
            if exit_code != 0: raise Error('INVALID_RECEIPT', 'Failed task cannot publish a build cache')
            reference(cache_artifact)
        receipt = encoded({'exit_code': exit_code, 'artifact': artifact, 'logs': logs})
        with self.transaction() as db:
            row = self._lease(db, worker, pid, task, lease, active=False)
            prior=db.execute('SELECT envelope FROM receipt_attestations WHERE pipeline=? AND task=? AND attempt=?',(pid,task,row['attempt'])).fetchone()
            if row['receipt']:
                if (json.loads(prior['envelope']) if prior else None)!=attestation:raise Error('RESULT_CONFLICT','Receipt signature already has another result',409)
                if row['receipt'] != receipt: raise Error('RESULT_CONFLICT', 'Lease already has another result', 409)
                return {'state': row['state'], 'duplicate': True}
            self._lease(db, worker, pid, task, lease)
            key=db.execute('SELECT public FROM worker_receipt_keys WHERE worker=?',(worker,)).fetchone()
            if key or attestation is not None:
                if not key:raise Error('WORKER_SIGNING_KEY','Worker signing key has not been independently approved',403)
                from .attestation import statement,check
                body=json.loads(db.execute('SELECT body FROM pipelines WHERE id=?',(pid,)).fetchone()['body'])
                assignment={'pipeline':pid,'task':json.loads(row['spec']),'attempt':row['attempt'],'source':body['source'],'lease':lease}
                check(attestation,key['public'],statement(worker,assignment,json.loads(receipt)))
                db.execute('INSERT INTO receipt_attestations VALUES(?,?,?,?)',(pid,task,row['attempt'],encoded(attestation)))
            state = 'completed' if exit_code == 0 else 'failed'
            db.execute('UPDATE tasks SET state=?,receipt=? WHERE pipeline=? AND id=?', (state, receipt, pid, task))
            db.execute('UPDATE attempts SET state=?,finished=?,receipt=? WHERE pipeline=? AND id=? AND attempt=?', (state, int(self.clock()), receipt, pid, task, row['attempt']))
            self.event(db, worker, 'task.'+state, pid, task)
            spec = json.loads(row['spec'])
            if exit_code == 0 and cache_artifact is not None and spec.get('cache_key') and spec.get('cache_mode','read-write')!='read-only':
                proj = db.execute('SELECT project FROM pipelines WHERE id=?', (pid,)).fetchone()['project']
                pipe_body = json.loads(db.execute('SELECT body FROM pipelines WHERE id=?', (pid,)).fetchone()['body'])
                source_digest = pipe_body.get('source', {}).get('digest')
                paths = spec.get('cache_paths', [])
                canonical_key = canonical_cache_key(spec['cache_key'], source_digest, spec['image'], spec['arch'], spec['argv'], paths)
                now = int(self.clock())
                db.execute('''
                    INSERT INTO build_caches(project, cache_key, artifact, created, last_accessed, size, hit_count, base_key, source_digest, image, arch)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                    ON CONFLICT(project, cache_key) DO UPDATE SET
                        artifact=excluded.artifact,
                        last_accessed=excluded.last_accessed,
                        size=excluded.size,
                        base_key=excluded.base_key,
                        source_digest=excluded.source_digest,
                        image=excluded.image,
                        arch=excluded.arch
                ''', (proj, canonical_key, json.dumps(cache_artifact, sort_keys=True), now, now, cache_size, spec['cache_key'], source_digest or '', spec.get('image', ''), spec.get('arch', '')))
            self.refresh(db)
        return {'state': state, 'duplicate': False, 'verification': 'pending', 'release': 'unpublished'}

    def cancel(self, actor, pid):
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM releases WHERE pipeline=? AND state='published'",(pid,)).fetchone():raise Error('CANCEL_REJECTED','Published releases require an explicit withdrawal operation',409)
            if db.execute("UPDATE pipelines SET state='cancelled' WHERE id=? AND state!='published'", (pid,)).rowcount != 1:
                raise Error('CANCEL_REJECTED', 'Pipeline not found or already published', 409)
            db.execute("UPDATE tasks SET state='cancelled',lease_hash=NULL,lease_until=NULL WHERE pipeline=? AND state NOT IN ('completed','failed')", (pid,))
            db.execute("UPDATE attempts SET state='cancelled',finished=? WHERE pipeline=? AND state='running'", (int(self.clock()), pid))
            self.event(db, actor, 'pipeline.cancelled', pid)
        return {'state': 'cancelled'}

    def retry(self, actor, pid, task):
        with self.transaction() as db:
            row = db.execute('SELECT t.*,p.state AS pipeline_state FROM tasks t JOIN pipelines p ON p.id=t.pipeline WHERE t.pipeline=? AND t.id=?', (pid, task)).fetchone()
            if not row or row['state'] != 'failed' or row['pipeline_state'] in ('cancelled', 'published') or row['attempt'] >= json.loads(row['spec'])['attempts']:
                raise Error('RETRY_REJECTED', 'Task cannot be retried within its attempt limit', 409)
            db.execute("UPDATE tasks SET state='queued',worker=NULL,lease_hash=NULL,lease_until=NULL,receipt=NULL,verification=NULL WHERE pipeline=? AND id=?", (pid, task))
            db.execute("UPDATE pipelines SET state='submitted' WHERE id=?",(pid,))
            self.event(db, actor, 'task.retried', pid, task)
            self.refresh(db)
        return {'state': 'queued'}

    def inspect(self, pid):
        with self.transaction() as db:
            self.refresh(db)
            pipeline = db.execute('SELECT * FROM pipelines WHERE id=?', (pid,)).fetchone()
            if not pipeline: raise Error('PIPELINE_NOT_FOUND', 'Pipeline not found', 404)
            tasks = []
            for row in db.execute('SELECT * FROM tasks WHERE pipeline=? ORDER BY rowid', (pid,)):
                signed=db.execute('SELECT envelope FROM receipt_attestations WHERE pipeline=? AND task=? AND attempt=?',(pid,row['id'],row['attempt'])).fetchone()
                tasks.append({key: row[key] for key in ('id', 'state', 'attempt', 'worker', 'lease_until')} | {'receipt': json.loads(row['receipt']) if row['receipt'] else None, 'verification': json.loads(row['verification']) if row['verification'] else None,'attestation':json.loads(signed['envelope']) if signed else None})
            publications=[dict(row) for row in db.execute('SELECT id,state,name,version,publisher FROM releases WHERE pipeline=? ORDER BY created',(pid,))]
            return {'pipeline': pid, 'project': pipeline['project'], 'state': pipeline['state'], 'tasks': tasks, 'release': 'published' if any(row['state']=='published' for row in publications) else 'unpublished', 'releases':publications, 'settlement': 'not_requested'}

    def append_log(self, worker, pid, task, lease, position, data):
        integer(position, 0, 65535)
        if not isinstance(data, bytes) or not 1 <= len(data) <= 16384: raise Error('LOG_CHUNK', 'Bounded binary log chunk required')
        with self.transaction() as db:
            row = self._lease(db, worker, pid, task, lease)
            previous = db.execute('SELECT body FROM log_chunks WHERE pipeline=? AND task=? AND attempt=? AND position=?', (pid,task,row['attempt'],position)).fetchone()
            if previous:
                if previous['body'] != data: raise Error('LOG_CONFLICT', 'Position already has different log bytes', 409)
                return {'position':position, 'duplicate':True}
            count, used = db.execute('SELECT count(*),coalesce(sum(length(body)),0) FROM log_chunks WHERE pipeline=? AND task=? AND attempt=?', (pid,task,row['attempt'])).fetchone()
            if position != count: raise Error('LOG_CURSOR', 'Log chunks must arrive in sequence', 409)
            if used+len(data) > 1024*1024: raise Error('LIVE_LOG_LIMIT', 'Live log budget reached; full log must be stored as an artifact', 413)
            db.execute('INSERT INTO log_chunks VALUES(?,?,?,?,?)', (pid,task,row['attempt'],position,data))
        return {'position':position,'duplicate':False}

    def logs(self, pid, task, attempt, after=-1):
        integer(attempt,1,5); integer(after,-1,65535)
        with closing(self.connect()) as db:
            return [{'position':row['position'],'data':row['body']} for row in db.execute('SELECT position,body FROM log_chunks WHERE pipeline=? AND task=? AND attempt=? AND position>? ORDER BY position LIMIT 64', (pid,task,attempt,after))]

    def list_pipelines(self, project, limit=50, before=2**63-1):
        identifier(project); integer(limit,1,100); integer(before,0,2**63-1)
        with self.transaction() as db:
            self.refresh(db)
            return [dict(row) for row in db.execute('SELECT rowid AS cursor,id,project,state,created FROM pipelines WHERE project=? AND rowid<? ORDER BY rowid DESC LIMIT ?', (project,before,limit))]

    def audit(self, pid, after=0):
        integer(after,0,2**63-1)
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute('SELECT sequence,created,actor,action,task,detail FROM events WHERE pipeline=? AND sequence>? ORDER BY sequence LIMIT 100', (pid,after))]

    def verify_rebuild(self, actor, pid, task, independent_task):
        if task==independent_task: raise Error('SELF_VERIFICATION','Independent task required',409)
        with self.transaction() as db:
            rows = [db.execute('SELECT * FROM tasks WHERE pipeline=? AND id=?',(pid,name)).fetchone() for name in (task,independent_task)]
            first,second=rows
            pipeline=db.execute('SELECT state FROM pipelines WHERE id=?',(pid,)).fetchone()
            if not pipeline or pipeline['state']!='completed':raise Error('VERIFICATION_STATE','Pipeline must be completed and not cancelled',409)
            if not first or not second or first['state']!='completed' or second['state']!='completed' or first['worker']==second['worker']:
                raise Error('VERIFICATION_REJECTED','Two completed tasks from distinct approved workers required',409)
            trusted=db.execute("SELECT * FROM workers WHERE id=? AND pool='trusted' AND enabled=1", (second['worker'],)).fetchone()
            if not trusted:raise Error('VERIFIER_NOT_TRUSTED','Independent verification requires enabled Trusted Worker',403)
            a,b=json.loads(first['spec']),json.loads(second['spec'])
            profiles=None
            if 'worker' in a or 'worker' in b:
                profiles=[db.execute('SELECT b.* FROM worker_build_profiles b JOIN workers w ON w.id=b.worker WHERE b.worker=? AND w.enabled=1',(r['worker'],)).fetchone() for r in (first,second)]
                if any(p is None or a['image'] not in json.loads(p['images']) for p in profiles) or profiles[0]['domain']==profiles[1]['domain']:
                    raise Error('BUILD_DOMAINS','Replica verification requires enabled approved images in distinct failure domains',409)
            if not a['outputs'] or a['outputs']!=b['outputs']:raise Error('VERIFICATION_OUTPUTS','Independent builds require identical declared output files',409)
            if any(a[key]!=b[key] for key in ('image','argv','arch')):
                raise Error('VERIFICATION_INPUT_MISMATCH','Independent build must use the same image, arguments and architecture',409)
            receipt_a,receipt_b=json.loads(first['receipt']),json.loads(second['receipt'])
            if receipt_a['artifact']['digest']!=receipt_b['artifact']['digest']:
                raise Error('BUILD_MISMATCH','Independent output digests differ',409)
            result={'status':'matched','verifier_worker':second['worker'],'independent_task':independent_task,
                    'method':'independent-task-output-equality','artifact':receipt_a['artifact'],
                    'software_security_verified':False,'reproducibility_across_hosts_verified':False}
            if profiles is not None:result['build_profiles']=[dict(profile) for profile in profiles]
            db.execute('UPDATE tasks SET verification=? WHERE pipeline=? AND id=?',(encoded(result),pid,task))
            signing_keys=[db.execute('SELECT public FROM worker_receipt_keys WHERE worker=?',(r['worker'],)).fetchone() for r in (first,second)]
            if all(signing_keys) and signing_keys[0]['public']==signing_keys[1]['public']:raise Error('SELF_VERIFICATION','Distinct signed Worker identities required',409)
            if any(signing_keys):self._release_verification(db,pid,task)
            self.event(db,actor,'task.verified',pid,task,{'independent_task':independent_task})
        return result

    def task_spec(self, pid, task):
        with closing(self.connect()) as db:
            row=db.execute('SELECT spec FROM tasks WHERE pipeline=? AND id=?',(pid,task)).fetchone()
            if not row:raise Error('TASK_NOT_FOUND','Task not found',404)
            return json.loads(row['spec'])

    def _release_verification(self,db,pid,task):
        """Revalidate current authority, exact receipts and independent build profiles.

        Called inside the same write transaction as each release state change.
        Historical verification is evidence, never a permanent authorization.
        """
        row=db.execute('SELECT * FROM tasks WHERE pipeline=? AND id=?',(pid,task)).fetchone()
        verification=json.loads(row['verification']) if row and row['verification'] else {}
        peer=db.execute('SELECT * FROM tasks WHERE pipeline=? AND id=?',(pid,verification.get('independent_task'))).fetchone()
        if (verification.get('status')!='matched' or not row or not peer or row['id']==peer['id'] or
                row['state']!='completed' or peer['state']!='completed' or row['worker']==peer['worker'] or
                peer['worker']!=verification.get('verifier_worker')):
            raise Error('RELEASE_VERIFIER','Current independent completed task verification required',409)
        workers=[db.execute('SELECT * FROM workers WHERE id=? AND enabled=1',(r['worker'],)).fetchone() for r in (row,peer)]
        project=db.execute('SELECT project FROM pipelines WHERE id=?',(pid,)).fetchone()['project']
        if any(w is None or project not in json.loads(w['projects']) for w in workers) or workers[1]['pool']!='trusted':
            raise Error('RELEASE_VERIFIER','Both workers must remain authorized and verifier Trusted',409)
        a,b=json.loads(row['spec']),json.loads(peer['spec'])
        if any(a[k]!=b[k] for k in ('image','argv','arch','outputs')) or not a['outputs']:
            raise Error('RELEASE_VERIFIER','Independent build inputs changed',409)
        receipts=[json.loads(r['receipt']) for r in (row,peer)]
        if any(r['exit_code']!=0 or r['artifact']['digest']!=verification.get('artifact',{}).get('digest') for r in receipts):
            raise Error('RELEASE_VERIFIER','Verified output receipts changed',409)
        for completed in (row,peer):
            key=db.execute('SELECT public FROM worker_receipt_keys WHERE worker=?',(completed['worker'],)).fetchone()
            signed=db.execute('SELECT envelope FROM receipt_attestations WHERE pipeline=? AND task=? AND attempt=?',(pid,completed['id'],completed['attempt'])).fetchone()
            if key or signed:
                if not key or not signed:raise Error('RELEASE_WORKER_SIGNATURE','Current signed Worker results required; rebuild unsigned historical tasks',409)
                from .attestation import check
                envelope=json.loads(signed['envelope']);body=json.loads(db.execute('SELECT body FROM pipelines WHERE id=?',(pid,)).fetchone()['body'])
                expected={'schema':'openci.worker-receipt.v1','worker':completed['worker'],'pipeline':pid,'task':completed['id'],'attempt':completed['attempt'],'source':body['source'],
                          'task_digest':'sha256:'+hashlib.sha256(encoded(json.loads(completed['spec'])).encode()).hexdigest(),'lease_digest':'sha256:'+completed['lease_hash'],'result':json.loads(completed['receipt'])}
                check(envelope,key['public'],expected)
        if 'worker' in a or 'worker' in b:
            profiles=[db.execute('SELECT * FROM worker_build_profiles WHERE worker=?',(r['worker'],)).fetchone() for r in (row,peer)]
            if (any(p is None or a['image'] not in json.loads(p['images']) for p in profiles) or
                    profiles[0]['domain']==profiles[1]['domain'] or
                    [dict(p) for p in profiles]!=verification.get('build_profiles')):
                raise Error('RELEASE_BUILD_PROFILE_CHANGED','Independent build approval changed; verify again',409)
        return verification

    def prepare_release(self,actor,pid,task,name,version,publisher,request):
        from ziokt.ufsdcpm import _label
        _label(name);_label(version)
        if not isinstance(publisher,str) or not re.fullmatch('[a-f0-9]{64}',publisher):raise Error('RELEASE_PUBLISHER','Verified publisher required')
        body=encoded(request);rid=hashlib.sha256(body.encode()).hexdigest()
        with self.transaction() as db:
            pipeline=db.execute('SELECT * FROM pipelines WHERE id=?',(pid,)).fetchone()
            row=db.execute('SELECT * FROM tasks WHERE pipeline=? AND id=?',(pid,task)).fetchone()
            if not pipeline or pipeline['state']!='completed' or not row or row['state']!='completed' or not row['verification']:
                raise Error('RELEASE_NOT_VERIFIED','Completed and independently verified output required',409)
            self._release_verification(db,pid,task)
            prior=db.execute('SELECT * FROM releases WHERE name=? AND version=? AND publisher=?',(name,version,publisher)).fetchone()
            if prior:
                if prior['id']!=rid or prior['request']!=body:raise Error('RELEASE_VERSION_CONFLICT','Release version already describes another verified build',409)
                return dict(prior)
            if db.execute('SELECT count(*) FROM releases').fetchone()[0]>=10000:raise Error('RELEASE_QUOTA','Release retention limit reached',429)
            db.execute('INSERT INTO releases VALUES(?,?,?,?,?,?,?,?,?,NULL,?)',(rid,pid,task,pipeline['project'],name,version,publisher,'prepared',body,int(self.clock())))
            self.event(db,actor,'release.prepared',pid,task,{'release':rid})
            return dict(db.execute('SELECT * FROM releases WHERE id=?',(rid,)).fetchone())

    def complete_release(self,actor,rid,publication):
        body=encoded(publication)
        with self.transaction() as db:
            row=db.execute('SELECT * FROM releases WHERE id=?',(rid,)).fetchone()
            if not row or row['state'] not in ('prepared','published'):raise Error('RELEASE_STATE','Release cannot be published in current state',409)
            if row['publication'] and row['publication']!=body:raise Error('RELEASE_RESULT_CONFLICT','Publication already has another result',409)
            if row['state']=='prepared':
                pipeline=db.execute('SELECT state FROM pipelines WHERE id=?',(row['pipeline'],)).fetchone()
                if not pipeline or pipeline['state']!='completed':
                    raise Error('RELEASE_AUTHORIZATION_CHANGED','Pipeline authorization changed before publication',409)
                self._release_verification(db,row['pipeline'],row['task'])
                db.execute("UPDATE releases SET state='published',publication=? WHERE id=?",(body,rid))
                self.event(db,actor,'release.published',row['pipeline'],row['task'],{'release':rid,'native_package':publication['package_id']})
        return self.release(rid)

    def release(self,rid):
        with closing(self.connect()) as db:
            row=db.execute('SELECT * FROM releases WHERE id=?',(rid,)).fetchone()
            if not row:raise Error('RELEASE_NOT_FOUND','Release not found',404)
            result=dict(row);result['request']=json.loads(result['request']);result['publication']=json.loads(result['publication']) if result['publication'] else None
            return result

    def withdraw_release(self,actor,rid):
        with self.transaction() as db:
            row=db.execute('SELECT * FROM releases WHERE id=?',(rid,)).fetchone()
            if not row or row['state']!='published':raise Error('RELEASE_STATE','Published release required',409)
            db.execute("UPDATE releases SET state='withdrawn' WHERE id=?",(rid,))
            self.event(db,actor,'release.withdrawn',row['pipeline'],row['task'],{'release':rid,'independent_copies_deleted':False})
        return self.release(rid)

    def cache_get(self, project, key):
        with closing(self.connect()) as db:
            row = db.execute('''
                SELECT cache_key, artifact, size, hit_count 
                FROM build_caches 
                WHERE project=? AND (cache_key=? OR base_key=?)
                ORDER BY (cache_key=?) DESC, last_accessed DESC LIMIT 1
            ''', (project, key, key, key)).fetchone()
            if not row: return None
            now = int(self.clock())
            db.execute('UPDATE build_caches SET hit_count=hit_count+1, last_accessed=? WHERE project=? AND cache_key=?', (now, project, row['cache_key']))
            db.commit()
            return {'cache_key': row['cache_key'], 'artifact': json.loads(row['artifact']), 'size': row['size'], 'hit_count': row['hit_count'] + 1}

    def cache_put(self, project, key, artifact, size=0, base_key='', source_digest='', image='', arch=''):
        reference(artifact)
        if type(size) is not int or not 0 <= size <= 512*1024*1024:
            raise Error('INVALID_CACHE_SIZE', 'Cache size outside budget')
        now = int(self.clock())
        payload = json.dumps(artifact, sort_keys=True)
        with closing(self.connect()) as db:
            db.execute('''
                INSERT INTO build_caches(project, cache_key, artifact, created, last_accessed, size, hit_count, base_key, source_digest, image, arch)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                ON CONFLICT(project, cache_key) DO UPDATE SET
                    artifact=excluded.artifact,
                    last_accessed=excluded.last_accessed,
                    size=excluded.size,
                    base_key=excluded.base_key,
                    source_digest=excluded.source_digest,
                    image=excluded.image,
                    arch=excluded.arch
            ''', (project, key, payload, now, now, size, base_key or key, source_digest or '', image or '', arch or ''))
            db.commit()
        return {'project': project, 'cache_key': key, 'size': size, 'stored': True}

    def queue_package_publication(self, release_id, project, package_name, version, payload):
        now = int(self.clock())
        with closing(self.connect()) as db:
            db.execute('''
                INSERT INTO pending_package_publications(release_id, project, package_name, version, payload, attempts, last_attempt, last_error, status, created)
                VALUES(?, ?, ?, ?, ?, 0, 0, '', 'pending', ?)
                ON CONFLICT(release_id) DO UPDATE SET
                    payload=excluded.payload,
                    status='pending'
            ''', (release_id, project, package_name, version, json.dumps(payload, sort_keys=True), now))
            db.commit()

    def record_package_publication(self, release_id, success, error=None):
        now = int(self.clock())
        status = 'published' if success else 'failed'
        err_str = '' if success else str(error or 'unknown error')[:1024]
        with closing(self.connect()) as db:
            if success:
                db.execute("UPDATE pending_package_publications SET status='published', last_attempt=?, last_error='' WHERE release_id=?", (now, release_id))
            else:
                db.execute("UPDATE pending_package_publications SET status='failed', attempts=attempts+1, last_attempt=?, last_error=? WHERE release_id=?", (now, err_str, release_id))
            db.commit()

    def list_pending_publications(self, project=None):
        with closing(self.connect()) as db:
            if project:
                rows = db.execute("SELECT * FROM pending_package_publications WHERE project=? AND status!='published' ORDER BY created", (project,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM pending_package_publications WHERE status!='published' ORDER BY created").fetchall()
            return [{
                'release_id': r['release_id'],
                'project': r['project'],
                'package_name': r['package_name'],
                'version': r['version'],
                'payload': json.loads(r['payload']),
                'attempts': r['attempts'],
                'last_attempt': r['last_attempt'],
                'last_error': r['last_error'],
                'status': r['status'],
                'created': r['created']
            } for r in rows]

    def cache_list(self, project, limit=100):
        with closing(self.connect()) as db:
            rows = db.execute('''
                SELECT cache_key, artifact, created, last_accessed, size, hit_count
                FROM build_caches WHERE project=? ORDER BY last_accessed DESC LIMIT ?
            ''', (project, min(max(1, limit), 500))).fetchall()
            return [{
                'cache_key': r[0], 'artifact': json.loads(r[1]),
                'created': r[2], 'last_accessed': r[3], 'size': r[4], 'hit_count': r[5]
            } for r in rows]

    def cache_delete(self, project, key):
        with closing(self.connect()) as db:
            cursor = db.execute('DELETE FROM build_caches WHERE project=? AND cache_key=?', (project, key))
            db.commit()
            return {'deleted': bool(cursor.rowcount)}

    def cache_prune(self, project, max_bytes=64*1024*1024, max_age_seconds=86400*30):
        now = int(self.clock())
        pruned = 0
        pruned_bytes = 0
        with closing(self.connect()) as db:
            if max_age_seconds > 0:
                cutoff = now - max_age_seconds
                expired = db.execute('SELECT cache_key, size FROM build_caches WHERE project=? AND last_accessed < ?', (project, cutoff)).fetchall()
                for key, sz in expired:
                    db.execute('DELETE FROM build_caches WHERE project=? AND cache_key=?', (project, key))
                    pruned += 1
                    pruned_bytes += sz
            total = db.execute('SELECT COALESCE(SUM(size), 0) FROM build_caches WHERE project=?', (project,)).fetchone()[0]
            if total > max_bytes:
                lru = db.execute('SELECT cache_key, size FROM build_caches WHERE project=? ORDER BY last_accessed ASC', (project,)).fetchall()
                for key, sz in lru:
                    if total <= max_bytes: break
                    db.execute('DELETE FROM build_caches WHERE project=? AND cache_key=?', (project, key))
                    total -= sz
                    pruned += 1
                    pruned_bytes += sz
            db.commit()
        return {'pruned_entries': pruned, 'pruned_bytes': pruned_bytes}

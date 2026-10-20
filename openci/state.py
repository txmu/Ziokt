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
from pathlib import Path
import re
import secrets
import sqlite3
import time

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


def validate_pipeline(value):
    if not isinstance(value, dict) or set(value) != {'schema', 'project', 'nonce', 'source', 'tasks'} or value['schema'] != 'openci.pipeline.v1':
        raise Error('INVALID_PIPELINE', 'Versioned pipeline with exact fields required')
    identifier(value['project']); identifier(value['nonce']); reference(value['source'])
    if not isinstance(value['tasks'], list) or not 1 <= len(value['tasks']) <= 128:
        raise Error('INVALID_DAG', 'Between one and 128 tasks required')
    tasks = {}
    for task in value['tasks']:
        if not isinstance(task, dict) or set(task) != {'id', 'needs', 'image', 'argv', 'arch', 'pool', 'cpu', 'memory_mb', 'timeout', 'attempts'}:
            raise Error('INVALID_TASK', 'Exact task fields required')
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
                CREATE TABLE IF NOT EXISTS attempts(pipeline TEXT,id TEXT,attempt INTEGER,worker TEXT,state TEXT,started INTEGER,finished INTEGER,receipt TEXT,PRIMARY KEY(pipeline,id,attempt),FOREIGN KEY(pipeline,id) REFERENCES tasks(pipeline,id));
                CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,created INTEGER NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,pipeline TEXT,task TEXT,detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS log_chunks(pipeline TEXT,task TEXT,attempt INTEGER,position INTEGER,body BLOB NOT NULL,PRIMARY KEY(pipeline,task,attempt,position),FOREIGN KEY(pipeline,task) REFERENCES tasks(pipeline,id));
                PRAGMA user_version=1;
            ''')
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
            self.event(db, actor, 'worker.approved', detail={'worker': worker, 'pool': pool})

    def disable_worker(self, actor, worker):
        with self.transaction() as db:
            if db.execute('UPDATE workers SET enabled=0 WHERE id=?', (worker,)).rowcount != 1:
                raise Error('WORKER_UNKNOWN', 'Worker not approved', 404)
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

    def claim(self, worker, lease_seconds=60):
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
                if task['project'] not in projects or spec['arch'] != approved['arch'] or spec['pool'] != approved['pool'] or spec['cpu']+cpu_used > approved['cpu'] or spec['memory_mb']+mem_used > approved['memory_mb']: continue
                lease = secrets.token_urlsafe(32)
                until, attempt = int(self.clock())+lease_seconds, task['attempt']+1
                db.execute("UPDATE tasks SET state='running',attempt=?,worker=?,lease_hash=?,lease_until=? WHERE pipeline=? AND id=?", (attempt, worker, hashlib.sha256(lease.encode()).hexdigest(), until, task['pipeline'], task['id']))
                db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,NULL,NULL)', (task['pipeline'], task['id'], attempt, worker, 'running', int(self.clock())))
                db.execute("UPDATE pipelines SET state='running' WHERE id=?", (task['pipeline'],))
                self.event(db, worker, 'task.claimed', task['pipeline'], task['id'], {'attempt': attempt})
                return {'pipeline': task['pipeline'], 'project': task['project'], 'task': spec, 'source': json.loads(task['body'])['source'], 'attempt': attempt, 'lease': lease, 'lease_until': until}
            return None

    def _lease(self, db, worker, pid, task, lease, active=True):
        row = db.execute('SELECT * FROM tasks WHERE pipeline=? AND id=?', (pid, task)).fetchone()
        candidate = hashlib.sha256(lease.encode()).hexdigest() if isinstance(lease, str) else ''
        if not row or row['worker'] != worker or not row['lease_hash'] or not hmac.compare_digest(row['lease_hash'], candidate):
            raise Error('LEASE_REJECTED', 'Task is not assigned to this lease', 409)
        if active and (row['state'] != 'running' or row['lease_until'] <= int(self.clock())):
            raise Error('LEASE_EXPIRED', 'Task lease is no longer active', 409)
        return row

    def heartbeat(self, worker, pid, task, lease, lease_seconds=60):
        integer(lease_seconds, 10, 300)
        with self.transaction() as db:
            self._lease(db, worker, pid, task, lease)
            until = int(self.clock())+lease_seconds
            db.execute('UPDATE tasks SET lease_until=? WHERE pipeline=? AND id=?', (until, pid, task))
        return {'state': 'running', 'lease_until': until}

    def finish(self, worker, pid, task, lease, *, exit_code, artifact, logs):
        integer(exit_code, 0, 255); reference(logs)
        if exit_code == 0: reference(artifact)
        elif artifact is not None: raise Error('INVALID_RECEIPT', 'Failed task cannot publish a success artifact')
        receipt = encoded({'exit_code': exit_code, 'artifact': artifact, 'logs': logs})
        with self.transaction() as db:
            row = self._lease(db, worker, pid, task, lease, active=False)
            if row['receipt']:
                if row['receipt'] != receipt: raise Error('RESULT_CONFLICT', 'Lease already has another result', 409)
                return {'state': row['state'], 'duplicate': True}
            self._lease(db, worker, pid, task, lease)
            state = 'completed' if exit_code == 0 else 'failed'
            db.execute('UPDATE tasks SET state=?,receipt=? WHERE pipeline=? AND id=?', (state, receipt, pid, task))
            db.execute('UPDATE attempts SET state=?,finished=?,receipt=? WHERE pipeline=? AND id=? AND attempt=?', (state, int(self.clock()), receipt, pid, task, row['attempt']))
            self.event(db, worker, 'task.'+state, pid, task)
            self.refresh(db)
        return {'state': state, 'duplicate': False, 'verification': 'pending', 'release': 'unpublished'}

    def cancel(self, actor, pid):
        with self.transaction() as db:
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
                tasks.append({key: row[key] for key in ('id', 'state', 'attempt', 'worker', 'lease_until')} | {'receipt': json.loads(row['receipt']) if row['receipt'] else None, 'verification': json.loads(row['verification']) if row['verification'] else None})
            return {'pipeline': pid, 'project': pipeline['project'], 'state': pipeline['state'], 'tasks': tasks, 'release': 'unpublished', 'settlement': 'not_requested'}

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
            if not first or not second or first['state']!='completed' or second['state']!='completed' or first['worker']==second['worker']:
                raise Error('VERIFICATION_REJECTED','Two completed tasks from distinct approved workers required',409)
            trusted=db.execute("SELECT * FROM workers WHERE id=? AND pool='trusted' AND enabled=1", (second['worker'],)).fetchone()
            if not trusted:raise Error('VERIFIER_NOT_TRUSTED','Independent verification requires enabled Trusted Worker',403)
            a,b=json.loads(first['spec']),json.loads(second['spec'])
            if any(a[key]!=b[key] for key in ('image','argv','arch')):
                raise Error('VERIFICATION_INPUT_MISMATCH','Independent build must use the same image, arguments and architecture',409)
            receipt_a,receipt_b=json.loads(first['receipt']),json.loads(second['receipt'])
            if receipt_a['artifact']['digest']!=receipt_b['artifact']['digest']:
                raise Error('BUILD_MISMATCH','Independent output digests differ',409)
            result={'status':'matched','verifier_worker':second['worker'],'independent_task':independent_task,
                    'method':'independent-task-output-equality','artifact':receipt_a['artifact'],
                    'software_security_verified':False,'reproducibility_across_hosts_verified':False}
            db.execute('UPDATE tasks SET verification=? WHERE pipeline=? AND id=?',(encoded(result),pid,task))
            self.event(db,actor,'task.verified',pid,task,{'independent_task':independent_task})
        return result

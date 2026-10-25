"""Standalone Controller API using native Ziokt Content Fabric for object bytes."""
from contextlib import closing
import base64
import hashlib
import hmac
import http.server
import json
from pathlib import Path
import socketserver
import socket
import threading
import time
from collections import deque
import tempfile
import tarfile
from urllib.parse import parse_qs, urlsplit

from ziokt.content_fabric import Fabric
from ziokt.protocol import ProtocolError, secure_read, strict_json
from .state import Error, Store, identifier, reference


class Controller:
    def __init__(self, root, config):
        self.root = Path(root)
        self.config = Path(config)
        self.git_slot=threading.BoundedSemaphore(1)
        self.enrollment_lock=threading.Lock();self.enrollment_attempts=deque(maxlen=60)
        self.state = Store(root)
        from .enrollment import setup
        self.enrollment_secret=setup(self.state)
        self.fabric = Fabric(self.root/'content')

    def close(self):
        self.fabric.close()

    def authenticate(self, authorization):
        if not isinstance(authorization, str) or not authorization.startswith('Bearer ') or len(authorization) > 256:
            raise Error('AUTH_REQUIRED', 'Bearer authorization required', 401)
        candidate = hashlib.sha256(authorization[7:].encode()).hexdigest()
        settings = strict_json(secure_read(self.config, 65536), 65536)
        for name, principal in settings['principals'].items():
            if hmac.compare_digest(principal['token_sha256'], candidate):
                return name, principal
        from .enrollment import authenticate
        enrolled=authenticate(self.state,candidate)
        if enrolled:return enrolled
        raise Error('AUTH_REJECTED', 'Invalid or revoked credential', 401)

    @staticmethod
    def project(principal, project, roles=None):
        identifier(project)
        if roles and principal['role'] not in roles or principal['role'] != 'admin' and project not in principal['projects']:
            raise Error('PROJECT_FORBIDDEN', 'Principal cannot access this project', 403)
        return 'openci-'+project

    def pipeline(self, principal, pid, roles=None):
        result = self.state.inspect(pid)
        self.project(principal, result['project'], roles)
        return result

    def content_reference(self, owner, value):
        reference(value)
        with self.fabric.lock:
            row = self.fabric.object_info(owner, value['object'])
        metadata = json.loads(row['metadata'])
        if metadata['digest'] != value['digest']:
            raise Error('REFERENCE_MISMATCH', 'Object plaintext digest differs from declared input', 409)
        return row

    def check_outputs(self, pipeline, task_id):
        from .runner import canonical_outputs, MAX_OUTPUT
        spec=self.state.task_spec(pipeline['pipeline'],task_id)
        if not spec['outputs']:raise Error('VERIFICATION_OUTPUTS','Declared output files required for build verification',409)
        task=next((entry for entry in pipeline['tasks'] if entry['id']==task_id),None)
        if not task or task['state']!='completed' or not task['receipt']:
            raise Error('VERIFICATION_STATE','Completed task with output receipt required',409)
        owner='openci-'+pipeline['project']
        row=self.content_reference(owner,task['receipt']['artifact'])
        if json.loads(row['metadata'])['size']>MAX_OUTPUT:raise Error('ARTIFACT_LIMIT','Verification artifact exceeds budget',413)
        metadata=json.loads(row['metadata'])
        artifact_set=None
        if metadata['size']<=65536:
            with self.fabric.store(owner) as store:payload=b''.join(store.stream(row['reference']))
            try:
                candidate=strict_json(payload,65536)
                if isinstance(candidate,dict) and candidate.get('schema')=='openci.artifact-set.v1':artifact_set=candidate
            except (ProtocolError,ValueError):pass
        if artifact_set is not None:
            from .artifacts import validate_set
            if metadata['size']>65536:raise Error('ARTIFACT_LIMIT','Artifact manifest exceeds budget',413)
            with closing(self.state.connect()) as db:source=json.loads(db.execute('SELECT body FROM pipelines WHERE id=?',(pipeline['pipeline'],)).fetchone()[0])['source']
            value=validate_set(artifact_set,source=source,image=spec['image'],required=spec['outputs'])
            for entry in value['files']:
                member=self.content_reference(owner,entry['reference'])
                if json.loads(member['metadata'])['size']!=entry['size']:raise Error('ARTIFACT_SIZE','Artifact member size differs from native object',409)
                self.fabric.verify_object(owner,entry['reference']['object'])
            return value['files']
        with tempfile.TemporaryDirectory(prefix='openci-verify-') as directory:
            archive=Path(directory)/'artifact.tar'
            with archive.open('wb') as output,self.fabric.store(owner) as store:
                for chunk in store.stream(row['reference']):output.write(chunk)
            try:canonical_outputs(archive,Path(directory)/'checked.tar',spec['outputs'])
            except (tarfile.TarError,ValueError) as error:
                if isinstance(error,Error):raise
                raise Error('ARTIFACT_FORMAT','Artifact is not a valid bounded output archive',409) from None

    def dispatch(self, method, path, query, body, actor, principal):
        if method=='POST' and path=='/v1/light/claim':
            from .light import claim
            return 200,claim(self,principal,body)
        if method=='GET' and path=='/v1/me':
            return 200,{'principal':actor,'role':principal['role'],'projects':principal['projects'],'worker':principal.get('worker'),'native_rewards_enabled':False}
        if method=='POST' and path=='/v1/enrollments/invites':
            if principal['role']!='admin':raise Error('ADMIN_REQUIRED','Only an operator can approve enrollment',403)
            from .enrollment import invite
            return 201,invite(self.state,actor,body)
        if method=='POST' and path=='/v1/contributions/prepare':
            if type(body) is not dict or set(body)!={'pipeline','task','policy','engine','bounty'}:raise Error('CHAIN_FIELDS','Exact contribution plan fields required')
            self.pipeline(principal,body['pipeline'],{'admin','submit'})
            from .chain import prepare
            return 200,prepare(self.state,body['pipeline'],body['task'],body['policy'],body['engine'],body['bounty'])
        if method=='POST' and path=='/v1/workers/build-profile':
            if principal['role']!='admin':raise Error('ADMIN_REQUIRED','Build profiles require operator verification',403)
            from .quorum import approve
            return 200,approve(self.state,actor,**body)
        if method=='POST' and path=='/v1/workers/presence':
            if principal['role']!='worker':raise Error('WORKER_REQUIRED','Dedicated worker identity required',403)
            from .quorum import presence
            return 200,presence(self.state,principal['worker'],body['images'])
        if method=='POST' and path=='/v1/rebuilds':
            self.pipeline(principal,body['pipeline'],{'admin','submit'})
            from .quorum import enqueue
            result=enqueue(self.state,actor,body['pipeline'],body['task'],body['nonce'],body.get('minimum',2))
            return (202 if result['state']=='submitted' else 200),result
        if method == 'GET' and path == '/v1/pipelines':
            project=query['project'][0];self.project(principal,project)
            return 200, {'pipelines':self.state.list_pipelines(project,before=int(query.get('before',[str(2**63-1)])[0]))}
        if method == 'GET' and path == '/v1/audit':
            pid=query['pipeline'][0];self.pipeline(principal,pid)
            return 200, {'events':self.state.audit(pid,int(query.get('after',['0'])[0]))}
        if method == 'POST' and path == '/v1/releases':
            self.pipeline(principal,body['pipeline'],{'admin'})
            from .release import ReleaseService
            return 200,ReleaseService(self).publish(actor,body['pipeline'],body['task'],body['name'],body['version'])
        if method == 'GET' and path.startswith('/v1/releases/'):
            release=self.state.release(path.split('/')[-1]);self.project(principal,release['project'])
            return 200,release
        if method == 'POST' and path == '/v1/releases/withdraw':
            release=self.state.release(body['release']);self.project(principal,release['project'],{'admin'})
            return 200,self.state.withdraw_release(actor,body['release'])
        if method == 'POST' and path == '/v1/verify':
            pipeline=self.pipeline(principal,body['pipeline'],{'admin'})
            for task_id in (body['task'],body['independent_task']):
                self.check_outputs(pipeline,task_id)
            return 200,self.state.verify_rebuild(actor,body['pipeline'],body['task'],body['independent_task'])
        if method=='GET' and path=='/v1/git/status':
            project=query['project'][0];self.project(principal,project)
            with closing(self.state.connect()) as db:
                deliveries=[dict(row) for row in db.execute('SELECT delivery,commit_id,state,pipeline,error,updated FROM git_deliveries WHERE project=? ORDER BY updated DESC LIMIT 100',(project,))]
                schedule=db.execute('SELECT next_due FROM git_schedules WHERE project=?',(project,)).fetchone()
            from .git_source import settings
            configured=settings(self,project)
            return 200,{'project':project,'deliveries':deliveries,'next_due':schedule['next_due'] if schedule else None,'automatic_mirror_fetch':bool(configured.get('remote_url'))}
        if method=='POST' and path=='/v1/git/trigger':
            self.project(principal,body['project'],{'admin','submit'})
            from .git_source import trigger
            return 202,trigger(self,actor,body['project'],body['commit'],body['delivery'])
        if method == 'POST' and path == '/v1/pipelines':
            owner = self.project(principal, body.get('project'), {'admin', 'submit'})
            self.content_reference(owner, body.get('source'))
            if any(isinstance(task,dict) and task.get('executor')=='light-c' for task in body.get('tasks',[])):
                from .light import check_source
                check_source(self,owner,body['source'])
            return 202, self.state.submit(actor, body)
        if method == 'GET' and path == '/v1/logs':
            pid = query['pipeline'][0]; self.pipeline(principal,pid)
            rows = self.state.logs(pid,query['task'][0],int(query['attempt'][0]),int(query.get('after',['-1'])[0]))
            return 200, {'chunks':[{'position':r['position'],'data_base64':base64.b64encode(r['data']).decode()} for r in rows]}
        if method == 'GET' and path.startswith('/v1/pipelines/'):
            return 200, self.pipeline(principal, path.split('/')[-1])
        if method == 'POST' and path in {'/v1/cancel', '/v1/retry'}:
            self.pipeline(principal, body['pipeline'], {'admin', 'submit'})
            if path == '/v1/cancel': return 200, self.state.cancel(actor, body['pipeline'])
            return 200, self.state.retry(actor, body['pipeline'], body['task'])
        if method=='POST' and path=='/v1/workers/signing-key':
            if principal['role']!='admin':raise Error('ADMIN_REQUIRED','Worker signing identity requires operator approval',403)
            if not isinstance(body,dict) or set(body)!={'worker','public','evidence'}:raise Error('INVALID_REQUEST','Exact signing identity fields required')
            return 200,self.state.approve_receipt_key(actor,**body)
        if method == 'POST' and path == '/v1/workers/disable':
            if principal['role']!='admin':raise Error('ADMIN_REQUIRED','Worker revocation requires operator approval',403)
            if not isinstance(body,dict) or set(body)!={'worker'}:raise Error('INVALID_REQUEST','Exact worker identity required')
            self.state.disable_worker(actor,identifier(body['worker']))
            return 200,{'state':'disabled','worker':body['worker']}
        if method == 'POST' and path == '/v1/workers/approve':
            if principal['role'] != 'admin': raise Error('ADMIN_REQUIRED', 'Worker caps require operator approval', 403)
            self.state.approve_worker(actor, **body)
            return 200, {'state': 'approved'}
        if method == 'POST' and path in {'/v1/claim', '/v1/heartbeat', '/v1/finish', '/v1/logs'}:
            if principal['role'] != 'worker': raise Error('WORKER_REQUIRED', 'Dedicated worker identity required', 403)
            worker = principal['worker']
            if path == '/v1/claim': return 200, {'assignment': self.state.claim(worker)}
            result = self.pipeline(principal, body['pipeline'])
            if path == '/v1/heartbeat':
                return 200, self.state.heartbeat(worker, body['pipeline'], body['task'], body['lease'])
            if path == '/v1/logs':
                return 200, self.state.append_log(worker,body['pipeline'],body['task'],body['lease'],body['position'],base64.b64decode(body['data_base64'],validate=True))
            owner = self.project(principal, result['project'])
            self.content_reference(owner, body['logs'])
            cache_artifact = body.get('cache_artifact')
            cache_size = 0
            if body['exit_code'] == 0:
                self.content_reference(owner, body['artifact'])
                if cache_artifact:
                    row = self.content_reference(owner, cache_artifact)
                    cache_size = json.loads(row['metadata'])['size']
                from .light import check_result
                check_result(self,result,body['task'],body['artifact'])
            return 200, self.state.finish(worker, body['pipeline'], body['task'], body['lease'],
                    exit_code=body['exit_code'], artifact=body['artifact'], logs=body['logs'],
                    attestation=body.get('attestation'), cache_artifact=cache_artifact, cache_size=cache_size)
        if path.startswith('/v1/cache/'):
            project = query.get('project', [None])[0]
            owner = self.project(principal, project)
            if method == 'GET' and path == '/v1/cache/lookup':
                key = query.get('key', [None])[0]
                if not key: raise Error('INVALID_CACHE_KEY', 'Cache key query param required')
                entry = self.state.cache_get(project, key)
                return 200, {'hit': entry is not None, 'cache': entry}
            if method == 'POST' and path == '/v1/cache/store':
                key = body.get('key')
                artifact = body.get('artifact')
                if not key or not artifact: raise Error('INVALID_CACHE_STORE', 'Key and artifact required')
                row = self.content_reference(owner, artifact)
                size = json.loads(row['metadata'])['size']
                return 200, self.state.cache_put(project, key, artifact, size)
            if method == 'GET' and path == '/v1/cache/list':
                limit = int(query.get('limit', ['100'])[0])
                return 200, {'caches': self.state.cache_list(project, limit)}
            if method == 'POST' and path == '/v1/cache/prune':
                max_bytes = body.get('max_bytes', 64*1024*1024)
                max_age = body.get('max_age', 86400*30)
                return 200, self.state.cache_prune(project, max_bytes, max_age)
        if path.startswith('/v1/objects/'):
            project = query.get('project', [None])[0]
            owner = self.project(principal, project)
            if method == 'POST' and path == '/v1/objects/begin':
                return 200, self.fabric.begin(owner, body['upload'], body['size'], body['digest'], body.get('mime', 'application/octet-stream'))
            if method == 'POST' and path == '/v1/objects/finish':
                result = self.fabric.finish(owner, body['upload'])
                return 200, {**result, 'reference': {'object': result['id'], 'digest': result['digest']}}
            parts = path.split('/')
            if method == 'PUT' and len(parts) == 6 and parts[4] == 'chunks':
                return 200, self.fabric.put(owner, parts[3], int(parts[5]), body)
            if method == 'GET' and len(parts) == 4:
                with self.fabric.lock: info = self.fabric.object_info(owner, parts[3])
                return 200, {'id':info['id'], 'reference':info['reference'], 'metadata':json.loads(info['metadata'])}
            if method == 'GET' and len(parts) == 6 and parts[4] == 'chunks':
                data = self.fabric.read_chunk(owner, parts[3], int(parts[5]))
                return 200, {'data_base64': base64.b64encode(data).decode()}
        raise Error('NOT_FOUND', 'Unknown OpenCI operation', 404)


def handler(controller):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *args):
            pass

        def send(self, status, value):
            raw = json.dumps(value, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(raw)
            self.close_connection = True

        def process(self):
            try:
                # API credentials are never accepted from URLs, cookies or bodies.
                origin=self.headers.get('Origin')
                settings=strict_json(secure_read(controller.config,65536),65536)
                approved_origins=set(settings.get('public_origins',[]))
                if settings.get('public_origin'):approved_origins.add(settings['public_origin'])
                if origin and origin not in approved_origins:
                    raise Error('ORIGIN_REJECTED','Explicit same-origin application required',403)
                if self.headers.get('Sec-Fetch-Site')=='cross-site':raise Error('ORIGIN_REJECTED','Cross-site access rejected',403)
                url = urlsplit(self.path)
                body = None
                if self.command=='GET' and url.path in {'/','/index.html','/app.js','/style.css','/light.js','/light-worker.js'} and not url.query:
                    name='index.html' if url.path in {'/','/index.html'} else url.path[1:]
                    kind={'index.html':'text/html; charset=utf-8','app.js':'text/javascript; charset=utf-8','style.css':'text/css; charset=utf-8','light.js':'text/javascript; charset=utf-8','light-worker.js':'text/javascript; charset=utf-8'}[name]
                    from importlib.resources import files
                    raw=files('openci').joinpath('web',name).read_bytes()
                    self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'");self.send_header('Connection','close');self.end_headers();self.wfile.write(raw);self.close_connection=True;return
                if self.command=='GET' and url.path=='/v1/status':
                    from ziokt.build_info import snapshot
                    self.send(200,{'schema':'openci.controller-status.v1','build':snapshot(),'native_rewards_enabled':False,'light_compile_configured':'light_compile' in settings});return
                if self.command=='GET' and url.path=='/v1/light/config':
                    from .light import settings
                    self.send(200,settings(controller)[1]);return
                if self.command=='GET' and url.path.startswith('/compiler/'):
                    from .light import asset
                    raw,kind=asset(controller,url.path[len('/compiler/'):])
                    self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');self.send_header('Connection','close');self.end_headers();self.wfile.write(raw);self.close_connection=True;return
                if self.command in {'POST', 'PUT'}:
                    if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                        raise Error('CONTENT_LENGTH_REQUIRED', 'One explicit body size required', 411)
                    limit = 16384 if self.command == 'PUT' else 1024*1024
                    size = int(self.headers.get('Content-Length', '-1'))
                    if not 0 <= size <= limit: raise Error('BODY_LIMIT', 'Request body exceeds budget', 413)
                    raw = self.rfile.read(size)
                    if len(raw) != size: raise Error('BODY_TRUNCATED', 'Incomplete request body')
                    body = raw if self.command == 'PUT' else strict_json(raw, limit)
                    if self.command == 'POST' and not isinstance(body, dict): raise Error('INVALID_BODY', 'Object body required')
                if self.command=='POST' and url.path.startswith('/v1/webhooks/github/'):
                    from .git_source import webhook
                    result=webhook(controller,url.path.split('/')[-1],raw,self.headers)
                    self.send(202,result);return
                if self.command=='POST' and url.path=='/v1/enrollments/redeem':
                    with controller.enrollment_lock:
                        now=time.monotonic()
                        while controller.enrollment_attempts and now-controller.enrollment_attempts[0]>=60:controller.enrollment_attempts.popleft()
                        if len(controller.enrollment_attempts)>=60:raise Error('ENROLLMENT_RATE','Enrollment retry budget exceeded',429)
                        controller.enrollment_attempts.append(now)
                    from .enrollment import redeem
                    self.send(200,redeem(controller.state,controller.enrollment_secret,body));return
                actor, principal = controller.authenticate(self.headers.get('Authorization'))
                status, result = controller.dispatch(self.command, url.path, parse_qs(url.query, max_num_fields=16), body, actor, principal)
                self.send(status, result)
            except Error as error:
                self.send(error.status, {'error': {'code': error.code, 'message': str(error), 'retryable': error.status in (429, 503)}})
            except PermissionError:
                self.send(403, {'error': {'code': 'OBJECT_FORBIDDEN', 'message': 'Object not accessible in this project', 'retryable': False}})
            except (ValueError, TypeError, KeyError, ProtocolError) as error:
                self.send(400, {'error': {'code': 'INVALID_REQUEST', 'message': str(error)[:256], 'retryable': False}})
            except Exception:
                self.send(500, {'error': {'code': 'CONTROLLER_ERROR', 'message': 'Controller operation failed; no success confirmation', 'retryable': True}})

        do_GET = process
        do_POST = process
        do_PUT = process
    return Handler


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, *args, **kwargs):
        if args and ':' in args[0][0]:self.address_family=socket.AF_INET6
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

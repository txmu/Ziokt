"""Independent OpenCI Controller, Runner and authenticated client commands."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from ziokt.protocol import secure_read, strict_json
from .client import Client
from .controller import Controller, Server, handler
from .state import Error, identifier


def private_write(path, value, *, replace=False):
    path=Path(path)
    if path.is_symlink():raise Error('UNSAFE_CONFIG','Config symlink rejected')
    raw=value if isinstance(value,bytes) else (json.dumps(value,indent=2)+'\n').encode()
    if not replace:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'wb') as output:output.write(raw);output.flush();os.fsync(output.fileno())
    else:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.openci-',delete=False) as output:
            temporary=Path(output.name);output.write(raw);output.flush();os.fsync(output.fileno())
        try:temporary.chmod(0o600);os.replace(temporary,path)
        finally:temporary.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(prog='openci')
    parser.add_argument('--root',type=Path,default=Path.home()/'.local/share/openci')
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('init')
    sub.add_parser('git-tick')
    p=sub.add_parser('git-configure');p.add_argument('--project',required=True);p.add_argument('--repository',type=Path,required=True);p.add_argument('--ref',default='refs/heads/main');p.add_argument('--template',type=Path,required=True);p.add_argument('--interval',type=int);p.add_argument('--remote-url')
    p=sub.add_parser('release-configure');p.add_argument('--native-source',type=Path,required=True)
    p=sub.add_parser('release-install');p.add_argument('release');p.add_argument('--destination',type=Path,required=True);p.add_argument('--activate',action='store_true')
    p=sub.add_parser('serve');p.add_argument('--port',type=int,default=8768)
    p=sub.add_parser('principal-add');p.add_argument('name');p.add_argument('--role',choices=['submit','worker'],required=True);p.add_argument('--project',action='append',required=True);p.add_argument('--worker')
    for name in ['upload','submit','inspect','cancel','retry','worker-approve','worker-disable','worker-signing-key','worker-build-profile','rebuild','runner','git-trigger','release-publish']:
        p=sub.add_parser(name);p.add_argument('--server',default='http://127.0.0.1:8768');p.add_argument('--token-file',type=Path)
        if name=='git-trigger':p.add_argument('--project',required=True);p.add_argument('--commit',required=True);p.add_argument('--delivery',required=True)
        if name=='release-publish':p.add_argument('pipeline');p.add_argument('task');p.add_argument('--name',required=True);p.add_argument('--version',required=True)
        if name=='upload':p.add_argument('--project',required=True);p.add_argument('file',type=Path)
        if name=='submit':p.add_argument('file',type=Path)
        if name in ('inspect','cancel','retry'):p.add_argument('pipeline')
        if name=='retry':p.add_argument('task')
        if name=='worker-disable':p.add_argument('worker')
        if name=='worker-approve':p.add_argument('file',type=Path)
        if name=='worker-signing-key':p.add_argument('file',type=Path)
        if name=='worker-build-profile':p.add_argument('file',type=Path)
        if name=='rebuild':p.add_argument('pipeline');p.add_argument('task');p.add_argument('--nonce',required=True);p.add_argument('--minimum',type=int,default=2)
        if name=='runner':p.add_argument('--signing-key-file',type=Path);p.add_argument('--image',action='append',required=True);p.add_argument('--once',action='store_true')
    args=parser.parse_args();root=args.root.resolve()
    if args.action=='init':
        root.mkdir(mode=0o700,parents=True,exist_ok=True)
        token=secrets.token_urlsafe(32)
        private_write(root/'owner.token',(token+'\n').encode())
        private_write(root/'controller.json',{'schema':'openci.controller.v1','principals':{'owner':{'role':'admin','projects':[],'token_sha256':hashlib.sha256(token.encode()).hexdigest()}}})
        print(json.dumps({'state':'initialized','config':str(root/'controller.json'),'token_file':str(root/'owner.token')}));return
    if args.action=='git-configure':
        from .git_source import resolve
        identifier(args.project)
        repository=args.repository.resolve()
        if not args.remote_url:resolve(repository,args.ref)
        if args.interval is not None and not 60<=args.interval<=2592000:parser.error('interval must be 60..2592000 seconds')
        template=strict_json(args.template.read_bytes(),65536)
        config=strict_json(secure_read(root/'controller.json',65536),65536)
        key=root/('git-'+args.project+'.key')
        if not key.exists():private_write(key,secrets.token_urlsafe(32).encode())
        value={'repository':str(repository),'ref':args.ref,'template':template,'webhook_key':str(key)}
        if args.interval is not None:value['interval_seconds']=args.interval
        if args.remote_url:
            from .git_source import refresh
            value['remote_url']=args.remote_url
            refresh(value)
        config.setdefault('git_projects',{})[args.project]=value
        private_write(root/'controller.json',config,replace=True)
        print(json.dumps({'state':'git_configured','project':args.project,'webhook_key_file':str(key),'mirror_fetch_automatic':bool(args.remote_url)}));return
    if args.action=='git-tick':
        from .git_source import tick
        controller=Controller(root,root/'controller.json')
        try:print(json.dumps(tick(controller)))
        finally:controller.close()
        return
    if args.action=='release-configure':
        from .release import configure
        print(json.dumps(configure(root,args.native_source)));return
    if args.action=='release-install':
        from .release import ReleaseService
        controller=Controller(root,root/'controller.json')
        try:print(json.dumps(ReleaseService(controller).install(args.release,args.destination,activate=args.activate)))
        finally:controller.close()
        return
    if args.action=='principal-add':
        identifier(args.name)
        if args.role=='worker' and not args.worker:parser.error('--worker required for worker role')
        if args.worker:identifier(args.worker)
        for project in args.project:identifier(project)
        config=strict_json(secure_read(root/'controller.json',65536),65536)
        if args.name in config['principals']:raise Error('PRINCIPAL_EXISTS','Principal already exists')
        token=secrets.token_urlsafe(32);destination=root/(args.name+'.token')
        private_write(destination,(token+'\n').encode())
        config['principals'][args.name]={'role':args.role,'projects':args.project,'token_sha256':hashlib.sha256(token.encode()).hexdigest()}
        if args.worker:config['principals'][args.name]['worker']=args.worker
        private_write(root/'controller.json',config,replace=True)
        print(json.dumps({'state':'principal_created','token_file':str(destination)}));return
    if args.action=='serve':
        if not 1<=args.port<=65535:parser.error('invalid port')
        controller=Controller(root,root/'controller.json');server=Server(('127.0.0.1',args.port),handler(controller))
        stop=threading.Event()
        def schedules():
            from .git_source import tick
            while not stop.wait(5):
                try:
                    result=tick(controller)
                    if result['schedule_results']:print(json.dumps(result),flush=True)
                except Exception:print(json.dumps({'state':'scheduler_failed','retryable':True}),flush=True)
        scheduler=threading.Thread(target=schedules,daemon=True);scheduler.start()
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:stop.set();scheduler.join(timeout=45);server.server_close();controller.close()
        return
    token=secure_read(args.token_file or root/'owner.token',4096).decode().strip()
    client=Client(args.server,token)
    if args.action=='git-trigger':result=client.request('POST','/v1/git/trigger',{'project':args.project,'commit':args.commit,'delivery':args.delivery})
    elif args.action=='release-publish':result=client.request('POST','/v1/releases',{'pipeline':args.pipeline,'task':args.task,'name':args.name,'version':args.version})
    elif args.action=='upload':result=client.upload(args.project,args.file)
    elif args.action=='submit':result=client.request('POST','/v1/pipelines',strict_json(args.file.read_bytes(),1024*1024))
    elif args.action=='inspect':result=client.request('GET','/v1/pipelines/'+args.pipeline)
    elif args.action=='cancel':result=client.request('POST','/v1/cancel',{'pipeline':args.pipeline})
    elif args.action=='retry':result=client.request('POST','/v1/retry',{'pipeline':args.pipeline,'task':args.task})
    elif args.action=='worker-disable':result=client.request('POST','/v1/workers/disable',{'worker':args.worker})
    elif args.action=='worker-approve':result=client.request('POST','/v1/workers/approve',strict_json(args.file.read_bytes(),65536))
    elif args.action=='worker-signing-key':result=client.request('POST','/v1/workers/signing-key',strict_json(args.file.read_bytes(),65536))
    elif args.action=='worker-build-profile':result=client.request('POST','/v1/workers/build-profile',strict_json(args.file.read_bytes(),65536))
    elif args.action=='rebuild':result=client.request('POST','/v1/rebuilds',{'pipeline':args.pipeline,'task':args.task,'nonce':args.nonce,'minimum':args.minimum})
    elif args.action=='runner':
        import fcntl
        from .runner import Runner
        area=root/'runner';area.mkdir(mode=0o700,exist_ok=True)
        fd=os.open(area/'runner.lock',os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            runner=Runner(client,area,args.image,signing_key=args.signing_key_file);runner.recover()
            while True:
                result=runner.run_once();print(json.dumps(result),flush=True)
                if args.once:return
                if result['state']=='idle':time.sleep(5)
    else:parser.error('unsupported operation')
    print(json.dumps(result,indent=2))

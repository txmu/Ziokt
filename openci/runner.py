"""OCI Runner. No host execution fallback; source scripts run only in a container.

Images must be operator-pinned and preloaded. Source and logs use native Content
Fabric references. A lost lease kills the container; no stale result is accepted.
"""
import base64
import hashlib
import io
import json
import os
import re
from pathlib import Path, PurePosixPath
import select
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
from .state import Error, IMAGE

MAX_SOURCE = 64*1024*1024
MAX_LOG = 16*1024*1024
MAX_OUTPUT = 80*1024*1024


def unpack_source(archive, destination):
    destination = Path(destination); destination.mkdir()
    total, count, names = 0, 0, set()
    with tarfile.open(archive, 'r:*') as source:
        for entry in source:
            path = PurePosixPath(entry.name)
            if path.is_absolute() or '..' in path.parts or '\\' in entry.name or len(entry.name)>4096 or entry.name in names:
                raise Error('SOURCE_ARCHIVE', 'Unsafe or duplicate archive member')
            names.add(entry.name);count += 1;total += entry.size
            if count>4096 or total>MAX_SOURCE or entry.size<0 or not (entry.isfile() or entry.isdir()):
                raise Error('SOURCE_ARCHIVE', 'Unsupported archive type or source budget')
            target = destination.joinpath(*path.parts)
            if entry.isdir(): target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                with source.extractfile(entry) as payload, target.open('xb') as output:
                    shutil.copyfileobj(payload,output,65536)
                target.chmod(0o555 if entry.mode & 0o111 else 0o444)
    for path in sorted(destination.rglob('*'),reverse=True):
        if path.is_dir(): path.chmod(0o555)
    destination.chmod(0o555)


def canonical_outputs(archive, output, required=()):
    # Output is an archive of untrusted bytes, not an installation request.
    seen, total, regular = set(), 0, set()
    with tarfile.open(archive,'r:') as source, tarfile.open(output,'w',format=tarfile.PAX_FORMAT) as target:
        entries = []
        for member in source:
            entries.append(member)
            if len(entries)>4096: raise Error('ARTIFACT_LIMIT','Too many output members')
        for entry in sorted(entries,key=lambda item:item.name):
            path = PurePosixPath(entry.name)
            if path.is_absolute() or '..' in path.parts or '\\' in entry.name or entry.name in seen or not (entry.isfile() or entry.isdir()):
                raise Error('ARTIFACT_ARCHIVE','Output contains unsafe member')
            seen.add(entry.name); total += entry.size
            if entry.isfile():regular.add(str(path))
            if total>64*1024*1024 or entry.size<0: raise Error('ARTIFACT_LIMIT','Output budget exceeded')
            entry.uid=entry.gid=entry.mtime=0;entry.uname=entry.gname='';entry.pax_headers={}
            entry.mode=0o755 if entry.isdir() or entry.mode & 0o111 else 0o644
            if entry.isfile():
                with source.extractfile(entry) as payload:target.addfile(entry,payload)
            else:target.addfile(entry)
        if not set(required)<=regular:raise Error('OUTPUT_MISSING','Task did not produce every declared output file',409)


class Runner:
    def __init__(self, client, root, images, runtime='docker',signing_key=None):
        self.client,self.root,self.images,self.runtime=client,Path(root),set(images),runtime
        if not self.images or any(not IMAGE.fullmatch(image) for image in self.images): raise Error('IMAGE_POLICY','Pinned image allowlist required')
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.root.is_symlink(): raise Error('UNSAFE_STATE','Runner root cannot be a symlink')
        self.signing_key=Path(signing_key) if signing_key else None
        self.assignment=None;self.last_heartbeat=0
        self.client.tick=self.tick

    def tick(self):
        if self.assignment and time.monotonic()-self.last_heartbeat>=15:
            self.last_heartbeat=time.monotonic()
            value=self.assignment
            self.client.request('POST','/v1/heartbeat',{'pipeline':value['pipeline'],'task':value['task']['id'],'lease':value['lease']})

    def command(self,*argv,**kwargs):
        return subprocess.run([self.runtime,*map(str,argv)],check=True,timeout=30,**kwargs)

    def collect(self, name, directory, paths, output):
        """Bound untrusted container archives before parsing or uploading them."""
        with Path(output).open('wb') as archive:
            copied=subprocess.Popen([self.runtime,'exec',name,'/bin/tar','-C',directory,'-cf','-','--',*paths],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            count=0;started=time.monotonic()
            try:
                while True:
                    self.tick()
                    if time.monotonic()-started>60:raise Error('ARTIFACT_TIMEOUT','Archive collection deadline exceeded')
                    ready,_,_=select.select([copied.stdout],[],[],.25)
                    if not ready:continue
                    data=os.read(copied.stdout.fileno(),65536)
                    if not data:break
                    count+=len(data)
                    if count>MAX_OUTPUT:raise Error('ARTIFACT_LIMIT','Container archive exceeds budget')
                    archive.write(data)
                if copied.wait(timeout=10)!=0:raise Error('ARTIFACT_COPY','Could not collect container archive')
            finally:
                if copied.poll() is None:copied.kill();copied.wait(timeout=10)
                copied.stdout.close()

    def restore_cache(self, name, area, assignment, cache):
        archive=area/'cache-in.tar'
        self.client.download(assignment['project'],cache['reference'],archive,MAX_OUTPUT)
        restored=area/'cache-restored'
        unpack_source(archive,restored)
        # Versioned cache namespaces avoid collisions between /cache and /work.
        for namespace,destination in [('cache','/cache'),('work','/work')]:
            tree=restored/namespace
            if not tree.is_dir():continue
            payload=area/(namespace+'-restore.tar')
            def writable(member):
                member.mode |= 0o200
                return member
            with tarfile.open(payload,'w') as output:
                output.add(tree,arcname='.',filter=writable)
            with payload.open('rb') as source:
                self.command('exec','-i',name,'/bin/tar','--no-same-owner','--no-same-permissions','--no-overwrite-dir','-C',destination,'-xf','-',stdin=source,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    def save_cache(self, name, area, assignment, cache):
        directory=area/'cache-save';directory.mkdir()
        paths=cache.get('paths') or []
        for namespace,source,selected in [('cache','/cache',['.']),('work','/work',paths)]:
            if not selected:continue
            archive=area/(namespace+'-raw.tar')
            self.collect(name,source,selected,archive)
            unpack_source(archive,directory/namespace)
        files=[p for p in directory.rglob('*') if p.is_file()]
        if not files:return None
        archive=area/'cache-out.tar'
        with tarfile.open(archive,'w') as output:
            for path in sorted(directory.iterdir()):output.add(path,arcname=path.name)
        if archive.stat().st_size>MAX_OUTPUT:raise Error('ARTIFACT_LIMIT','Combined cache exceeds budget')
        return self.client.upload(assignment['project'],archive)

    def recover(self):
        # Remove only containers labelled by this private runner state directory.
        label='openci.runner='+hashlib.sha256(str(self.root.resolve()).encode()).hexdigest()
        result=self.command('ps','-aq','--filter','label='+label,stdout=subprocess.PIPE,text=True)
        containers=result.stdout.split()
        if len(containers)>64 or any(not re.fullmatch('[a-f0-9]{12,64}',cid) for cid in containers):
            raise Error('RUNTIME_STATE','Unexpected orphan container listing')
        for cid in containers:self.command('rm','--force',cid,stdout=subprocess.DEVNULL)
        from ziokt.protocol import secure_read, strict_json
        journals=sorted(self.root.glob('receipt-*.json'))
        if len(journals)>1024:raise Error('RECEIPT_LIMIT','Operator must archive old receipt recovery records')
        for journal in journals:
            receipt=strict_json(secure_read(journal,65536),65536)
            try:self.client.request('POST','/v1/finish',receipt)
            except Error as error:
                if error.code not in ('LEASE_REJECTED','LEASE_EXPIRED','RESULT_CONFLICT'):raise
                journal.rename(journal.with_suffix('.rejected'))
            else:journal.unlink()

    def run_once(self):
        # Only advertise pinned images which the local OCI engine can inspect.
        # This is liveness, not attestation: eligibility still needs an operator profile.
        available=[]
        for image in sorted(self.images):
            try:self.command('image','inspect',image,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:continue
            available.append(image)
        if available:self.client.request('POST','/v1/workers/presence',{'images':available})
        assignment=self.client.request('POST','/v1/claim',{})['assignment']
        if assignment is None:return {'state':'idle'}
        self.assignment=assignment;self.last_heartbeat=time.monotonic()
        name='openci-'+uuid.uuid4().hex
        try:
            with tempfile.TemporaryDirectory(prefix='attempt-',dir=self.root) as temporary:
                area=Path(temporary); logs=area/'build.log';logs.touch(mode=0o600)
                artifact=None;cache_artifact=None;exit_code=125
                try:
                    task=assignment['task'];image=task['image']
                    if image not in self.images:raise Error('IMAGE_NOT_APPROVED','Image is not in the operator allowlist')
                    self.client.download(assignment['project'],assignment['source'],area/'source.tar',MAX_SOURCE)
                    unpack_source(area/'source.tar',area/'source')
                    cache_cfg=assignment.get('cache')
                    cache_mode=cache_cfg.get('mode','read-write') if cache_cfg else 'read-write'
                    can_restore=cache_mode in ('read-write','read-only')
                    result=self.command('image','inspect',image,'--format','{{.Architecture}}',stdout=subprocess.PIPE,text=True)
                    expected={'x86_64':'amd64','aarch64':'arm64'}[task['arch']]
                    if result.stdout.strip()!=expected:raise Error('IMAGE_ARCH','Pinned image architecture does not match worker requirement')
                    self.command('create','--name',name,'--label','openci.runner='+hashlib.sha256(str(self.root.resolve()).encode()).hexdigest(),'--pull=never','--network=none','--read-only',
                        '--user','65532:65532','--cap-drop=ALL','--security-opt','no-new-privileges',
                        '--pids-limit','128','--memory',str(task['memory_mb'])+'m','--memory-swap',str(task['memory_mb'])+'m',
                        '--cpus',str(task['cpu']),'--ulimit','nofile=1024:1024','--ulimit','fsize=67108864:67108864',
                        '--tmpfs','/tmp:rw,nosuid,nodev,size=16777216,mode=1777',
                        '--tmpfs','/work:rw,nosuid,nodev,size=134217728,mode=1777',
                        '--tmpfs','/out:rw,nosuid,nodev,size=67108864,mode=1777',
                        '--tmpfs','/cache:rw,nosuid,nodev,size=67108864,mode=1777',
                        '--mount','type=bind,src='+str(area/'source')+',dst=/src,readonly',
                        '--workdir','/work',image,'/bin/sh','-c','exec sleep 10800',stdout=subprocess.DEVNULL)
                    self.command('start',name,stdout=subprocess.DEVNULL)
                    if can_restore and cache_cfg and cache_cfg.get('hit') and cache_cfg.get('reference'):
                        try:
                            self.restore_cache(name,area,assignment,cache_cfg)
                        except (Error,OSError,ValueError,tarfile.TarError,subprocess.SubprocessError) as error:
                            with logs.open('ab') as log:log.write(('OpenCI cache restore skipped: '+str(error)+'\n').encode()[:4096])
                    process=subprocess.Popen([self.runtime,'exec',name,*task['argv']],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                    started=time.monotonic();size=0;position=0;pending=bytearray();live=True
                    try:
                        with logs.open('ab',buffering=0) as log:
                            while True:
                                self.tick()
                                if time.monotonic()-started>task['timeout']:raise Error('TASK_TIMEOUT','Container task exceeded deadline')
                                ready,_,_=select.select([process.stdout],[],[],.25)
                                if ready:
                                    data=os.read(process.stdout.fileno(),16384)
                                    if not data:break
                                    size+=len(data)
                                    if size>MAX_LOG:raise Error('LOG_LIMIT','Task log limit exceeded')
                                    log.write(data);pending.extend(data)
                                if live and (len(pending)>=8192 or pending and not ready):
                                    chunk=bytes(pending[:16384]);del pending[:len(chunk)]
                                    try:self.client.request('POST','/v1/logs',{'pipeline':assignment['pipeline'],'task':task['id'],'lease':assignment['lease'],'position':position,'data_base64':base64.b64encode(chunk).decode()});position+=1
                                    except Error as error:
                                        if error.code!='LIVE_LOG_LIMIT':raise
                                        live=False;pending.clear()
                            if live and pending:
                                self.client.request('POST','/v1/logs',{'pipeline':assignment['pipeline'],'task':task['id'],'lease':assignment['lease'],'position':position,'data_base64':base64.b64encode(bytes(pending)).decode()})
                            exit_code=process.wait(timeout=10)
                            if exit_code<0:exit_code=128-exit_code
                    finally:
                        if process.poll() is None:
                            self.command('rm','--force',name,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                            process.kill();process.wait(timeout=10)
                        process.stdout.close()
                    if exit_code==0:
                        raw=area/'outputs.raw.tar'
                        self.collect(name,'/out',['.'],raw)
                        canonical_outputs(raw,area/'artifact.tar',task['outputs'])
                        from .artifacts import publish_outputs
                        artifact=publish_outputs(self.client,assignment['project'],area/'artifact.tar',task['outputs'],assignment['source'],task['image'])
                        can_save=cache_mode in ('read-write','write-only')
                        if can_save and cache_cfg and cache_cfg.get('key'):
                            try:cache_artifact=self.save_cache(name,area,assignment,cache_cfg)
                            except (Error,OSError,ValueError,tarfile.TarError,subprocess.SubprocessError) as error:
                                with logs.open('ab') as log:log.write(('OpenCI cache save skipped: '+str(error)+'\n').encode()[:4096])
                except (Error,OSError,ValueError,tarfile.TarError,subprocess.SubprocessError) as error:
                    exit_code=124 if isinstance(error,Error) and error.code=='TASK_TIMEOUT' else 125
                    with logs.open('ab') as log:log.write(('\nOpenCI Runner: '+type(error).__name__+': '+str(error)+'\n').encode()[:4096])
                log_reference=self.client.upload(assignment['project'],logs)
                receipt={'pipeline':assignment['pipeline'],'task':assignment['task']['id'],'lease':assignment['lease'],
                         'exit_code':exit_code,'artifact':artifact if exit_code==0 else None,'logs':log_reference}
                if cache_artifact is not None:receipt['cache_artifact']=cache_artifact
                if self.signing_key:
                    from ziokt.protocol import secure_read
                    from ziokt.security import sign
                    from .attestation import DOMAIN,statement
                    result_fields={key:receipt[key] for key in ('exit_code','artifact','logs')}
                    receipt['attestation']=sign(statement(assignment['worker'],assignment,result_fields),secure_read(self.signing_key,32),DOMAIN)
                journal=self.root/('receipt-'+assignment['pipeline']+'-'+assignment['task']['id']+'-'+str(assignment['attempt'])+'.json')
                fd=os.open(journal,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
                with os.fdopen(fd,'w') as output:output.write(json.dumps(receipt));output.flush();os.fsync(output.fileno())
                result=self.client.request('POST','/v1/finish',receipt)
                journal.unlink()
                return result
        finally:
            self.assignment=None
            try:self.command('rm','--force',name,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            except (OSError,subprocess.SubprocessError):pass

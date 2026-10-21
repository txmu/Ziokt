"""Native versioned file installation, activation and rollback; never execute files.

System dpkg/rpm operations remain the separate explicit Package.install API.
This installer supports data, firmware and VM programs in an owner-chosen root.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from ziokt.protocol import secure_read,strict_json
from ziokt.safefs import _private_dir
from ziokt.ufsdcpm import read_package,reference_manifest
from dcpm_core import get_package_id,get_version_id
from ufs_http_security import ConfinedFiles

ID=re.compile(r'[a-f0-9]{64}\Z')


class FileInstaller:
    def __init__(self,store,root):
        self.store=store;self.root=_private_dir(Path(root))

    @contextmanager
    def mutation(self,allow):
        if allow is not True:raise PermissionError('DCPM_FILE_INSTALL_REQUIRES_LOCAL_OWNER')
        import fcntl
        descriptor=os.open(self.root/'.install.lock',os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(descriptor,'w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            yield

    @staticmethod
    def identities(package,version):
        if not isinstance(package,str) or not ID.fullmatch(package) or not isinstance(version,str) or not ID.fullmatch(version):
            raise ValueError('DCPM_INSTALL_IDENTITY')

    def signed_manifest(self,blob):
        value=strict_json(blob,8*1024*1024,string_limit=8*1024*1024)
        signed=value.get('manifest',{}) if isinstance(value,dict) else {}
        public=signed.get('public_key')
        if public not in self.store.authorities:raise PermissionError('DCPM_UNTRUSTED_PUBLISHER')
        if signed.get('payload',{}).get('schema')=='ziokt.dcpm-package.v2':manifest=reference_manifest(blob,public)
        else:manifest,_=read_package(blob,public)
        return public,manifest

    def installed(self,package,version):
        self.identities(package,version)
        directory=self.root/package/'versions'/version
        for path in (self.root/package,self.root/package/'versions',directory):
            if path.is_symlink() or not path.is_dir():raise ValueError('DCPM_INSTALLED_PATH')
        blob=secure_read(directory/'package.zpkg',8*1024*1024)
        public,manifest=self.signed_manifest(blob)
        if get_package_id(manifest['name'],public)!=package or get_version_id(manifest['name'],public,manifest['version'])!=version:
            raise ValueError('DCPM_INSTALLED_IDENTITY')
        declared={entry['path'] for entry in manifest['files']}
        actual=set();count=0
        for path in (directory/'payload').rglob('*'):
            count+=1
            if count>4096 or path.is_symlink():raise ValueError('DCPM_INSTALLED_TREE_CHANGED')
            if path.is_file():actual.add(path.relative_to(directory/'payload').as_posix())
        if actual!=declared:raise ValueError('DCPM_INSTALLED_TREE_CHANGED')
        files=ConfinedFiles(directory/'payload')
        try:
            for entry in manifest['files']:
                expected=entry['sha256'].removeprefix('sha256:');full=hashlib.sha256();size=0
                with files.open(entry['path'].split('/')) as source:
                    while chunk:=source.read(65536):full.update(chunk);size+=len(chunk)
                if size!=entry['size'] or full.hexdigest()!=expected:raise ValueError('DCPM_INSTALLED_CONTENT_CHANGED')
        finally:files.close()
        return {'package_id':package,'version_id':version,'name':manifest['name'],'version':manifest['version'],
                'publisher':public,'manifest':manifest,'installed':True,'directory':str(directory/'payload'),
                'execution_authorized':False,'source_sha256':hashlib.sha256(blob).hexdigest()}

    def dependencies(self,manifest):
        required=set(manifest['dependencies'])
        if not required:return
        candidates=[path for path in self.root.iterdir() if ID.fullmatch(path.name)]
        if len(candidates)>4096:raise ValueError('DCPM_INSTALL_RETENTION_LIMIT')
        for path in candidates:
            try:current=self.active(path.name)
            except FileNotFoundError:continue
            required.discard(current['name'])
            if not required:return
        raise ValueError('DCPM_DEPENDENCY_NOT_INSTALLED:'+','.join(sorted(required)))

    @staticmethod
    def sync_directory(directory):
        if os.name=='posix':
            descriptor=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|getattr(os,'O_NOFOLLOW',0))
            try:os.fsync(descriptor)
            finally:os.close(descriptor)

    def install(self,package,version,*,allow=False):
        with self.mutation(allow):
            blob=self.store.blob(package,version)
            public,manifest=self.signed_manifest(blob)
            self.identities(package,version);self.dependencies(manifest)
            total=sum(entry['size'] for entry in manifest['files'])
            if shutil.disk_usage(self.root).free<total+1024*1024:raise OSError('DCPM_INSTALL_DISK_SPACE')
            base=_private_dir(self.root/package);versions=_private_dir(base/'versions');destination=versions/version
            if destination.exists():
                installed=self.installed(package,version)
                if installed['source_sha256']!=hashlib.sha256(blob).hexdigest():raise ValueError('DCPM_INSTALLED_VERSION_CONFLICT')
                return {**installed,'duplicate':True,'activated':self.is_active(package,version)}
            if len(list(versions.iterdir()))>=128:raise ValueError('DCPM_INSTALL_VERSION_LIMIT')
            stage=Path(tempfile.mkdtemp(prefix='.stage-',dir=versions))
            try:
                payload=_private_dir(stage/'payload')
                for path,size,expected,chunks in self.store.content_files(package,version):
                    # Signed paths were checked by the shared native package parser.
                    target=payload.joinpath(*path.split('/'));target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                    digest=hashlib.sha256();written=0
                    try:
                        with target.open('xb') as output:
                            os.chmod(target,0o600)
                            for chunk in chunks:
                                written+=len(chunk)
                                if written>size:raise ValueError('DCPM_INSTALL_SIZE')
                                digest.update(chunk);output.write(chunk)
                            output.flush();os.fsync(output.fileno())
                    finally:
                        if hasattr(chunks,'close'):chunks.close()
                    if written!=size or digest.hexdigest()!=expected:raise ValueError('DCPM_INSTALL_CONTENT_INTEGRITY')
                fd=os.open(stage/'package.zpkg',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as output:output.write(blob);output.flush();os.fsync(output.fileno())
                for directory in sorted((p for p in payload.rglob('*') if p.is_dir()),reverse=True):self.sync_directory(directory)
                self.sync_directory(payload);self.sync_directory(stage)
                os.rename(stage,destination);self.sync_directory(versions)
            except BaseException:
                shutil.rmtree(stage,ignore_errors=True)
                raise
            return {**self.installed(package,version),'duplicate':False,'activated':self.is_active(package,version)}

    def is_active(self,package,version):
        try:return self.active(package)['version_id']==version
        except FileNotFoundError:return False

    def active(self,package):
        if not isinstance(package,str) or not ID.fullmatch(package):raise ValueError('DCPM_INSTALL_IDENTITY')
        pointer=strict_json(secure_read(self.root/package/'active.json',16384),16384)
        if not isinstance(pointer,dict) or set(pointer)!={'schema','version_id','history'} or pointer['schema']!='dcpm.file-activation.v1' or not isinstance(pointer['history'],list) or len(pointer['history'])>128 or any(not isinstance(v,str) or not ID.fullmatch(v) for v in pointer['history']):
            raise ValueError('DCPM_ACTIVATION_STATE')
        return {**self.installed(package,pointer['version_id']),'activated':True,'history':pointer['history']}

    def activate(self,package,version,*,allow=False):
        with self.mutation(allow):return self._activate(package,version)

    def _activate(self,package,version):
        installed=self.installed(package,version);self.dependencies(installed['manifest'])
        base=self.root/package;pointer=base/'active.json'
        try:previous=self.active(package)
        except FileNotFoundError:previous=None
        history=[] if previous is None else list(dict.fromkeys([previous['version_id'],*previous['history']]))
        history=[old for old in history if old!=version][:128]
        value={'schema':'dcpm.file-activation.v1','version_id':version,'history':history}
        with tempfile.NamedTemporaryFile(dir=base,prefix='.active-',delete=False) as output:
            temporary=Path(output.name);output.write(json.dumps(value,sort_keys=True).encode());output.flush();os.fsync(output.fileno())
        try:temporary.chmod(0o600);os.replace(temporary,pointer);self.sync_directory(base)
        finally:temporary.unlink(missing_ok=True)
        return {**installed,'activated':True,'history':history,'execution_authorized':False}

    def rollback(self,package,*,allow=False):
        with self.mutation(allow):
            current=self.active(package)
            if not current['history']:raise ValueError('DCPM_NO_ROLLBACK_VERSION')
            return self._activate(package,current['history'][0])

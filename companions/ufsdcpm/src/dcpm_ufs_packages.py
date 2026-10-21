"""Persistent native UFS bridge for the existing Ziokt signed DCPM format."""
import base64
import hashlib
import io
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
from urllib.parse import urlsplit, urlencode
from urllib.request import build_opener, HTTPDigestAuthHandler, HTTPPasswordMgrWithDefaultRealm, HTTPSHandler, ProxyHandler
import ssl
import stat

from ziokt.protocol import secure_read
from ziokt.security import sign
from ziokt.ufsdcpm import read_package, verify_reference_package
from dcpm_core import get_package_id, get_version_id, Package
from ufs_http_security import ConfinedFiles
from dcpm_file_install import FileInstaller

MAX_PACKAGE = 8*1024*1024
ID = re.compile('[a-f0-9]{64}\\Z')


class PackageStore:
    def __init__(self, root, signing_key=None, trusted_publishers=None, max_bytes=100*1024**3, *, reference_store=None):
        if type(max_bytes) is not int or not 1<=max_bytes<=1024**4: raise ValueError('DCPM_STORAGE_BUDGET')
        self.max_bytes=max_bytes
        self.reference_store=reference_store
        self.root = Path(root).absolute()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink(): raise ValueError('DCPM_STORE_SYMLINK')
        if os.name!='nt' and self.root.stat().st_uid!=os.geteuid(): raise PermissionError('DCPM_STORE_OWNER')
        os.chmod(self.root,0o700)
        self.key_path = Path(signing_key or self.root/'publisher.key')
        self.key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.key_path.exists():
            fd = os.open(self.key_path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
            with os.fdopen(fd,'wb') as target:
                target.write(secrets.token_bytes(32)); target.flush(); os.fsync(target.fileno())
        self.private = secure_read(self.key_path,32)
        if len(self.private) != 32: raise ValueError('DCPM_SIGNING_KEY_LENGTH')
        self.public = sign({},self.private,'test')['public_key']
        if trusted_publishers is not None and (not isinstance(trusted_publishers,list) or len(trusted_publishers)>64 or
                any(not isinstance(k,str) or not ID.fullmatch(k) for k in trusted_publishers)):
            raise ValueError('DCPM_TRUSTED_PUBLISHER_LIST')
        self.authorities = set(trusted_publishers or []) | {self.public}
        if len(self.authorities)>64 or any(not isinstance(k,str) or not ID.fullmatch(k) for k in self.authorities):
            raise ValueError('DCPM_TRUSTED_PUBLISHER_REQUIRED')
        self.files = ConfinedFiles(self.root/'objects')
        path = self.root/'index.sqlite'
        if path.exists():
            info=path.lstat()
            if path.is_symlink() or not stat.S_ISREG(info.st_mode) or (os.name!='nt' and (info.st_uid!=os.geteuid() or info.st_mode & 0o077)):
                self.files.close(); raise ValueError('DCPM_PRIVATE_INDEX_REQUIRED')
        self.db = sqlite3.connect(path,timeout=5,check_same_thread=False)
        os.chmod(path,0o600)
        self.lock = threading.RLock()
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS packages(version_id TEXT PRIMARY KEY,package_id TEXT,name TEXT,version TEXT,publisher TEXT,digest TEXT,created INTEGER,size INTEGER NOT NULL); CREATE INDEX IF NOT EXISTS package_lookup ON packages(package_id,created);')
        if 'size' not in {row[1] for row in self.db.execute('PRAGMA table_info(packages)')}:
            with self.db:
                self.db.execute('ALTER TABLE packages ADD COLUMN size INTEGER NOT NULL DEFAULT 0')
                for version,digest in self.db.execute('SELECT version_id,digest FROM packages LIMIT 4096').fetchall():
                    size=self.files.info([digest]).st_size
                    self.db.execute('UPDATE packages SET size=? WHERE version_id=?',(size,version))
        self.db.execute('CREATE TABLE IF NOT EXISTS reference_pending(version_id TEXT PRIMARY KEY,package_id TEXT,name TEXT,version TEXT,publisher TEXT,digest TEXT,created INTEGER,size INTEGER,holder TEXT NOT NULL)')
        self.db.commit()
        if self.reference_store is not None:self.resume_pending()

    def close(self): self.db.close(); self.files.close()

    def validate(self, blob):
        if not isinstance(blob,bytes) or not 1<=len(blob)<=MAX_PACKAGE: raise ValueError('DCPM_PACKAGE_LIMIT')
        # Parse the bounded envelope to select only an explicitly trusted key;
        # read_package performs the actual publisher signature and content check.
        from ziokt.protocol import strict_json
        envelope = strict_json(blob, MAX_PACKAGE, string_limit=MAX_PACKAGE)
        signed = envelope.get('manifest') if isinstance(envelope,dict) else None
        public = signed.get('public_key') if isinstance(signed,dict) else None
        if not isinstance(public,str) or public not in self.authorities: raise PermissionError('DCPM_UNTRUSTED_PUBLISHER')
        if signed.get('payload',{}).get('schema')=='ziokt.dcpm-package.v2':
            if self.reference_store is None:raise PermissionError('DCPM_REFERENCE_STORE_REQUIRED')
            report=verify_reference_package(self.reference_store,blob,public)
            return public,report['manifest'],None
        manifest, files = read_package(blob, public)
        return public, manifest, files

    def admit(self, blob, *, expected_id=None, expected_version=None):
        public, manifest, files = self.validate(blob)
        package_id = get_package_id(manifest['name'],public)
        version_id = get_version_id(manifest['name'],public,manifest['version'])
        if expected_id is not None and expected_id not in {package_id,version_id} or expected_version is not None and expected_version != version_id:
            raise ValueError('DCPM_PACKAGE_IDENTITY_MISMATCH')
        if manifest['schema']=='ziokt.dcpm-package.v2':
            return self._admit_reference(blob,public,manifest,package_id,version_id)
        digest = hashlib.sha256(blob).hexdigest()
        import time
        with self.lock, self.db:
            self.db.execute('BEGIN IMMEDIATE')
            previous = self.db.execute('SELECT digest FROM packages WHERE version_id=?',(version_id,)).fetchone()
            if previous and previous[0] != digest: raise ValueError('DCPM_VERSION_CONFLICT')
            if self.db.execute('SELECT 1 FROM reference_pending WHERE version_id=?',(version_id,)).fetchone():raise ValueError('DCPM_VERSION_PENDING')
            if not previous and self.db.execute('SELECT (SELECT count(*) FROM packages)+(SELECT count(*) FROM reference_pending)').fetchone()[0]>=4096:
                raise ValueError('DCPM_PACKAGE_RETENTION_LIMIT')
            used=self.db.execute('SELECT (SELECT coalesce(sum(size),0) FROM packages)+(SELECT coalesce(sum(size),0) FROM reference_pending)').fetchone()[0]
            if not previous and used+len(blob)>self.max_bytes: raise ValueError('DCPM_STORAGE_BUDGET_EXHAUSTED')
            self.files.put([digest],io.BytesIO(blob),len(blob))
            self.db.execute('INSERT OR IGNORE INTO packages VALUES (?,?,?,?,?,?,?,?)',
                (version_id,package_id,manifest['name'],manifest['version'],public,digest,time.time_ns(),len(blob)))
        return {'package_id':package_id,'version_id':version_id,'publisher':public,'sha256':digest,
            'durably_stored':True,'replica_count':1,'chain_confirmed':False}

    def blob(self, package_id, version_id=None):
        for value in (package_id,version_id):
            if value is not None and (not isinstance(value,str) or not ID.fullmatch(value)): raise ValueError('DCPM_PACKAGE_ID')
        with self.lock:
            if version_id:
                row=self.db.execute('SELECT digest FROM packages WHERE package_id=? AND version_id=?',(package_id,version_id)).fetchone()
            else: row=self.db.execute('SELECT digest FROM packages WHERE package_id=? OR version_id=? ORDER BY created DESC,version_id LIMIT 1',(package_id,package_id)).fetchone()
            if not row: raise FileNotFoundError('DCPM_PACKAGE_UNAVAILABLE')
            with self.files.open([row[0]]) as source: blob=source.read(MAX_PACKAGE+1)
            if hashlib.sha256(blob).hexdigest()!=row[0]: raise ValueError('DCPM_STORED_DIGEST_CHANGED')
            public,manifest,_=self.validate(blob)
            expected=(get_package_id(manifest['name'],public),get_version_id(manifest['name'],public,manifest['version']))
            if package_id not in expected or version_id and version_id!=expected[1]: raise ValueError('DCPM_PACKAGE_IDENTITY_CHANGED')
            return blob

    def package(self, package_id, version_id=None):
        blob=self.blob(package_id,version_id)
        public, manifest, files=self.validate(blob)
        if files is None:
            if sum(entry['size'] for entry in manifest['files'])>8*1024*1024:raise ValueError('DCPM_STREAMING_INSTALL_REQUIRED')
            files={entry['path']:b''.join(self.reference_store.stream(entry['object'])) for entry in manifest['files']}
        package=Package(manifest['name'],manifest['version'],files,'dpkg',manifest['dependencies'])
        package.package_id=get_package_id(package.name,public)
        package.version_id=get_version_id(package.name,public,package.version)
        return package

    def list(self):
        with self.lock:
            return [dict(zip(('package_id','version_id','name','version','publisher','sha256'), row)) for row in
                self.db.execute('SELECT package_id,version_id,name,version,publisher,digest FROM packages ORDER BY created DESC LIMIT 128')]


    def _admit_reference(self,blob,public,manifest,package_id,version_id):
        import time
        digest=hashlib.sha256(blob).hexdigest()
        holder='sha256:'+hashlib.sha256(b'Ziokt/native-DCPM/reference-pin/v1\0'+str(self.root).encode()+blob).hexdigest()
        with self.lock,self.db:
            self.db.execute('BEGIN IMMEDIATE')
            previous=self.db.execute('SELECT digest FROM packages WHERE version_id=?',(version_id,)).fetchone()
            pending=self.db.execute('SELECT digest FROM reference_pending WHERE version_id=?',(version_id,)).fetchone()
            if (previous and previous[0]!=digest) or (pending and pending[0]!=digest):raise ValueError('DCPM_VERSION_CONFLICT')
            if not previous and not pending:
                count=self.db.execute('SELECT (SELECT count(*) FROM packages)+(SELECT count(*) FROM reference_pending)').fetchone()[0]
                used=self.db.execute('SELECT (SELECT coalesce(sum(size),0) FROM packages)+(SELECT coalesce(sum(size),0) FROM reference_pending)').fetchone()[0]
                if count>=4096 or used+len(blob)>self.max_bytes:raise ValueError('DCPM_PACKAGE_BUDGET')
                self.files.put([digest],io.BytesIO(blob),len(blob))
                self.db.execute('INSERT INTO reference_pending VALUES(?,?,?,?,?,?,?,?,?)',(version_id,package_id,manifest['name'],manifest['version'],public,digest,time.time_ns(),len(blob),holder))
        if previous:
            # Recheck/pin after an interrupted external retention operation.
            self.reference_store.pin(holder,[entry['object'] for entry in manifest['files']])
            return self._publication(package_id,version_id,public,digest)
        return self._resume_reference(version_id)

    @staticmethod
    def _publication(package_id,version_id,public,digest):
        return {'package_id':package_id,'version_id':version_id,'publisher':public,'sha256':digest,
                'durably_stored':True,'replica_count':1,'chain_confirmed':False,
                'package_schema':'ziokt.dcpm-package.v2','content_referenced':True,
                'installed':False,'activated':False}

    def _resume_reference(self,version_id):
        with self.lock:
            row=self.db.execute('SELECT * FROM reference_pending WHERE version_id=?',(version_id,)).fetchone()
            if not row:raise FileNotFoundError('DCPM_PENDING_UNAVAILABLE')
            version,package,name,label,public,digest,created,size,holder=row
            with self.files.open([digest]) as source:blob=source.read(MAX_PACKAGE+1)
            if hashlib.sha256(blob).hexdigest()!=digest:raise ValueError('DCPM_PENDING_INTEGRITY')
            actual,manifest,_=self.validate(blob)
            if actual!=public or get_package_id(manifest['name'],public)!=package or get_version_id(manifest['name'],public,manifest['version'])!=version:raise ValueError('DCPM_PENDING_IDENTITY')
            # This pin is committed before the publication row. The durable
            # pending record makes a crash in between safely resumable.
            self.reference_store.pin(holder,[entry['object'] for entry in manifest['files']])
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                previous=self.db.execute('SELECT digest FROM packages WHERE version_id=?',(version,)).fetchone()
                if previous and previous[0]!=digest:raise ValueError('DCPM_VERSION_CONFLICT')
                self.db.execute('INSERT OR IGNORE INTO packages VALUES(?,?,?,?,?,?,?,?)',(version,package,name,label,public,digest,created,size))
                self.db.execute('DELETE FROM reference_pending WHERE version_id=?',(version,))
            return self._publication(package,version,public,digest)

    def resume_pending(self,limit=16):
        if self.reference_store is None:raise PermissionError('DCPM_REFERENCE_STORE_REQUIRED')
        if type(limit) is not int or not 1<=limit<=128:raise ValueError('DCPM_RECOVERY_LIMIT')
        rows=self.db.execute('SELECT version_id FROM reference_pending ORDER BY created LIMIT ?',(limit,)).fetchall()
        return [self._resume_reference(row[0]) for row in rows]

    def file_installer(self,root):
        return FileInstaller(self,root)

    def content_files(self,package_id,version_id=None):
        """Verified files as bounded streams; no untrusted install script execution."""
        blob=self.blob(package_id,version_id)
        public,manifest,files=self.validate(blob)
        if files is not None:
            for path,data in sorted(files.items()):yield path,len(data),hashlib.sha256(data).hexdigest(),iter([data])
        else:
            for entry in manifest['files']:
                yield entry['path'],entry['size'],entry['sha256'].removeprefix('sha256:'),self.reference_store.stream(entry['object'])


def fetch_http(source, package_id, version_id=None):
    """Only owner-configured sources; redirects are forbidden, TLS verified."""
    if os.environ.get('ZIOKT_AIRGAP','').lower() in {'1','true','yes'}:
        raise PermissionError('DCPM_AIRGAP_NETWORK_DENIED')
    from urllib.request import HTTPRedirectHandler
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*_): raise PermissionError('DCPM_SOURCE_REDIRECT_DENIED')
    if not isinstance(source,dict) or not {'url','username','password'}<=set(source): raise ValueError('DCPM_HTTP_SOURCE')
    url=source['url']; parsed=urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.scheme not in {'http','https'}:
        raise ValueError('DCPM_HTTP_SOURCE')
    if parsed.scheme=='http':
        import ipaddress
        try: local=ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError: local=False
        if not local: raise PermissionError('DCPM_TLS_SOURCE_REQUIRED')
    for value in (package_id,version_id):
        if value is not None and (not isinstance(value,str) or not ID.fullmatch(value)): raise ValueError('DCPM_PACKAGE_ID')
    class SHA256DigestAuthHandler(HTTPDigestAuthHandler):
        def get_algorithm_impls(self, algorithm):
            if algorithm != 'SHA-256': raise ValueError('DCPM_DIGEST_DOWNGRADE_DENIED')
            digest=lambda value:hashlib.sha256(value.encode()).hexdigest()
            return digest, lambda secret,data:digest(secret+':'+data)
    manager=HTTPPasswordMgrWithDefaultRealm(); manager.add_password(None,url,source['username'],source['password'])
    context=ssl.create_default_context(cafile=source.get('ca'))
    opener=build_opener(ProxyHandler({}),NoRedirect(),SHA256DigestAuthHandler(manager),HTTPSHandler(context=context))
    query={'package_id':package_id}
    if version_id: query['version_id']=version_id
    target=url.rstrip('/')+'/api/dcpm/package?'+urlencode(query)
    with opener.open(target,timeout=15) as response:
        blob=response.read(MAX_PACKAGE+1)
    if len(blob)>MAX_PACKAGE: raise ValueError('DCPM_PACKAGE_LIMIT')
    return blob

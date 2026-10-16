"""UFS HTTP boundaries: expiring Digest challenges and descriptor-confined I/O."""
import hashlib
import hmac
import os
import re
import secrets
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlsplit


class DigestAuthority:
    def __init__(self, lifetime=300, maximum=4096):
        self.secret = secrets.token_bytes(32)
        self.lifetime, self.maximum = lifetime, maximum
        self.used = {}
        self.lock = threading.Lock()

    def challenge(self):
        value = str(int(time.time()))+':'+secrets.token_hex(16)
        return value+':'+hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def admit(self, nonce, username, cnonce, count):
        try:
            stamp, salt, signature = nonce.split(':')
            if not re.fullmatch('[0-9]{1,12}', stamp) or not re.fullmatch('[a-f0-9]{32}', salt): return False
            if not re.fullmatch('[a-f0-9]{64}', signature): return False
            value = stamp+':'+salt
            if not hmac.compare_digest(signature, hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()): return False
            now = int(time.time())
            if not 0 <= now-int(stamp) <= self.lifetime: return False
        except (ValueError, TypeError): return False
        with self.lock:
            self.used = {k:v for k,v in self.used.items() if v[1] >= now}
            # Scope to nonce and user, rather than cnonce: changing a cnonce
            # cannot grow the replay table without issuing another challenge.
            key = (nonce, username)
            previous = self.used.get(key)
            if previous and count <= previous[0]: return False
            if not previous and len(self.used) >= self.maximum: return False
            self.used[key] = (count, int(stamp)+self.lifetime)
        return True


def digest_fields(header):
    if not isinstance(header, str) or not header.startswith('Digest ') or len(header) > 8192:
        raise ValueError('UFS_DIGEST_REQUIRED')
    text, fields = header[7:], {}
    pattern = re.compile(r'\s*([A-Za-z][A-Za-z0-9_-]*)\s*=\s*(?:"([^"\\\r\n]*)"|([^,\s]+))\s*(?:,|$)')
    offset = 0
    while offset < len(text):
        match = pattern.match(text, offset)
        if not match or match.group(1) in fields: raise ValueError('UFS_INVALID_DIGEST')
        fields[match.group(1)] = match.group(2) if match.group(2) is not None else match.group(3)
        offset = match.end()
    required = {'username', 'realm', 'nonce', 'uri', 'response', 'qop', 'nc', 'cnonce'}
    if not required <= set(fields) or set(fields)-required-{'algorithm', 'opaque'}:
        raise ValueError('UFS_INVALID_DIGEST_FIELDS')
    if (fields['qop'] != 'auth' or fields.get('algorithm', 'SHA-256') != 'SHA-256' or
            not re.fullmatch('[a-fA-F0-9]{8}', fields['nc']) or int(fields['nc'],16) == 0 or
            not re.fullmatch('[a-fA-F0-9]{64}', fields['response']) or not 8 <= len(fields['cnonce']) <= 128):
        raise ValueError('UFS_INVALID_DIGEST_PROOF')
    return fields


class ConfinedFiles:
    """No-follow directory descriptors; never open an untrusted absolute path.

    Platforms lacking directory-relative opens fail closed, rather than falling
    back to a race-prone resolve/check/open sequence.
    """
    def __init__(self, root):
        if os.open not in os.supports_dir_fd or not hasattr(os, 'O_NOFOLLOW'):
            raise RuntimeError('UFS_SECURE_DIR_FD_UNAVAILABLE')
        self.root = Path(root).absolute()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.lock = threading.RLock()

    def close(self):
        if self.fd is not None:
            os.close(self.fd); self.fd = None

    def parts(self, url):
        value = urlsplit(url)
        if value.scheme or value.netloc or len(url) > 4096: raise ValueError('UFS_UNSAFE_PATH')
        path = unquote(value.path, errors='strict')
        if not path.startswith('/') or '\\' in path or ':' in path or '\x00' in path:
            raise ValueError('UFS_UNSAFE_PATH')
        parts = path.strip('/').split('/') if path.strip('/') else []
        if len(parts) > 32 or any(not p or p.startswith('.') or len(p.encode()) > 255 for p in parts):
            raise ValueError('UFS_UNSAFE_PATH')
        return parts

    def _checked(self, parts):
        if (not isinstance(parts,list) or len(parts)>32 or
                any(not isinstance(p,str) or not p or p.startswith('.') or len(p.encode())>255 or
                    any(c in p for c in ('/', '\\', ':', '\x00')) for p in parts)):
            raise ValueError('UFS_UNSAFE_COMPONENT')

    @contextmanager
    def directory(self, parts, create=False):
        self._checked(parts)
        fd = os.dup(self.fd)
        try:
            for part in parts:
                if create:
                    try: os.mkdir(part, mode=0o700, dir_fd=fd)
                    except FileExistsError: pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd); fd = child
            yield fd
        finally: os.close(fd)

    def open(self, parts):
        self._checked(parts)
        if not parts: raise IsADirectoryError()
        with self.directory(parts[:-1]) as parent:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd); raise PermissionError('UFS_REGULAR_FILE_REQUIRED')
        return os.fdopen(fd, 'rb')

    def entries(self, parts, maximum):
        self._checked(parts)
        with self.directory(parts) as fd:
            result = []
            # scandir is incremental: never materialize an unbounded directory.
            with os.scandir(fd) as entries:
                for entry in entries:
                    if entry.name.startswith('.') or entry.is_symlink(): continue
                    if len(result) >= maximum: raise ValueError('UFS_LISTING_LIMIT')
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode):
                        result.append((entry.name, info))
            return sorted(result, key=lambda item:item[0])

    def info(self, parts):
        self._checked(parts)
        if not parts: return os.fstat(self.fd)
        with self.directory(parts[:-1]) as fd:
            info = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise PermissionError('UFS_REGULAR_FILE_REQUIRED')
        return info

    def put(self, parts, reader, size, progress=lambda _:None):
        self._checked(parts)
        if not parts: raise IsADirectoryError()
        if type(size) is not int or not 0<=size<=10*1024**3: raise ValueError('UFS_UPLOAD_LIMIT')
        with self.lock, self.directory(parts[:-1], create=True) as parent:
            try:
                if not stat.S_ISREG(os.stat(parts[-1], dir_fd=parent, follow_symlinks=False).st_mode):
                    raise PermissionError('UFS_REGULAR_FILE_REQUIRED')
                existed = True
            except FileNotFoundError: existed = False
            name = '.ufs-upload-'+secrets.token_hex(16)
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            try:
                with os.fdopen(fd, 'wb') as target:
                    remaining = size
                    while remaining:
                        data = reader.read(min(65536, remaining))
                        if not isinstance(data,bytes) or not data or len(data)>remaining: raise ValueError('UFS_TRUNCATED_UPLOAD')
                        target.write(data); remaining -= len(data); progress(len(data))
                    target.flush(); os.fsync(target.fileno())
                os.replace(name, parts[-1], src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                try: os.unlink(name, dir_fd=parent)
                except FileNotFoundError: pass
            return existed

    def delete(self, parts):
        self._checked(parts)
        if not parts: raise PermissionError('UFS_ROOT_IMMUTABLE')
        with self.lock, self.directory(parts[:-1]) as parent:
            info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            if stat.S_ISREG(info.st_mode): os.unlink(parts[-1], dir_fd=parent)
            elif stat.S_ISDIR(info.st_mode): os.rmdir(parts[-1], dir_fd=parent)
            else: raise PermissionError('UFS_REGULAR_FILE_REQUIRED')
            os.fsync(parent)

    def mkdir(self, parts):
        self._checked(parts)
        if not parts: raise FileExistsError()
        with self.lock, self.directory(parts[:-1]) as parent:
            os.mkdir(parts[-1], mode=0o700, dir_fd=parent); os.fsync(parent)

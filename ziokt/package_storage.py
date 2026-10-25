"""Bounded, non-symlink paths for operator-owned package stores."""
import os
from pathlib import Path
import re
import tempfile

from .protocol import ProtocolError


def relative_path(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 256 or
            not re.fullmatch(r'[A-Za-z0-9_./+-]+', value) or
            any(part in {'', '.', '..'} for part in value.split('/'))):
        raise ProtocolError('PATH_TRAVERSAL', 'canonical relative file path required')
    return value


def safe_path(root, relative, *, leaf_link=False):
    relative_path(relative)
    root = Path(root).absolute()
    current = root
    for part in relative.split('/'):
        if current.is_symlink():
            raise ProtocolError('UNSAFE_FILE', 'symlink directory in package store')
        current = current / part
    if current.is_symlink() and not leaf_link:
        raise ProtocolError('UNSAFE_FILE', 'symlink file in package store')
    return current


def check_files(files, *, reserved=()):
    if not isinstance(files, dict) or not 1 <= len(files) <= 4096:
        raise ProtocolError('PACKAGE_INTEGRITY', '1..4096 package files required')
    total = 0
    for name, data in files.items():
        relative_path(name)
        if name.split('/')[0] in reserved:
            raise ProtocolError('PATH_TRAVERSAL', 'reserved package metadata path')
        if not isinstance(data, bytes) or len(data) > 32 * 1024 * 1024:
            raise ProtocolError('PACKAGE_INTEGRITY', 'bounded byte payload required')
        total += len(data)
        if total > 128 * 1024 * 1024:
            raise ProtocolError('PACKAGE_INTEGRITY', 'package exceeds 128 MiB')
        parts = name.split('/')
        if any('/'.join(parts[:index]) in files for index in range(1, len(parts))):
            raise ProtocolError('PACKAGE_INTEGRITY', 'file/directory collision')


def atomic_write(path, data, *, mode=0o600):
    path = Path(path)
    if path.is_symlink():
        raise ProtocolError('UNSAFE_FILE', 'symlink destination rejected')
    fd, temporary = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

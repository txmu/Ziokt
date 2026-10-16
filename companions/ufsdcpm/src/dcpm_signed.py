"""Existing Ziokt package signatures shared by native DCPM transports."""
import base64
import os
from ziokt.protocol import secure_read
from ziokt.security import sign
from ziokt.ufsdcpm import package_bytes, read_package

PREFIX = 'ziokt.dcpm-package.v1:'


def encode_package(package, key_path=None):
    key_path = key_path or os.environ.get('ZIOKT_DCPM_SIGNING_KEY')
    if not key_path: raise PermissionError('DCPM_PERSISTENT_SIGNING_KEY_REQUIRED')
    private = secure_read(key_path, 32)
    if len(private) != 32: raise ValueError('DCPM_ED25519_KEY_REQUIRED')
    public = sign({}, private, 'test')['public_key']
    blob = package_bytes(package.name, package.version, package.files, package.dependencies, private)
    return public, blob, PREFIX + base64.b64encode(blob).decode('ascii')


def decode_package(data, authority=None):
    authority = authority or os.environ.get('ZIOKT_DCPM_PUBLISHER_PUBLIC_KEY')
    if not isinstance(authority, str) or len(authority) != 64:
        raise PermissionError('DCPM_PINNED_PUBLISHER_REQUIRED')
    try:
        if len(bytes.fromhex(authority)) != 32: raise ValueError()
    except ValueError: raise ValueError('DCPM_PINNED_PUBLISHER_INVALID')
    if not isinstance(data, str) or len(data) > 8*1024*1024 or not data.startswith(PREFIX):
        raise ValueError('DCPM_LEGACY_OR_MISSING_UNSIGNED_METADATA_REJECTED')
    blob = base64.b64decode(data[len(PREFIX):], validate=True)
    manifest, files = read_package(blob, authority)
    return manifest, files

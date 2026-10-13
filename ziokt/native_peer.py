"""Use reviewed Shadow6 stream services for proxy links and native ICE paths."""
import hashlib
from pathlib import Path
import re
import sys
import threading

from .protocol import ProtocolError, secure_read

_imports = threading.Lock()


def validate_native(value, host):
    required = {'kind', 'shadow6_root', 'registry_path', 'service_name', 'lock_digest', 'sdk_digest'}
    if not isinstance(value, dict) or set(value) != required or value['kind'] != 'shadow6-stream':
        raise ProtocolError('INVALID_NATIVE_PATH', 'exact reviewed Shadow6 stream binding required')
    for field in ('shadow6_root', 'registry_path'):
        if not isinstance(value[field], str) or not Path(value[field]).is_absolute() or '..' in Path(value[field]).parts:
            raise ProtocolError('INVALID_NATIVE_PATH', 'absolute native path required')
    if not isinstance(value['service_name'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', value['service_name']):
        raise ProtocolError('INVALID_NATIVE_PATH', 'fixed native service name required')
    if any(not isinstance(value[field], str) or not re.fullmatch('sha256:[a-f0-9]{64}', value[field]) for field in ('lock_digest', 'sdk_digest')):
        raise ProtocolError('INVALID_NATIVE_PATH', 'pinned native lock and SDK digests required')
    return value


class NativeStream:
    def __init__(self, sdk, handle): self.sdk, self.handle, self.socket = sdk, handle, handle.socket
    def recv(self, size): return self.socket.recv(size)
    def sendall(self, data): return self.socket.sendall(data)
    def settimeout(self, timeout): self.socket.settimeout(timeout)
    def gettimeout(self): return self.socket.gettimeout()
    def fileno(self): return self.socket.fileno()
    def shutdown(self, how): self.socket.shutdown(how)
    def close(self):
        try: self.handle.close()
        finally: self.sdk.close()


def connect_native(host, port, value, timeout=30, cancellation=None):
    validate_native(value, host)
    if type(timeout) not in {int, float} or not 0 < timeout <= 120:
        raise ProtocolError('INVALID_NATIVE_PATH', 'bounded native connection deadline required')
    root = Path(value['shadow6_root'])
    source = root/'libshadow6/__init__.py'
    if root.is_symlink() or hashlib.sha256(secure_read(source, 128*1024, private=None)).hexdigest() != value['sdk_digest'][7:]:
        raise ProtocolError('STALE_PLAN', 'reviewed Shadow6 SDK source changed')
    secure_read(value['registry_path'], 4*1024*1024)
    with _imports:
        for name in ('libshadow6', 'Deployment', 'Deployment.service_registry', 'Deployment.core_catalog'):
            existing = sys.modules.get(name)
            if existing is not None and getattr(existing, '__file__', None) is not None and not Path(existing.__file__).resolve().is_relative_to(root.resolve()):
                raise ProtocolError('STALE_PLAN', 'loaded SDK belongs to another native source tree')
        sys.path[:0] = [str(root), str(root/'Deployment'), str(root/'Crosed')]
        from Deployment.service_registry import ServiceRegistry
        from Deployment.core_catalog import CoreCatalog
        from libshadow6 import Shadow6, RegistryControl
    registry = ServiceRegistry(value['registry_path'], CoreCatalog(root))
    item = registry.services.get(value['service_name'], {})
    if (item.get('deploymentLock') or {}).get('digest') != value['lock_digest']:
        raise ProtocolError('STALE_PLAN', 'native service binding changed')
    sdk = Shadow6(control=RegistryControl(registry))
    try:
        handle = sdk.connect_handle(value['service_name'], timeout=timeout, cancellation=cancellation,
                                    require={'kind': 'stream', 'reliable': True, 'ordered': True})
        if handle.describe().get('lockDigest') != value['lock_digest']:
            handle.close(); raise ProtocolError('STALE_PLAN', 'opened native stream differs from reviewed lock')
        return NativeStream(sdk, handle)
    except BaseException:
        sdk.close(); raise

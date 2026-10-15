"""Process-scoped offline policy. Activate before starting any network workers.

This is an application guard, not an OS sandbox for untrusted native code.
"""
import os
import sys

_active = False


def airgap_enabled():
    global _active
    if os.environ.get('ZIOKT_AIRGAP', '').lower() in {'1', 'true', 'yes'}:
        _active = True
    return _active


def activate_airgap():
    global _active
    _active = True
    os.environ['ZIOKT_AIRGAP'] = '1'


def require_network():
    if airgap_enabled():
        from .protocol import ProtocolError
        raise ProtocolError('AIRGAP_DENIED', 'AirGap blocks networking and external workers; restart to return online')


def status():
    return {'schema': 'ziokt.network-policy.v1', 'mode': 'airgap' if airgap_enabled() else 'online',
            'network_allowed': not airgap_enabled(), 'external_workers_allowed': not airgap_enabled(),
            'local_compute': True, 'offline_file_exchange': True, 'os_sandbox': False}


def _audit(event, args):
    # Deny before DNS, opening a listener, transmitting, or executing a child.
    # Blocks all socket families so local proxies cannot bypass the policy.
    if (event.startswith('socket.') or event in {
            'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.fork', 'os.forkpty'}):
        require_network()


sys.addaudithook(_audit)

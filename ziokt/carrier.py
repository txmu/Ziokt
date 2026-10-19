"""Explicit Tor SOCKS5 carrier: onion-only destinations, no local DNS or fallback.

The operator owns the Tor process. This module never creates hidden services,
changes routing, or treats a SOCKS handshake as proof against traffic analysis.
"""
import base64
import hashlib
import ipaddress
import secrets
import socket
import struct
import threading
import time

from .protocol import ProtocolError


def onion_address(host):
    if not isinstance(host, str) or len(host) != 62 or not host.endswith('.onion'):
        raise ProtocolError('INVALID_CARRIER', 'exact Tor v3 onion destination required')
    try:
        raw = base64.b32decode(host[:56].upper())
        if host != host.lower() or raw[-1:] != b'\x03' or raw[32:34] != hashlib.sha3_256(b'.onion checksum'+raw[:32]+raw[-1:]).digest()[:2]:
            raise ValueError()
    except ValueError:
        raise ProtocolError('INVALID_CARRIER', 'onion version or checksum rejected')
    return host


def validate_carrier(value, host):
    if isinstance(value, dict) and value.get('kind') == 'shadow6-stream':
        from .native_peer import validate_native
        return validate_native(value, host)
    if isinstance(value, dict) and value.get('kind') == 'i2p-sam':
        from .i2p import validate_i2p
        return validate_i2p(value, host)
    if isinstance(value, dict) and value.get('kind') == 'peer-multihop':
        from .peer_proxy import validate_peer_carrier
        return validate_peer_carrier(value, host)
    required = {'kind', 'proxy_host', 'proxy_port'}
    if (not isinstance(value, dict) or not required <= set(value) or set(value)-required-{'hops'} or value['kind'] != 'tor-socks5' or
            type(value['proxy_port']) is not int or not 1 <= value['proxy_port'] <= 65535):
        raise ProtocolError('INVALID_CARRIER', 'fixed local Tor SOCKS5 proxy required')
    try:
        if not ipaddress.ip_address(value['proxy_host']).is_loopback:
            raise ValueError()
    except (ValueError, TypeError):
        raise ProtocolError('INVALID_CARRIER', 'proxy must be a literal loopback IP')
    onion_address(host)
    hops = value.get('hops', [])
    if not isinstance(hops, list) or len(hops) > 3:
        raise ProtocolError('INVALID_CARRIER', 'at most three explicit onion SOCKS5 intermediate hops required')
    seen = {host}
    for hop in hops:
        if (not isinstance(hop, dict) or set(hop) != {'host', 'port'} or
                type(hop['port']) is not int or not 1 <= hop['port'] <= 65535):
            raise ProtocolError('INVALID_CARRIER', 'exact onion intermediate host and port required')
        onion_address(hop['host'])
        if hop['host'] in seen:
            raise ProtocolError('INVALID_CARRIER', 'repeated onion hops or destination loops rejected')
        seen.add(hop['host'])
    return value


def carrier_deadline(value):
    """A finite per-path budget; every onion intermediate adds a handshake."""
    if value is None: return 30
    if value.get('kind') == 'tor-socks5':
        hops = value.get('hops', [])
        if type(hops) is not list or len(hops) > 3:
            raise ProtocolError('INVALID_CARRIER', 'bounded onion path required')
        return 30 * (1 + len(hops))
    entry = value.get('entry_carrier') or {}
    budget = value.get('deadline_seconds', 90 if value.get('kind') == 'i2p-sam' or entry.get('kind') == 'i2p-sam' else 30)
    if type(budget) is not int or not 1 <= budget <= 120:
        raise ProtocolError('INVALID_CARRIER', 'bounded carrier deadline required')
    return budget


def open_carrier(host, port, value=None, timeout=30, cancellation=None):
    from .runtime_policy import require_network
    require_network()
    if cancellation is not None and cancellation.is_set(): raise ProtocolError('CANCELLED', 'carrier request cancelled')
    if value is None:
        if isinstance(host, str) and host.endswith(('.onion', '.i2p')):
            raise ProtocolError('NO_POLICY_COMPLIANT_PATH', 'anonymous host requires its reviewed carrier')
        return socket.create_connection((host, port), timeout=timeout)
    validate_carrier(value, host)
    if value['kind'] == 'tor-socks5': return connect_onion(host, port, value, min(carrier_deadline(value), timeout), cancellation=cancellation)
    if value['kind'] == 'i2p-sam':
        from .i2p import connect_i2p
        return connect_i2p(host, port, value, timeout, cancellation)
    if value['kind'] == 'shadow6-stream':
        from .native_peer import connect_native
        return connect_native(host, port, value, timeout, cancellation)
    if value['kind'] == 'peer-multihop':
        from .peer_proxy import connect_peer
        return connect_peer(host, port, value, timeout, cancellation)
    raise ProtocolError('INVALID_CARRIER', 'unknown carrier')


def connect_onion(host, port, carrier, timeout=None, cancellation=None):
    from .runtime_policy import require_network
    require_network()
    if not isinstance(carrier, dict) or carrier.get('kind') != 'tor-socks5':
        raise ProtocolError('INVALID_CARRIER', 'Tor onion connector requires its Tor carrier')
    validate_carrier(carrier, host)
    budget = carrier_deadline(carrier)
    if timeout is None: timeout = budget
    if type(port) is not int or not 1 <= port <= 65535 or type(timeout) not in {int, float} or not 0 < timeout <= budget:
        raise ProtocolError('INVALID_CARRIER', 'bounded port and deadline required')
    if cancellation is not None and cancellation.is_set(): raise ProtocolError('CANCELLED', 'onion connection cancelled')
    deadline = time.monotonic()+timeout
    try:
        sock = socket.create_connection((carrier['proxy_host'], carrier['proxy_port']), timeout=timeout)
    except OSError as exc:
        error = ProtocolError('CARRIER_UNAVAILABLE', 'approved onion entry unavailable (phase=entry-connect; kind='+type(exc).__name__+')')
        error.transport_diagnostic = {'phase': 'entry-connect', 'kind': type(exc).__name__, 'socks_reply': None}
        raise error from None
    done = threading.Event()
    watcher = None
    if cancellation is not None:
        def monitor():
            while not done.wait(.2):
                if cancellation.is_set():
                    try: sock.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
                    return
        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
    def send(data):
        remaining = deadline-time.monotonic()
        if remaining <= 0: raise TimeoutError('carrier deadline')
        sock.settimeout(remaining)
        sock.sendall(data)
    def read(size):
        data = bytearray()
        while len(data) < size:
            remaining = deadline-time.monotonic()
            if remaining <= 0: raise TimeoutError('carrier deadline')
            sock.settimeout(remaining)
            part = sock.recv(size-len(data))
            if not part: raise OSError('carrier closed')
            data.extend(part)
        return bytes(data)
    diagnostic={'phase':'entry-connected','reply':None}
    def negotiate(destination, destination_port, label):
        diagnostic['phase']=label+'-auth-method';diagnostic['reply']=None
        # Require authentication negotiation; fresh Tor isolation values on each
        # connection. A proxy refusing this method does not get a downgrade.
        send(b'\x05\x01\x02')
        if read(2) != b'\x05\x02': raise OSError('carrier authentication method')
        diagnostic['phase']=label+'-isolation-auth'
        username = b'<torS0X>0'; password = secrets.token_hex(16).encode()
        send(b'\x01'+bytes([len(username)])+username+bytes([len(password)])+password)
        if read(2) != b'\x01\x00': raise OSError('carrier isolation rejected')
        diagnostic['phase']=label+'-socks-connect'
        name = destination.encode('ascii')
        send(b'\x05\x01\x00\x03'+bytes([len(name)])+name+struct.pack('!H', destination_port))
        reply = read(4)
        if reply[0]!=5 or reply[2]!=0:raise OSError('carrier malformed reply')
        diagnostic['reply']=reply[1]
        if reply[1]!=0:raise OSError('carrier destination rejected')
        diagnostic['phase']=label+'-bound-address'
        if reply[3] == 1: read(4)
        elif reply[3] == 4: read(16)
        elif reply[3] == 3: read(read(1)[0])
        else: raise OSError('carrier address type')
        read(2)
    try:
        # Every intermediary is an operator-provisioned SOCKS5 onion service.
        # All CONNECT names stay inside their respective Tor paths; only the
        # loopback entry proxy is opened locally, with no retry or bypass.
        for index,hop in enumerate(carrier.get('hops', [])):
            negotiate(hop['host'], hop['port'],'hop-'+str(index+1))
        negotiate(host, port,'target')
        remaining = deadline-time.monotonic()
        if remaining <= 0: raise TimeoutError('carrier deadline')
        if cancellation is not None and cancellation.is_set(): raise ProtocolError('CANCELLED', 'onion connection cancelled')
        sock.settimeout(remaining)
        return sock
    except OSError as exc:
        sock.close()
        if cancellation is not None and cancellation.is_set(): raise ProtocolError('CANCELLED', 'onion connection cancelled') from None
        detail='phase='+diagnostic['phase']+'; kind='+type(exc).__name__
        if diagnostic['reply'] is not None:detail+='; socks_reply=0x'+format(diagnostic['reply'],'02x')
        error = ProtocolError('CARRIER_UNAVAILABLE', 'approved onion path failed ('+detail+')')
        error.transport_diagnostic = dict(diagnostic, kind=type(exc).__name__)
        # Keep the structured field name stable without copying exception text,
        # destinations, isolation passwords or onion identities into diagnostics.
        error.transport_diagnostic['socks_reply'] = error.transport_diagnostic.pop('reply')
        raise error from None
    except BaseException:
        sock.close()
        raise
    finally:
        done.set()
        if watcher is not None: watcher.join(.5)

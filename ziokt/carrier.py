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


def open_carrier(host, port, value=None, timeout=30, cancellation=None):
    if cancellation is not None and cancellation.is_set(): raise ProtocolError('CANCELLED', 'carrier request cancelled')
    if value is None:
        if isinstance(host, str) and host.endswith(('.onion', '.i2p')):
            raise ProtocolError('NO_POLICY_COMPLIANT_PATH', 'anonymous host requires its reviewed carrier')
        return socket.create_connection((host, port), timeout=timeout)
    validate_carrier(value, host)
    if value['kind'] == 'tor-socks5': return connect_onion(host, port, value, min(30, timeout))
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


def connect_onion(host, port, carrier, timeout=30):
    if not isinstance(carrier, dict) or carrier.get('kind') != 'tor-socks5':
        raise ProtocolError('INVALID_CARRIER', 'Tor onion connector requires its Tor carrier')
    validate_carrier(carrier, host)
    if type(port) is not int or not 1 <= port <= 65535 or type(timeout) not in {int, float} or not 0 < timeout <= 30:
        raise ProtocolError('INVALID_CARRIER', 'bounded port and deadline required')
    deadline = time.monotonic()+timeout
    try:
        sock = socket.create_connection((carrier['proxy_host'], carrier['proxy_port']), timeout=timeout)
    except OSError:
        raise ProtocolError('CARRIER_UNAVAILABLE', 'approved onion entry unavailable') from None
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
    def negotiate(destination, destination_port):
        # Require authentication negotiation; fresh Tor isolation values on each
        # connection. A proxy refusing this method does not get a downgrade.
        send(b'\x05\x01\x02')
        if read(2) != b'\x05\x02': raise OSError('carrier authentication method')
        username = b'<torS0X>0'; password = secrets.token_hex(16).encode()
        send(b'\x01'+bytes([len(username)])+username+bytes([len(password)])+password)
        if read(2) != b'\x01\x00': raise OSError('carrier isolation rejected')
        name = destination.encode('ascii')
        send(b'\x05\x01\x00\x03'+bytes([len(name)])+name+struct.pack('!H', destination_port))
        reply = read(4)
        if reply[:3] != b'\x05\x00\x00': raise OSError('carrier destination rejected')
        if reply[3] == 1: read(4)
        elif reply[3] == 4: read(16)
        elif reply[3] == 3: read(read(1)[0])
        else: raise OSError('carrier address type')
        read(2)
    try:
        # Every intermediary is an operator-provisioned SOCKS5 onion service.
        # All CONNECT names stay inside their respective Tor paths; only the
        # loopback entry proxy is opened locally, with no retry or bypass.
        for hop in carrier.get('hops', []):
            negotiate(hop['host'], hop['port'])
        negotiate(host, port)
        remaining = deadline-time.monotonic()
        if remaining <= 0: raise TimeoutError('carrier deadline')
        sock.settimeout(remaining)
        return sock
    except OSError:
        sock.close()
        raise ProtocolError('CARRIER_UNAVAILABLE', 'approved onion path failed') from None
    except BaseException:
        sock.close()
        raise

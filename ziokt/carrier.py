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
    if (not isinstance(value, dict) or set(value) != {'kind', 'proxy_host', 'proxy_port'} or value['kind'] != 'tor-socks5' or
            type(value['proxy_port']) is not int or not 1 <= value['proxy_port'] <= 65535):
        raise ProtocolError('INVALID_CARRIER', 'fixed local Tor SOCKS5 proxy required')
    try:
        if not ipaddress.ip_address(value['proxy_host']).is_loopback:
            raise ValueError()
    except (ValueError, TypeError):
        raise ProtocolError('INVALID_CARRIER', 'proxy must be a literal loopback IP')
    onion_address(host)
    return value


def connect_onion(host, port, carrier, timeout=30):
    validate_carrier(carrier, host)
    if type(port) is not int or not 1 <= port <= 65535 or type(timeout) not in {int, float} or not 0 < timeout <= 30:
        raise ProtocolError('INVALID_CARRIER', 'bounded port and deadline required')
    deadline = time.monotonic()+timeout
    sock = socket.create_connection((carrier['proxy_host'], carrier['proxy_port']), timeout=timeout)
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
    try:
        # Require authentication negotiation; fresh Tor isolation values on each
        # connection. A proxy refusing this method does not get a downgrade.
        sock.sendall(b'\x05\x01\x02')
        if read(2) != b'\x05\x02': raise OSError('carrier authentication method')
        username = b'<torS0X>0'; password = secrets.token_hex(16).encode()
        sock.sendall(b'\x01'+bytes([len(username)])+username+bytes([len(password)])+password)
        if read(2) != b'\x01\x00': raise OSError('carrier isolation rejected')
        name = host.encode('ascii')
        sock.sendall(b'\x05\x01\x00\x03'+bytes([len(name)])+name+struct.pack('!H', port))
        reply = read(4)
        if reply[:3] != b'\x05\x00\x00': raise OSError('carrier destination rejected')
        if reply[3] == 1: read(4)
        elif reply[3] == 4: read(16)
        elif reply[3] == 3: read(read(1)[0])
        else: raise OSError('carrier address type')
        read(2)
        remaining = deadline-time.monotonic()
        if remaining <= 0: raise TimeoutError('carrier deadline')
        sock.settimeout(remaining)
        return sock
    except BaseException:
        sock.close()
        raise

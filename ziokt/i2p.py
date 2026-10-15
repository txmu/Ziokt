"""Bounded SAM 3.1 streams, long-lived sessions and pinned b32 destinations.

Only the explicitly configured loopback router is contacted. Session identities
are reused per carrier, rather than rebuilding I2P tunnels for every HTTP range.
"""
import atexit
import ipaddress
import re
import secrets
import select
import socket
import threading
import time

from .protocol import ProtocolError

B32 = re.compile(r'[a-z2-7]{52}\.b32\.i2p\Z')
_sessions = {}
_lock = threading.Lock()


def i2p_address(host):
    if not isinstance(host, str) or not B32.fullmatch(host):
        raise ProtocolError('INVALID_I2P', 'pinned canonical I2P b32 destination required')
    import base64
    try:
        raw = base64.b32decode(host[:52].upper()+'====')
        if base64.b32encode(raw).decode().lower().rstrip('=') != host[:52]: raise ValueError()
    except ValueError:
        raise ProtocolError('INVALID_I2P', 'noncanonical I2P destination rejected')
    return host


def validate_i2p(value, host):
    required = {'kind', 'proxy_host', 'proxy_port'}
    if not isinstance(value, dict) or not required <= set(value) or set(value)-required-{'tunnel_length', 'tunnel_quantity', 'isolation_scope'} or value['kind'] != 'i2p-sam':
        raise ProtocolError('INVALID_I2P', 'exact local I2P SAM carrier required')
    try:
        if not isinstance(value['proxy_host'], str) or not ipaddress.ip_address(value['proxy_host']).is_loopback: raise ValueError()
    except ValueError:
        raise ProtocolError('INVALID_I2P', 'SAM must use a literal loopback IP')
    if type(value['proxy_port']) is not int or not 1 <= value['proxy_port'] <= 65535:
        raise ProtocolError('INVALID_I2P', 'bounded SAM port required')
    for name, default, maximum in [('tunnel_length', 3, 4), ('tunnel_quantity', 2, 3)]:
        number = value.get(name, default)
        if type(number) is not int or not 2 <= number <= maximum:
            raise ProtocolError('INVALID_I2P', 'bounded explicit I2P tunnel settings required')
    i2p_address(host)
    if not isinstance(value.get('isolation_scope', 'local'), str) or not re.fullmatch('[A-Za-z0-9._-]{1,64}', value.get('isolation_scope', 'local')):
        raise ProtocolError('INVALID_I2P', 'fixed I2P isolation scope required')
    return value


def _reply(sock, prefix, deadline, cancellation=None):
    data = bytearray()
    while len(data) <= 8192:
        remaining = deadline-time.monotonic()
        if cancellation is not None and cancellation.is_set(): raise ProtocolError('CANCELLED', 'I2P request cancelled')
        if remaining <= 0: raise TimeoutError('SAM deadline')
        sock.settimeout(min(1, remaining))
        try: part = sock.recv(1)
        except socket.timeout: continue
        if not part: raise OSError('SAM closed')
        if part == b'\n': break
        data.extend(part)
    else: raise ProtocolError('INVALID_I2P', 'SAM reply budget exceeded')
    try:
        line = data.decode('ascii')
        if not line.startswith(prefix+' '): raise ValueError()
        # MESSAGE may contain spaces; RESULT and VERSION must be unambiguous.
        fields = {}
        for token in line[len(prefix)+1:].split():
            if '=' not in token: continue
            key, value = token.split('=', 1)
            if key in {'RESULT', 'VERSION'}:
                if key in fields: raise ValueError()
                fields[key] = value
        if fields.get('RESULT') != 'OK':
            raise ProtocolError('CARRIER_UNAVAILABLE', 'I2P router refused the approved path')
        return fields
    except ProtocolError:
        raise
    except ValueError:
        raise ProtocolError('INVALID_I2P', 'SAM status rejected') from None


def _hello(sock, deadline, cancellation=None):
    sock.sendall(b'HELLO VERSION MIN=3.1 MAX=3.1\n')
    if _reply(sock, 'HELLO REPLY', deadline, cancellation).get('VERSION') != '3.1':
        raise ProtocolError('INVALID_I2P', 'SAM 3.1 negotiation required')


class Session:
    def __init__(self, value, deadline, cancellation=None):
        self.id = 'ziokt-'+secrets.token_hex(12)
        self.proxy = (value['proxy_host'], value['proxy_port'])
        self.control = socket.create_connection(self.proxy, timeout=max(.001, deadline-time.monotonic()))
        try:
            _hello(self.control, deadline, cancellation)
            length, quantity = value.get('tunnel_length', 3), value.get('tunnel_quantity', 2)
            self.control.sendall((f'SESSION CREATE STYLE=STREAM ID={self.id} DESTINATION=TRANSIENT SIGNATURE_TYPE=7 '
                f'i2cp.leaseSetEncType=4 inbound.length={length} outbound.length={length} '
                f'inbound.quantity={quantity} outbound.quantity={quantity}\n').encode())
            _reply(self.control, 'SESSION STATUS', deadline, cancellation)
        except BaseException:
            self.control.close(); raise

    def alive(self):
        return self.control.fileno() >= 0 and not select.select([self.control], [], [], 0)[0]

    def close(self): self.control.close()

    def connect(self, host, deadline, cancellation=None):
        sock = socket.create_connection(self.proxy, timeout=max(.001, deadline-time.monotonic()))
        try:
            _hello(sock, deadline, cancellation)
            sock.sendall(f'STREAM CONNECT ID={self.id} DESTINATION={host} SILENT=false\n'.encode())
            _reply(sock, 'STREAM STATUS', deadline, cancellation)
            sock.settimeout(max(.001, deadline-time.monotonic()))
            return sock
        except BaseException:
            sock.close(); raise


def close_sessions():
    with _lock:
        for session in _sessions.values(): session.close()
        _sessions.clear()


atexit.register(close_sessions)


def connect_i2p(host, port, value, timeout=90, cancellation=None):
    from .runtime_policy import require_network
    require_network()
    validate_i2p(value, host)
    if type(port) is not int or not 1 <= port <= 65535 or type(timeout) not in {int, float} or not 0 < timeout <= 120:
        raise ProtocolError('INVALID_I2P', 'bounded I2P service and deadline required')
    deadline = time.monotonic()+timeout
    key = (value['proxy_host'], value['proxy_port'], value.get('tunnel_length', 3), value.get('tunnel_quantity', 2), value.get('isolation_scope', 'local'))
    while not _lock.acquire(timeout=min(1, max(0, deadline-time.monotonic()))):
        if cancellation is not None and cancellation.is_set(): raise ProtocolError('CANCELLED', 'I2P request cancelled')
        if time.monotonic() >= deadline: raise ProtocolError('CARRIER_UNAVAILABLE', 'I2P session budget busy')
    try:
        session = _sessions.get(key)
        if session is not None and not session.alive():
            session.close(); del _sessions[key]; session = None
        if session is None:
            if len(_sessions) >= 4: raise ProtocolError('BACKPRESSURE', 'I2P session budget exhausted')
            session = Session(value, deadline, cancellation); _sessions[key] = session
    except OSError:
        raise ProtocolError('CARRIER_UNAVAILABLE', 'local I2P SAM router unavailable') from None
    finally: _lock.release()
    try: return session.connect(host, deadline, cancellation)
    except OSError:
        raise ProtocolError('CARRIER_UNAVAILABLE', 'approved I2P stream failed') from None

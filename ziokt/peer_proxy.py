"""Opt-in, authenticated byte proxies and nested TLS, with no community keys.

Each proxy learns its immediate destination. The client verifies each hop and
keeps the final application's mTLS inside all tunnels using SSL MemoryBIO.
"""
import hashlib
import io
import ipaddress
from pathlib import Path
import re
import select
import socket
import socketserver
import ssl
import struct
import threading
import time

from .protocol import ProtocolError, encoded, secure_read, strict_json

FRAME_LIMIT = 16384


def address(host, port, *, listening=False):
    try:
        if not isinstance(host, str) or '%' in host: raise ValueError()
        ipaddress.ip_address(host)
    except ValueError:
        raise ProtocolError('INVALID_PROXY', 'literal IPv4 or IPv6 address required')
    if type(port) is not int or not (0 if listening else 1) <= port <= 65535:
        raise ProtocolError('INVALID_PROXY', 'bounded explicit proxy port required')
    return host, port


def target_address(host, port):
    if isinstance(host, str) and host.endswith('.onion'):
        from .carrier import onion_address
        onion_address(host)
    elif isinstance(host, str) and host.endswith('.i2p'):
        from .i2p import i2p_address
        i2p_address(host)
    else: return address(host, port)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ProtocolError('INVALID_PROXY', 'bounded destination port required')
    return host, port


def target_key(host, port):
    try: host = ipaddress.ip_address(host)
    except ValueError: pass
    return host, port


def validate_peer_carrier(value, host):
    if not isinstance(value, dict) or not {'kind', 'hops'} <= set(value) or set(value)-{'kind', 'hops', 'entry_carrier', 'deadline_seconds'} or value['kind'] != 'peer-multihop':
        raise ProtocolError('INVALID_PROXY', 'exact opt-in peer carrier required')
    target_address(host, 1)
    if type(value.get('deadline_seconds', 30)) is not int or not 1 <= value.get('deadline_seconds', 30) <= 120:
        raise ProtocolError('INVALID_PROXY', 'bounded overall peer deadline required')
    if not isinstance(value['hops'], list) or not 2 <= len(value['hops']) <= 4:
        raise ProtocolError('INVALID_PROXY', 'two to four explicit peer proxies required')
    seen = set()
    for hop in value['hops']:
        if not isinstance(hop, dict) or not {'host', 'port', 'tls_config'} <= set(hop) or set(hop)-{'host', 'port', 'tls_config', 'server_fingerprint'}:
            raise ProtocolError('INVALID_PROXY', 'fixed peer address and TLS config required')
        target = target_address(hop['host'], hop['port'])
        canonical = target_key(*target)
        if canonical in seen:
            raise ProtocolError('INVALID_PROXY', 'repeated peer proxy rejected')
        seen.add(canonical)
        if 'server_fingerprint' in hop and (not isinstance(hop['server_fingerprint'], str) or not re.fullmatch('[a-f0-9]{64}', hop['server_fingerprint'])):
            raise ProtocolError('INVALID_PROXY', 'pinned peer certificate fingerprint required')
        if not isinstance(hop['tls_config'], str) or not Path(hop['tls_config']).is_absolute() or '..' in Path(hop['tls_config']).parts:
            raise ProtocolError('INVALID_PROXY', 'absolute fixed peer TLS material config required')
    entry = value.get('entry_carrier')
    if entry is not None:
        if not isinstance(entry, dict) or entry.get('kind') not in {'tor-socks5', 'i2p-sam', 'shadow6-stream'}:
            raise ProtocolError('INVALID_PROXY', 'fixed native or anonymous entry carrier required')
        from .carrier import validate_carrier
        validate_carrier(entry, value['hops'][0]['host'])
    elif value['hops'][0]['host'].endswith(('.onion', '.i2p')):
        raise ProtocolError('INVALID_PROXY', 'anonymous first hop requires an explicit entry carrier')
    return value


def _read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        part = stream.recv(size-len(data))
        if not part: raise OSError('proxy stream ended')
        data.extend(part)
    return bytes(data)


def read_frame(stream):
    size = struct.unpack('!I', _read_exact(stream, 4))[0]
    if not 1 <= size <= FRAME_LIMIT:
        raise ProtocolError('INVALID_PROXY', 'bounded proxy control frame required')
    return strict_json(_read_exact(stream, size), FRAME_LIMIT)


def write_frame(stream, value):
    data = encoded(value)
    if len(data) > FRAME_LIMIT:
        raise ProtocolError('INVALID_PROXY', 'proxy control frame exceeds budget')
    stream.sendall(struct.pack('!I', len(data))+data)


class TLSStream:
    """Socket-shaped TLS over another stream; wrapping SSLSocket loses its TLS.

    SSLObject/MemoryBIO preserve every outer encrypted layer instead. Only the
    request thread performs TLS I/O; cancellation shuts down the root socket.
    """
    def __init__(self, stream, context, host, deadline):
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname or context.minimum_version < ssl.TLSVersion.TLSv1_3:
            raise ProtocolError('INVALID_PROXY', 'verified TLS 1.3 client context required')
        self.stream, self.deadline = stream, deadline
        self.incoming, self.outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        self.tls = context.wrap_bio(self.incoming, self.outgoing, server_hostname=host)
        self.closed = False
        self.close_requested, self.readers = False, 0

    def _flush(self):
        while self.outgoing.pending:
            self.stream.sendall(self.outgoing.read(16384))

    def _run(self, operation):
        while True:
            remaining = self.deadline-time.monotonic()
            if remaining <= 0: raise TimeoutError('peer path deadline')
            self.stream.settimeout(remaining)
            try:
                result = operation()
                self._flush()
                return result
            except ssl.SSLWantWriteError:
                self._flush()
            except ssl.SSLWantReadError:
                self._flush()
                data = self.stream.recv(16384)
                if data: self.incoming.write(data)
                else: self.incoming.write_eof()

    def do_handshake(self): self._run(self.tls.do_handshake)

    def sendall(self, data):
        data = memoryview(data)
        while data:
            written = self._run(lambda: self.tls.write(data[:16384]))
            data = data[written:]

    def recv(self, size):
        if size == 0: return b''
        try: return self._run(lambda: self.tls.read(size))
        except (ssl.SSLZeroReturnError, ssl.SSLEOFError): return b''

    def settimeout(self, timeout): self.stream.settimeout(timeout)
    def shutdown(self, how): self.stream.shutdown(how)
    def close(self):
        self.close_requested = True
        if not self.closed and not self.readers:
            self.closed = True
            self.stream.close()

    def makefile(self, mode='rb', buffering=None):
        if mode != 'rb': raise ValueError('peer TLS supports read-only HTTP streams')
        stream = self
        self.readers += 1
        class Reader(io.RawIOBase):
            def readable(self): return True
            def readinto(self, buffer):
                data = stream.recv(len(buffer)); buffer[:len(data)] = data
                return len(data)
            def close(self):
                if not self.closed:
                    super().close()
                    stream.readers -= 1
                    if stream.close_requested: stream.close()
        return io.BufferedReader(Reader())


def connect_peer(host, port, carrier, timeout=30, cancellation=None):
    from .runtime_policy import require_network
    require_network()
    validate_peer_carrier(carrier, host)
    destination = target_address(host, port)
    if type(timeout) not in {int, float} or not 0 < timeout <= 120:
        raise ProtocolError('INVALID_PROXY', 'bounded peer path deadline required')
    from .remote import load_remote, tls_context
    hops, contexts = carrier['hops'], []
    if any(target_key(h['host'], h['port']) == target_key(host, port) for h in hops):
        raise ProtocolError('INVALID_PROXY', 'final destination cannot be an intermediate proxy')
    # Validate all credential files before opening even the first connection.
    deadline = time.monotonic()+timeout
    for hop in hops:
        config = load_remote(hop['tls_config'])
        if (config['host'], config['port']) != (hop['host'], hop['port']) or set(config) & {'carrier', 'candidates', 'rendezvous'}:
            raise ProtocolError('INVALID_PROXY', 'peer TLS config must match this direct hop')
        contexts.append(tls_context(config['certificate'], config['private_key'], config['ca']))
    stream = None
    finished = threading.Event()
    try:
        remaining = deadline-time.monotonic()
        if remaining <= 0: raise TimeoutError('peer path deadline')
        from .carrier import open_carrier
        stream = open_carrier(hops[0]['host'], hops[0]['port'], carrier.get('entry_carrier'), timeout=remaining, cancellation=cancellation)
        if cancellation is not None:
            root_stream = stream
            def watch():
                while not finished.wait(.1):
                    if cancellation.is_set():
                        try: root_stream.shutdown(socket.SHUT_RDWR)
                        except OSError: pass
                        return
            threading.Thread(target=watch, name='ziokt-hop-cancellation', daemon=True).start()
        for index, hop in enumerate(hops):
            stream = TLSStream(stream, contexts[index], hop['host'], deadline)
            stream.do_handshake()
            if 'server_fingerprint' in hop and hashlib.sha256(stream.tls.getpeercert(binary_form=True)).hexdigest() != hop['server_fingerprint']:
                raise ProtocolError('PROXY_DENIED', 'peer certificate differs from its signed advertisement')
            target = (hops[index+1]['host'], hops[index+1]['port']) if index+1 < len(hops) else destination
            write_frame(stream, {'schema': 'ziokt.proxy-connect.v1', 'host': target[0], 'port': target[1]})
            if read_frame(stream) != {'ready': True}:
                raise ProtocolError('PROXY_DENIED', 'approved peer refused the next hop')
        return stream
    except OSError:
        if stream is not None: stream.close()
        raise ProtocolError('CARRIER_UNAVAILABLE', 'approved peer path failed') from None
    except BaseException:
        if stream is not None: stream.close()
        raise
    finally: finished.set()


def proxy_server(config, context):
    from .runtime_policy import require_network
    require_network()
    required = {'schema', 'enabled', 'host', 'port', 'trusted_clients', 'targets', 'max_connections', 'max_bytes', 'max_seconds'}
    if not isinstance(config, dict) or set(config)-required-{'certificate', 'private_key', 'ca', 'discovery'} or not required <= set(config) or config['schema'] != 'ziokt.peer-proxy.v1' or type(config['enabled']) is not bool:
        raise ProtocolError('INVALID_PROXY', 'exact opt-in proxy configuration required')
    if not config['enabled']:
        raise ProtocolError('PROXY_DISABLED', 'peer proxy must be explicitly enabled')
    address(config['host'], config['port'], listening=True)
    directory = directory_config = None
    if 'discovery' in config:
        if not isinstance(config['discovery'], str) or not Path(config['discovery']).is_absolute():
            raise ProtocolError('INVALID_DISCOVERY', 'fixed local discovery config required')
        from .peer_directory import load_directory
        directory, directory_config = load_directory(config['discovery'])
    fingerprints = config['trusted_clients']
    if (not isinstance(fingerprints, list) or not (0 if directory is not None else 1) <= len(fingerprints) <= 64 or
            any(not isinstance(f, str) or not re.fullmatch('[a-f0-9]{64}', f) for f in fingerprints)):
        raise ProtocolError('INVALID_PROXY', 'pinned approved client certificate fingerprints required')
    if not isinstance(config['targets'], list) or not (0 if directory is not None else 1) <= len(config['targets']) <= 64:
        raise ProtocolError('INVALID_PROXY', 'one to sixty-four explicit next-hop targets required')
    targets = {}
    for target in config['targets']:
        if not isinstance(target, dict) or not {'host', 'port'} <= set(target) or set(target)-{'host', 'port', 'carrier'}:
            raise ProtocolError('INVALID_PROXY', 'exact approved proxy target required')
        host, port = target_address(target['host'], target['port'])
        target_carrier = target.get('carrier')
        if target_carrier is not None:
            from .carrier import validate_carrier
            if not isinstance(target_carrier, dict) or target_carrier.get('kind') not in {'tor-socks5', 'i2p-sam', 'shadow6-stream'}:
                raise ProtocolError('INVALID_PROXY', 'reviewed target carrier required')
            validate_carrier(target_carrier, host)
        elif host.endswith(('.onion', '.i2p')):
            raise ProtocolError('INVALID_PROXY', 'anonymous proxy target requires its local carrier')
        targets[target_key(host, port)] = target_carrier
    for field, maximum in [('max_connections', 32), ('max_bytes', 128*1024*1024), ('max_seconds', 120)]:
        if type(config[field]) is not int or not 1 <= config[field] <= maximum:
            raise ProtocolError('INVALID_PROXY', 'finite proxy resource budgets required')
    if context.verify_mode != ssl.CERT_REQUIRED or context.minimum_version < ssl.TLSVersion.TLSv1_3:
        raise ProtocolError('INVALID_PROXY', 'mutual TLS 1.3 proxy context required')

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            stream, upstream = self.request, None
            deadline = time.monotonic()+config['max_seconds']
            def expire():
                for sock in (stream, upstream):
                    if sock is not None:
                        try: sock.shutdown(socket.SHUT_RDWR)
                        except OSError: pass
            timer = threading.Timer(config['max_seconds'], expire); timer.daemon = True; timer.start()
            try:
                stream.settimeout(min(5, config['max_seconds'])); stream.do_handshake()
                certificate = stream.getpeercert(binary_form=True)
                fingerprint = hashlib.sha256(certificate).hexdigest()
                if directory is None and fingerprint not in fingerprints:
                    raise ProtocolError('PROXY_DENIED', 'client certificate not approved')
                request = read_frame(stream)
                if directory is not None and isinstance(request, dict) and request.get('schema') == 'ziokt.proxy-discover.v1':
                    write_frame(stream, directory.exchange(request, fingerprint)); return
                if fingerprint not in fingerprints and (directory is None or not directory.certificate_admitted(fingerprint)):
                    raise ProtocolError('PROXY_DENIED', 'client certificate not approved')
                if not isinstance(request, dict) or set(request) != {'schema', 'host', 'port'} or request['schema'] != 'ziokt.proxy-connect.v1':
                    raise ProtocolError('INVALID_PROXY', 'exact proxy next-hop frame required')
                host, port = target_address(request['host'], request['port'])
                if target_key(host, port) in targets: target_carrier = targets[target_key(host, port)]
                elif directory is not None: target_carrier = directory.target_carrier(host, port)
                else: raise ProtocolError('PROXY_DENIED', 'next hop not approved')
                from .carrier import open_carrier
                upstream = open_carrier(host, port, target_carrier, timeout=min(config['max_seconds'], max(.001, deadline-time.monotonic())))
                write_frame(stream, {'ready': True})
                stream.settimeout(2); upstream.settimeout(2)
                total = 0
                while time.monotonic() < deadline:
                    readable = [stream] if stream.pending() else select.select([stream, upstream], [], [], min(1, max(0, deadline-time.monotonic())))[0]
                    for source in readable:
                        try: data = source.recv(16384)
                        except socket.timeout: continue
                        if not data: return
                        total += len(data)
                        if total > config['max_bytes']: return
                        (upstream if source is stream else stream).sendall(data)
            except (OSError, ProtocolError, ValueError):
                # No requests, certificates, addresses or raw exceptions logged.
                pass
            finally:
                timer.cancel()
                if upstream is not None: upstream.close()

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = False
        def __init__(self):
            self.slots = threading.BoundedSemaphore(config['max_connections'])
            self.active = set(); self.active_lock = threading.Lock()
            super().__init__((config['host'], config['port']), Handler)
        def get_request(self):
            raw, addr = super().get_request()
            try: return context.wrap_socket(raw, server_side=True, do_handshake_on_connect=False), addr
            except BaseException: raw.close(); raise
        def process_request(self, request, address):
            if not self.slots.acquire(False): self.shutdown_request(request); return
            with self.active_lock: self.active.add(request)
            try: super().process_request(request, address)
            except BaseException:
                with self.active_lock: self.active.discard(request)
                self.slots.release(); raise
        def process_request_thread(self, request, address):
            try: super().process_request_thread(request, address)
            finally:
                with self.active_lock: self.active.discard(request)
                self.slots.release()
        def handle_error(self, *_): pass
        def server_close(self):
            with self.active_lock:
                for sock in self.active:
                    try: sock.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
            super().server_close()
            if directory is not None and directory.worker is not None: directory.worker.close()
    if ipaddress.ip_address(config['host']).version == 6:
        Server.address_family = socket.AF_INET6
    server = Server()
    if directory is not None and 'signing_key' in directory_config:
        from .peer_directory import DiscoveryWorker
        if directory.worker is None: directory.worker = DiscoveryWorker(directory, directory_config)
        directory.worker.start()
    return server


def load_proxy(path):
    config = strict_json(secure_read(path))
    if not isinstance(config, dict) or config.get('enabled') is not True:
        raise ProtocolError('PROXY_DISABLED', 'peer proxy must be explicitly enabled')
    for field in ('certificate', 'private_key', 'ca'):
        if not isinstance(config.get(field), str) or not Path(config[field]).is_absolute() or '..' in Path(config[field]).parts:
            raise ProtocolError('INVALID_PROXY', 'fixed absolute proxy TLS material paths required')
    return config

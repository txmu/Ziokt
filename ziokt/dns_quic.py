"""DNS-over-QUIC (DoQ, RFC 9250) and DNS-over-HTTP/3 (DoH3, RFC 9114).

Provides dedicated modern transport interfaces for whole-device DNS:
- DoQ: RFC 9250 over dedicated QUIC on UDP port 853 (ALPN 'doq').
- DoH3: RFC 9114 over HTTP/3 on UDP port 443 / high-port (ALPN 'h3').
"""
import asyncio
import base64
import os
from pathlib import Path
import struct
import threading
from urllib.parse import parse_qs, urlsplit

from .protocol import ProtocolError
from .dns_wire import answer
from .naming import NameNetworks

try:
    from aioquic.asyncio import QuicConnectionProtocol, serve
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.quic.events import StreamDataReceived
    from aioquic.h3.connection import H3Connection
    from aioquic.h3.events import HeadersReceived, DataReceived
    import aioquic.tls
    if hasattr(aioquic.tls.Context, '_server_handle_hello'):
        _orig_handle_hello = aioquic.tls.Context._server_handle_hello
        def _hooked_server_handle_hello(self, input_buf, initial_buf, handshake_buf):
            pos = input_buf.tell()
            try:
                peer_hello = aioquic.tls.pull_client_hello(input_buf)
                self._server_name = peer_hello.server_name
            except Exception:
                pass
            input_buf.seek(pos)
            return _orig_handle_hello(self, input_buf, initial_buf, handshake_buf)
        aioquic.tls.Context._server_handle_hello = _hooked_server_handle_hello
    QUIC_AVAILABLE = True
except ImportError:
    QUIC_AVAILABLE = False


def _get_cert_and_key(tls_cert=None, tls_key=None, host='127.0.0.1'):
    from .tls_helper import get_cert_and_key
    return get_cert_and_key(tls_cert, tls_key, host=host)


class DoQServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, resolver=None, limits=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.resolver = resolver
        self.limits = limits
        self.buffers = {}

    def quic_event_received(self, event):
        if not isinstance(event, StreamDataReceived):
            return
        stream_id = event.stream_id
        buf = self.buffers.setdefault(stream_id, bytearray())
        buf.extend(event.data)
        if len(buf) < 2:
            return
        length = struct.unpack('!H', buf[:2])[0]
        if not 12 <= length <= 4096:
            self.buffers.pop(stream_id, None)
            return
        if len(buf) < 2 + length:
            return
        query = bytes(buf[2:2 + length])
        del self.buffers[stream_id]

        client_addr = self._transport.get_extra_info('peername')
        ip = client_addr[0] if client_addr else '127.0.0.1'
        if self.limits and not self.limits.admit(ip):
            return

        active = self.resolver
        sni = getattr(self._quic, 'server_name', None) or getattr(getattr(self._quic, 'tls', None), '_server_name', None) or getattr(self._quic, 'sni', None)
        if sni and isinstance(self.resolver, NameNetworks):
            first = sni.split('.')[0]
            if first in self.resolver.realms:
                active = self.resolver.view(first)
            elif sni not in ('dns.ziokt.com', 'localhost') and '.' in sni:
                try: active = self.resolver.view(first)
                except ProtocolError: active = None

        if active is None:
            ident = struct.unpack('!H', query[:2])[0]
            resp = struct.pack('!6H', ident, 0x8105, 1, 0, 0, 0) + query[12:]
        else:
            resp = answer(query, active, tcp=True)

        self._quic.send_stream_data(stream_id, struct.pack('!H', len(resp)) + resp, end_stream=True)
        self.transmit()


class DoH3ServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, resolver=None, limits=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.resolver = resolver
        self.limits = limits
        self.h3 = H3Connection(self._quic)
        self.streams = {}

    def quic_event_received(self, event):
        for h3_event in self.h3.handle_event(event):
            stream_id = getattr(h3_event, 'stream_id', None)
            if isinstance(h3_event, HeadersReceived):
                info = self.streams.setdefault(stream_id, {'headers': dict(h3_event.headers), 'data': bytearray()})
                headers = info['headers']
                path = headers.get(b':path', b'').decode('latin1', 'replace')
                method = headers.get(b':method', b'').decode('latin1', 'replace')
                if method == 'GET' and '?dns=' in path:
                    b64 = path.split('?dns=')[1].split('&')[0]
                    try:
                        raw = base64.urlsafe_b64decode(b64 + '=' * ((-len(b64)) % 4))
                        self._respond(stream_id, raw, path)
                    except Exception:
                        self._send_error(stream_id, 400)
            elif isinstance(h3_event, DataReceived):
                info = self.streams.get(stream_id)
                if info:
                    info['data'].extend(h3_event.data)
                    if h3_event.stream_ended:
                        headers = info['headers']
                        method = headers.get(b':method', b'').decode('latin1', 'replace')
                        ctype = headers.get(b'content-type', b'').decode('latin1', 'replace')
                        if method == 'POST' and ctype != 'application/dns-message':
                            self._send_error(stream_id, 415)
                            return
                        path = headers.get(b':path', b'').decode('latin1', 'replace')
                        self._respond(stream_id, bytes(info['data']), path)

    def _resolve_active(self, path):
        parts = urlsplit(path)
        active = self.resolver
        if parts.path != '/dns-query':
            segments = parts.path.split('/')
            if len(segments) != 4 or segments[1] != 'realms' or segments[3] != 'dns-query' or not isinstance(self.resolver, NameNetworks):
                return None, 404
            try:
                active = self.resolver.view(segments[2])
            except ProtocolError:
                return None, 404
        else:
            sni = getattr(self._quic, 'server_name', None) or getattr(getattr(self._quic, 'tls', None), '_server_name', None) or getattr(self._quic, 'sni', None)
            if sni and isinstance(self.resolver, NameNetworks):
                first = sni.split('.')[0]
                if first in self.resolver.realms:
                    active = self.resolver.view(first)
                elif sni not in ('dns.ziokt.com', 'localhost') and '.' in sni:
                    try: active = self.resolver.view(first)
                    except ProtocolError: return None, 404
        return active, 200

    def _respond(self, stream_id, query_bytes, path):
        client_addr = self._transport.get_extra_info('peername')
        ip = client_addr[0] if client_addr else '127.0.0.1'
        if self.limits and not self.limits.admit(ip):
            self._send_error(stream_id, 429)
            return
        active, status = self._resolve_active(path)
        if active is None:
            self._send_error(stream_id, status)
            return
        if not 12 <= len(query_bytes) <= 4096:
            self._send_error(stream_id, 400)
            return
        body = answer(query_bytes, active, tcp=True)
        self.h3.send_headers(stream_id, [
            (b':status', b'200'),
            (b'content-type', b'application/dns-message'),
            (b'cache-control', b'no-store'),
            (b'content-length', str(len(body)).encode()),
        ])
        self.h3.send_data(stream_id, body, end_stream=True)
        self.streams.pop(stream_id, None)
        self.transmit()

    def _send_error(self, stream_id, code):
        self.h3.send_headers(stream_id, [(b':status', str(code).encode())], end_stream=True)
        self.streams.pop(stream_id, None)
        self.transmit()


class QuicServerRunner:
    """Synchronous interface compatible with socketserver for gateway & CLI."""
    def __init__(self, mode, resolver, host, port, tls_cert=None, tls_key=None, limits=None):
        self.mode = mode
        self.resolver = resolver
        self.host = host
        self.port = port
        self.limits = limits
        self.tls_cert, self.tls_key, self.td = _get_cert_and_key(tls_cert, tls_key, host=host)
        self.loop = None
        self.server = None
        self.thread = None
        self.server_address = (host, port)
        self.started = threading.Event()
        self.stopped = threading.Event()

    def start(self):
        if not QUIC_AVAILABLE:
            raise RuntimeError('aioquic is required for native DoQ / DoH3')
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.started.wait(5.0)

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        alpn = ['doq'] if self.mode == 'doq' else ['h3']
        config = QuicConfiguration(is_client=False, alpn_protocols=alpn)
        config.load_cert_chain(self.tls_cert, self.tls_key)

        protocol_cls = DoQServerProtocol if self.mode == 'doq' else DoH3ServerProtocol

        def create_protocol(*args, **kwargs):
            return protocol_cls(*args, resolver=self.resolver, limits=self.limits, **kwargs)

        async def serve_quic():
            self.server = await serve(self.host, self.port, configuration=config, create_protocol=create_protocol)
            actual_port = self.server._transport.get_extra_info('sockname')[1]
            self.server_address = (self.host, actual_port)
            self.started.set()
            while not self.stopped.is_set():
                await asyncio.sleep(0.5)
            self.server.close()

        self.loop.run_until_complete(serve_quic())
        self.loop.close()

    def serve_forever(self):
        if self.thread is None:
            self.start()
        self.thread.join()

    def shutdown(self):
        self.stopped.set()

    def server_close(self):
        self.shutdown()
        if self.td is not None:
            try: self.td.cleanup()
            except Exception: pass

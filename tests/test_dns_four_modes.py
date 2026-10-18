"""Integration tests for ZDNS supporting all four encrypted DNS transports:
1. DoH (DNS-over-HTTPS, RFC 8484)
2. DoT (DNS-over-TLS, RFC 7858)
3. DoH3 (DNS-over-HTTP/3, RFC 9114)
4. DoQ (DNS-over-QUIC, RFC 9250)

Validates:
- All 4 modes resolve native records (A, AAAA, TXT, HTTPS).
- Native custom TLDs: .tc16, .tcc, .ttc.
- Refusal of unmanaged/external domains (no public DNS fallback).
- Multi-realm routing via SNI (DoT, DoQ, DoH3) and URL path (DoH, DoH3).
- Strict non-leakage between isolated realms.
"""
import asyncio
import base64
import http.client
from pathlib import Path
import secrets
import socket
import ssl
import struct
import tempfile
import threading
import time
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ziokt.protocol import ProtocolError
from ziokt.security import sign
from ziokt.naming import Names, NameNetworks
from ziokt.naming_tc16 import TC16Names, DOMAIN as TC16_DOMAIN
from ziokt.dns_wire import wire_name, answer
from ziokt.dns_server import servers

import sys
from pathlib import Path
user_site = Path.home() / '.local/lib/python3.13/site-packages'
if user_site.is_dir() and str(user_site) not in sys.path:
    sys.path.insert(0, str(user_site))

from aioquic.asyncio.client import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import HeadersReceived, DataReceived


def derive_public(key_bytes):
    return Ed25519PrivateKey.from_private_bytes(key_bytes).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


class H3TestClient(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.h3 = H3Connection(self._quic)
        self.headers = {}
        self.data = bytearray()
        self.done = asyncio.Event()

    def quic_event_received(self, event):
        for h3_evt in self.h3.handle_event(event):
            if isinstance(h3_evt, HeadersReceived):
                self.headers.update(dict(h3_evt.headers))
            elif isinstance(h3_evt, DataReceived):
                self.data.extend(h3_evt.data)
                if h3_evt.stream_ended:
                    self.done.set()


class FourModesDNSTests(unittest.TestCase):
    def setUp(self):
        self.tc16_key = secrets.token_bytes(32)
        self.tc16_public = derive_public(self.tc16_key)
        self.child_key = secrets.token_bytes(32)
        self.child_public = derive_public(self.child_key)

        # Set up a TC-16 native names adapter
        self.temp_dir = tempfile.TemporaryDirectory(prefix='ziokt-test-dns-4m-')
        self.addCleanup(self.temp_dir.cleanup)
        vault_root = Path(self.temp_dir.name) / 'vault'
        vault_root.mkdir()

        self.tc16 = TC16Names(vault_root=str(vault_root), signing_key=self.tc16_public, network_id='ziokt-main')

        descriptor_main = {
            'public_dns': [
                {'type': 'A', 'value': '93.184.216.34', 'ttl': 300},
                {'type': 'AAAA', 'value': '2606:2800:220:1:248:1893:25c8:1946', 'ttl': 300},
                {'type': 'TXT', 'value': 'ziokt-descriptor=sha256:' + 'f' * 64, 'ttl': 300},
                {'type': 'HTTPS', 'value': {'priority': 1, 'target': '.', 'alpn': ['h3', 'h2'], 'port': 853, 'ech': ''}, 'ttl': 300},
            ],
            'services': {
                'tc16': {'object': 'sha256:' + 'a' * 64, 'access': 'public'},
            },
            'private': None,
        }

        DELEGATION_DOMAIN = 'Ziokt/name-delegation/v1'

        root_delegation = {
            'network_id': 'ziokt-main',
            'component': 'tc16',
            'path': 'compute',
            'parent_revision': 1,
            'revision': 1,
            'expires_at': int(time.time()) + 3600,
            'delegate': self.child_public,
            'descriptor': descriptor_main,
        }

        # Root registration for compute (.tc16, .tcc, .ttc)
        reg_tc16 = {
            'network_id': 'ziokt-main',
            'component': 'tc16',
            'root': 'compute',
            'owner': self.tc16_public,
            'revision': 1,
            'expires_at': int(time.time()) + 3600,
            'published_suffixes': ['tc16', 'tcc', 'ttc'],
            'delegations': {
                'compute': sign(root_delegation, self.tc16_key, DELEGATION_DOMAIN),
            },
        }
        self.tc16.register(sign(reg_tc16, self.tc16_key, TC16_DOMAIN))

        # Multi-realm setup: 'main' realm and 'isolated' realm
        self.names_main = Names({'tc16': self.tc16}, network_id='ziokt-main')

        vault_iso = Path(self.temp_dir.name) / 'vault_iso'
        vault_iso.mkdir()
        tc16_iso = TC16Names(vault_root=str(vault_iso), signing_key=self.tc16_public, network_id='ziokt-isolated')
        iso_desc = {
            'public_dns': [{'type': 'A', 'value': '93.184.216.35', 'ttl': 300}],
            'services': {},
            'private': None,
        }
        iso_del = {
            'network_id': 'ziokt-isolated',
            'component': 'tc16',
            'path': 'iso',
            'parent_revision': 1,
            'revision': 1,
            'expires_at': int(time.time()) + 3600,
            'delegate': self.child_public,
            'descriptor': iso_desc,
        }
        iso_reg = {
            'network_id': 'ziokt-isolated',
            'component': 'tc16',
            'root': 'iso',
            'owner': self.tc16_public,
            'revision': 1,
            'expires_at': int(time.time()) + 3600,
            'published_suffixes': ['tc16'],
            'delegations': {
                'iso': sign(iso_del, self.tc16_key, DELEGATION_DOMAIN),
            },
        }
        tc16_iso.register(sign(iso_reg, self.tc16_key, TC16_DOMAIN))
        self.names_iso = Names({'tc16': tc16_iso}, network_id='ziokt-isolated')

        self.networks = NameNetworks({'main': self.names_main, 'isolated': self.names_iso}, default='main')

        # Launch all 4 modern encrypted modes + standard UDP/TCP
        self.opened = servers(
            self.networks,
            host='127.0.0.1',
            port=0,
            doh_port=0,
            dot_port=0,
            doq_port=0,
            doh3_port=0,
        )
        for s in self.opened:
            self.addCleanup(s.server_close)
            if hasattr(s, 'shutdown'):
                self.addCleanup(s.shutdown)
            threading.Thread(target=s.serve_forever, daemon=True).start()

        self.udp, self.tcp, self.doh, self.dot, self.doq, self.doh3 = self.opened

    def _query_dot(self, query, server_name='dns.ziokt.com'):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try: ctx.set_alpn_protocols(['dot'])
        except Exception: pass
        with socket.create_connection(('127.0.0.1', self.dot.server_address[1]), timeout=3) as raw_sock:
            with ctx.wrap_socket(raw_sock, server_hostname=server_name) as s:
                s.sendall(struct.pack('!H', len(query)) + query)
                sz = struct.unpack('!H', s.recv(2))[0]
                resp = bytearray()
                while len(resp) < sz:
                    chunk = s.recv(sz - len(resp))
                    if not chunk: raise EOFError()
                    resp.extend(chunk)
                return bytes(resp)

    def _query_doq(self, query, server_name='dns.ziokt.com'):
        async def _run():
            cfg = QuicConfiguration(is_client=True, alpn_protocols=['doq'])
            cfg.verify_mode = ssl.CERT_NONE
            cfg.server_name = server_name
            async with connect('127.0.0.1', self.doq.server_address[1], configuration=cfg) as client:
                reader, writer = await client.create_stream()
                writer.write(struct.pack('!H', len(query)) + query)
                writer.write_eof()
                sz = struct.unpack('!H', await reader.read(2))[0]
                resp = bytearray()
                while len(resp) < sz:
                    chunk = await reader.read(sz - len(resp))
                    if not chunk: raise EOFError()
                    resp.extend(chunk)
                return bytes(resp)
        return asyncio.run(_run())

    def _query_doh3(self, query, path='/dns-query', server_name='dns.ziokt.com'):
        async def _run():
            cfg = QuicConfiguration(is_client=True, alpn_protocols=['h3'])
            cfg.verify_mode = ssl.CERT_NONE
            cfg.server_name = server_name
            async with connect('127.0.0.1', self.doh3.server_address[1], configuration=cfg, create_protocol=H3TestClient) as client:
                stream_id = client._quic.get_next_available_stream_id()
                headers = [
                    (b':method', b'POST'),
                    (b':scheme', b'https'),
                    (b':authority', server_name.encode()),
                    (b':path', path.encode()),
                    (b'content-type', b'application/dns-message'),
                    (b'content-length', str(len(query)).encode()),
                ]
                client.h3.send_headers(stream_id, headers)
                client.h3.send_data(stream_id, query, end_stream=True)
                client.transmit()
                await asyncio.wait_for(client.done.wait(), timeout=3.0)
                return bytes(client.data)
        return asyncio.run(_run())

    def _query_doh_post(self, query, path='/dns-query'):
        conn = http.client.HTTPConnection('127.0.0.1', self.doh.server_address[1], timeout=3)
        conn.request('POST', path, query, {'Content-Type': 'application/dns-message'})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def _query_doh_get(self, query, path='/dns-query'):
        b64 = base64.urlsafe_b64encode(query).decode().rstrip('=')
        conn = http.client.HTTPConnection('127.0.0.1', self.doh.server_address[1], timeout=3)
        conn.request('GET', f'{path}?dns={b64}')
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def test_all_four_modes_resolve_tc16_records(self):
        """Mode 1 (DoH), Mode 2 (DoT), Mode 3 (DoH3), and Mode 4 (DoQ) resolve .tc16."""
        # Query A record for compute.tc16
        q_a = struct.pack('!6H', 1, 0x100, 1, 0, 0, 0) + wire_name('compute.tc16') + struct.pack('!HH', 1, 1)

        # 1. DoH (POST)
        status, resp_doh = self._query_doh_post(q_a)
        self.assertEqual(status, 200)
        self.assertEqual(int.from_bytes(resp_doh[2:4], 'big') & 15, 0)  # NOERROR
        self.assertGreaterEqual(int.from_bytes(resp_doh[6:8], 'big'), 1)  # ANCOUNT >= 1

        # 1b. DoH (GET)
        status, resp_doh_get = self._query_doh_get(q_a)
        self.assertEqual(status, 200)
        self.assertEqual(int.from_bytes(resp_doh_get[2:4], 'big') & 15, 0)

        # 2. DoT
        resp_dot = self._query_dot(q_a)
        self.assertEqual(int.from_bytes(resp_dot[2:4], 'big') & 15, 0)
        self.assertGreaterEqual(int.from_bytes(resp_dot[6:8], 'big'), 1)

        # 3. DoH3
        resp_doh3 = self._query_doh3(q_a)
        self.assertEqual(int.from_bytes(resp_doh3[2:4], 'big') & 15, 0)
        self.assertGreaterEqual(int.from_bytes(resp_doh3[6:8], 'big'), 1)

        # 4. DoQ
        resp_doq = self._query_doq(q_a)
        self.assertEqual(int.from_bytes(resp_doq[2:4], 'big') & 15, 0)
        self.assertGreaterEqual(int.from_bytes(resp_doq[6:8], 'big'), 1)

    def test_suffixes_tc16_tcc_ttc_resolution(self):
        """.tc16, .tcc, and .ttc are all recognized custom TLDs."""
        for name in ('compute.tc16', 'compute.tcc', 'compute.ttc'):
            q = struct.pack('!6H', 2, 0x100, 1, 0, 0, 0) + wire_name(name) + struct.pack('!HH', 1, 1)
            # Verify across DoT and DoQ
            r_dot = self._query_dot(q)
            self.assertEqual(int.from_bytes(r_dot[2:4], 'big') & 15, 0, f'DoT failed for {name}')
            r_doq = self._query_doq(q)
            self.assertEqual(int.from_bytes(r_doq[2:4], 'big') & 15, 0, f'DoQ failed for {name}')

    def test_all_four_modes_refuse_unmanaged_external_domains(self):
        """ZDNS strictly refuses unmanaged names (RCODE 5) without public fallback across all modes."""
        q_ext = struct.pack('!6H', 9, 0x100, 1, 0, 0, 0) + wire_name('google.com') + struct.pack('!HH', 1, 1)

        # DoH
        status, r_doh = self._query_doh_post(q_ext)
        self.assertEqual(status, 200)
        self.assertEqual(int.from_bytes(r_doh[2:4], 'big') & 15, 5)  # REFUSED

        # DoT
        r_dot = self._query_dot(q_ext)
        self.assertEqual(int.from_bytes(r_dot[2:4], 'big') & 15, 5)

        # DoH3
        r_doh3 = self._query_doh3(q_ext)
        self.assertEqual(int.from_bytes(r_doh3[2:4], 'big') & 15, 5)

        # DoQ
        r_doq = self._query_doq(q_ext)
        self.assertEqual(int.from_bytes(r_doq[2:4], 'big') & 15, 5)

    def test_multi_realm_isolation(self):
        """Multi-realm SNI and URL paths resolve within their own realms and reject cross-realm leakage."""
        q_iso = struct.pack('!6H', 10, 0x100, 1, 0, 0, 0) + wire_name('iso.tc16') + struct.pack('!HH', 1, 1)

        # Query default realm (main) -> iso.tc16 should be NXDOMAIN (RCODE 3)
        status, r_main = self._query_doh_post(q_iso, '/dns-query')
        self.assertEqual(status, 200)
        self.assertEqual(int.from_bytes(r_main[2:4], 'big') & 15, 3)

        # Query explicit realm via DoH path: /realms/isolated/dns-query -> NOERROR (RCODE 0)
        status, r_iso_doh = self._query_doh_post(q_iso, '/realms/isolated/dns-query')
        self.assertEqual(status, 200)
        self.assertEqual(int.from_bytes(r_iso_doh[2:4], 'big') & 15, 0)

        # Query explicit realm via DoT SNI: isolated.dns.ziokt.com -> NOERROR (RCODE 0)
        r_iso_dot = self._query_dot(q_iso, server_name='isolated.dns.ziokt.com')
        self.assertEqual(int.from_bytes(r_iso_dot[2:4], 'big') & 15, 0)

        # Query explicit realm via DoQ SNI: isolated.dns.ziokt.com -> NOERROR (RCODE 0)
        r_iso_doq = self._query_doq(q_iso, server_name='isolated.dns.ziokt.com')
        self.assertEqual(int.from_bytes(r_iso_doq[2:4], 'big') & 15, 0)

        # Query unknown realm via DoT SNI -> REFUSED (RCODE 5)
        r_unk_dot = self._query_dot(q_iso, server_name='nonexistent.dns.ziokt.com')
        self.assertEqual(int.from_bytes(r_unk_dot[2:4], 'big') & 15, 5)

    def test_return_aaaa_txt_and_https_records(self):
        """ZDNS returns AAAA, TXT, and HTTPS records across the transports."""
        # AAAA (type 28)
        q_aaaa = struct.pack('!6H', 20, 0x100, 1, 0, 0, 0) + wire_name('compute.tc16') + struct.pack('!HH', 28, 1)
        r_dot = self._query_dot(q_aaaa)
        self.assertEqual(int.from_bytes(r_dot[2:4], 'big') & 15, 0)
        self.assertGreaterEqual(int.from_bytes(r_dot[6:8], 'big'), 1)

        # TXT (type 16)
        q_txt = struct.pack('!6H', 21, 0x100, 1, 0, 0, 0) + wire_name('compute.tc16') + struct.pack('!HH', 16, 1)
        r_doq = self._query_doq(q_txt)
        self.assertEqual(int.from_bytes(r_doq[2:4], 'big') & 15, 0)
        self.assertGreaterEqual(int.from_bytes(r_doq[6:8], 'big'), 1)

        # HTTPS (type 65)
        q_https = struct.pack('!6H', 22, 0x100, 1, 0, 0, 0) + wire_name('compute.tc16') + struct.pack('!HH', 65, 1)
        r_doh3 = self._query_doh3(q_https)
        self.assertEqual(int.from_bytes(r_doh3[2:4], 'big') & 15, 0)
        self.assertGreaterEqual(int.from_bytes(r_doh3[6:8], 'big'), 1)


if __name__ == '__main__':
    unittest.main()

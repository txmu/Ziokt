"""SAM stream lifecycle, actual TLS exchange and no destination DNS/downgrade."""
import base64
import hashlib
import json
from pathlib import Path
import secrets
import socket
import socketserver
import tempfile
import threading
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from test_community_network import certificates
from ziokt.community import Community, RIGHTS, create_policy
from ziokt.community_network import CommunityEndpoint, sync_remote
from ziokt.i2p import close_sessions, connect_i2p, i2p_address
from ziokt.protocol import ProtocolError, make_private
from ziokt.remote import remote_server, tls_context
from ziokt.security import sign

I2P_HOST = base64.b32encode(hashlib.sha256(b'i2p-test-destination').digest()).decode().lower().rstrip('=')+'.b32.i2p'


class SamBridge(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    def __init__(self, destination, port, *, refused=False):
        self.commands, self.sessions = [], set()
        bridge = self
        class Handler(socketserver.BaseRequestHandler):
            def line(self):
                data = bytearray()
                while len(data) < 8192:
                    part = self.request.recv(1)
                    if not part: raise OSError('EOF')
                    if part == b'\n': return data.decode()
                    data.extend(part)
                raise OSError('budget')
            def handle(self):
                self.request.settimeout(30)
                try:
                    hello = self.line(); bridge.commands.append(hello)
                    if hello != 'HELLO VERSION MIN=3.1 MAX=3.1': raise OSError('version')
                    self.request.sendall(b'HELLO REPLY RESULT=OK VERSION=3.1\n')
                    command = self.line(); bridge.commands.append(command)
                    fields = dict(token.split('=', 1) for token in command.split() if '=' in token)
                    if command.startswith('SESSION CREATE '):
                        bridge.sessions.add(fields['ID'])
                        self.request.sendall(b'SESSION STATUS RESULT=OK DESTINATION=private-not-exported\n')
                        try: self.request.recv(1)
                        finally: bridge.sessions.discard(fields['ID'])
                        return
                    if not command.startswith('STREAM CONNECT ') or fields['ID'] not in bridge.sessions or fields['DESTINATION'] != destination:
                        raise OSError('unapproved')
                    if refused:
                        self.request.sendall(b'STREAM STATUS RESULT=CANT_REACH_PEER\n'); return
                    with socket.create_connection(('127.0.0.1', port), timeout=5) as upstream:
                        self.request.sendall(b'STREAM STATUS RESULT=OK\n')
                        def copy(source, target):
                            try:
                                while part := source.recv(16384): target.sendall(part)
                            except OSError: pass
                            try: target.shutdown(socket.SHUT_WR)
                            except OSError: pass
                        worker = threading.Thread(target=copy, args=(self.request, upstream), daemon=True)
                        worker.start(); copy(upstream, self.request); worker.join(5)
                except OSError: pass
        super().__init__(('127.0.0.1', 0), Handler)


class I2PTests(unittest.TestCase):
    def setUp(self):
        close_sessions(); self.addCleanup(close_sessions)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private, key = secrets.token_bytes(32), secrets.token_bytes(32)
        self.public = sign({}, self.private, 'test')['public_key']
        policy = create_policy(self.private, 'i2p-village', {self.public: sorted(RIGHTS)})
        self.source = Community(self.root/'source', policy, self.public, key); self.addCleanup(self.source.close)
        self.target = Community(self.root/'target', policy, self.public, key); self.addCleanup(self.target.close)
        ca, pairs = certificates(self.root, I2P_HOST)
        self.context = tls_context(*pairs['client'][:2], ca)
        fingerprint = hashlib.sha256(pairs['client'][2].public_bytes(serialization.Encoding.DER)).hexdigest()
        trusted = {fingerprint: {'public_key': self.public, 'methods': ['community.status', 'community.checkpoint.create', 'community.checkpoint.get', 'community.checkpoint.release'], 'providers': ['i2p-village']}}
        self.server = remote_server({'enabled': True, 'federation_id': 'i2p-village', 'providers': []},
            tls_context(*pairs['server'][:2], ca, server=True), self.root/'replay.sqlite', trusted,
            allow_mutations=True, community=CommunityEndpoint(self.source, self.private))
        self.start(self.server)
        self.bridge = SamBridge(I2P_HOST, self.server.server_port); self.start(self.bridge)
        self.carrier = {'kind': 'i2p-sam', 'proxy_host': '127.0.0.1', 'proxy_port': self.bridge.server_address[1]}
        self.endpoint = {'host': I2P_HOST, 'port': 443, 'carrier': self.carrier,
                         'connection_policy': {'mode': 'anonymous', 'allow_direct_fallback': False}}
        self.source.publish(self.private, 'wiki', 'home', {'title': 'I2P', 'text': 'private I2P community stream'})
    def start(self, server):
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def stop(): close_sessions(); server.shutdown(); server.server_close(); thread.join(5)
        self.addCleanup(stop)

    def test_real_mtls_sync_reuses_session_and_never_resolves_i2p_destination_locally(self):
        original = socket.getaddrinfo
        def dns(host, *args, **kwargs):
            self.assertEqual(host, '127.0.0.1')
            return original(host, *args, **kwargs)
        with patch('socket.getaddrinfo', side_effect=dns):
            sync_remote(self.target, self.endpoint, self.context, self.private, publisher=self.public)
            sync_remote(self.target, self.endpoint, self.context, self.private, publisher=self.public)
        self.assertEqual(self.target.view('wiki'), self.source.view('wiki'))
        sessions = [line for line in self.bridge.commands if line.startswith('SESSION CREATE')]
        self.assertEqual(len(sessions), 1)
        self.assertIn('SIGNATURE_TYPE=7', sessions[0]); self.assertIn('i2cp.leaseSetEncType=4', sessions[0])
        self.assertGreater(len([line for line in self.bridge.commands if line.startswith('STREAM CONNECT')]), 2)

    def test_invalid_destinations_and_nonlocal_sam_are_rejected_before_connect(self):
        self.assertEqual(i2p_address(I2P_HOST), I2P_HOST)
        for host in ['example.com', 'abc.i2p', I2P_HOST.upper(), 'a'*51+'b.b32.i2p', I2P_HOST+'\nSTREAM CONNECT']:
            with patch('socket.create_connection') as dial:
                with self.assertRaises(ProtocolError): connect_i2p(host, 443, self.carrier)
                dial.assert_not_called()
        with self.assertRaises(ProtocolError): connect_i2p(I2P_HOST, 443, {**self.carrier, 'proxy_host': '8.8.8.8'})

    def test_failed_stream_has_no_direct_or_other_carrier_retry(self):
        bridge = SamBridge(I2P_HOST, self.server.server_port, refused=True); self.start(bridge)
        with self.assertRaises(ProtocolError) as error:
            connect_i2p(I2P_HOST, 443, {**self.carrier, 'proxy_port': bridge.server_address[1]}, timeout=5)
        self.assertEqual(error.exception.code, 'CARRIER_UNAVAILABLE')
        self.assertEqual(len([line for line in bridge.commands if line.startswith('STREAM CONNECT')]), 1)

    def test_keyless_peer_multihop_reaches_i2p_final_destination(self):
        from ziokt.peer_proxy import proxy_server
        hops = []
        target = {'host':I2P_HOST,'port':443,'carrier':self.carrier}
        for index in range(2):
            material = self.root/f'proxy{index}'; material.mkdir()
            ca,pairs = certificates(material,'127.0.0.1')
            fp = hashlib.sha256(pairs['client'][2].public_bytes(serialization.Encoding.DER)).hexdigest()
            server = proxy_server({'schema':'ziokt.peer-proxy.v1','enabled':True,'host':'127.0.0.1','port':0,
                'trusted_clients':[fp],'targets':[target],'max_connections':4,'max_bytes':1024*1024,'max_seconds':30},
                tls_context(*pairs['server'][:2],ca,server=True))
            self.start(server)
            config = material/'client.json'
            config.write_text(json.dumps({'schema':'ziokt.remote.v1','host':'127.0.0.1','port':server.server_address[1],
                'certificate':str(pairs['client'][0]),'private_key':str(pairs['client'][1]),'ca':str(ca)})); make_private(config)
            hops.insert(0,{'host':'127.0.0.1','port':server.server_address[1],'tls_config':str(config)})
            target = {'host':'127.0.0.1','port':server.server_address[1]}
        endpoint = {**self.endpoint,'carrier':{'kind':'peer-multihop','hops':hops},
            'connection_policy':{'mode':'peer-multihop','allow_direct_fallback':False}}
        sync_remote(self.target,endpoint,self.context,self.private,publisher=self.public)
        self.assertEqual(self.target.view('wiki'),self.source.view('wiki'))


if __name__ == '__main__': unittest.main()

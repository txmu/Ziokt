"""Real user-operated TLS proxies with no Tor, I2P or community content keys."""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from test_community_network import certificates
from ziokt.community import Community, RIGHTS, create_policy
from ziokt.community_cli import register, execute
from ziokt.community_network import CommunityEndpoint, sync_remote, push_remote
from ziokt.peer_proxy import proxy_server, connect_peer, read_frame, write_frame, load_proxy
from ziokt.protocol import ProtocolError, make_private
from ziokt.remote import remote_server, tls_context, load_remote
from ziokt.routes import resolve_endpoint
from ziokt.security import sign


class PeerProxyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private, self.key = secrets.token_bytes(32), secrets.token_bytes(32)
        self.public = sign({}, self.private, 'test')['public_key']
        self.policy = create_policy(self.private, 'peers', {self.public: sorted(RIGHTS)})
        self.source = Community(self.root/'source', self.policy, self.public, self.key); self.addCleanup(self.source.close)
        self.target = Community(self.root/'target', self.policy, self.public, self.key); self.addCleanup(self.target.close)
        material = self.root/'target-tls'; material.mkdir()
        self.ca, self.pairs = certificates(material, '127.0.0.1')
        self.context = tls_context(*self.pairs['client'][:2], self.ca)
        fingerprint = hashlib.sha256(self.pairs['client'][2].public_bytes(serialization.Encoding.DER)).hexdigest()
        methods = ['community.status', 'community.checkpoint.create', 'community.checkpoint.get', 'community.checkpoint.release', 'community.event.put', 'community.blob.put']
        self.destination = remote_server({'enabled': True, 'federation_id': 'peers', 'providers': []},
            tls_context(*self.pairs['server'][:2], self.ca, server=True), self.root/'replay.sqlite',
            {fingerprint: {'public_key': self.public, 'methods': methods, 'providers': ['peers']}},
            allow_mutations=True, community=CommunityEndpoint(self.source, self.private))
        self.start(self.destination)
        self.source.publish(self.private, 'wiki', 'secret', {'title': 'Private', 'text': 'opaque through ordinary peers'})
        self.last, self.last_hop = self.proxy('last', self.destination.server_port)
        self.first, self.first_hop = self.proxy('first', self.last.server_address[1])
        self.endpoint = {'host': '127.0.0.1', 'port': self.destination.server_port,
                         'connection_policy': {'mode': 'peer-multihop', 'allow_direct_fallback': False},
                         'carrier': {'kind': 'peer-multihop', 'hops': [self.first_hop, self.last_hop]}}

    def start(self, server):
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def stop(): server.shutdown(); server.server_close(); thread.join(5)
        self.addCleanup(stop)

    def proxy(self, name, destination_port, *, max_bytes=64*1024*1024, max_seconds=30, max_connections=4):
        material = self.root/name; material.mkdir()
        ca, pairs = certificates(material, '127.0.0.1')
        fingerprint = hashlib.sha256(pairs['client'][2].public_bytes(serialization.Encoding.DER)).hexdigest()
        config = {'schema': 'ziokt.peer-proxy.v1', 'enabled': True, 'host': '127.0.0.1', 'port': 0,
                  'trusted_clients': [fingerprint], 'targets': [{'host': '127.0.0.1', 'port': destination_port}],
                  'max_connections': max_connections, 'max_bytes': max_bytes, 'max_seconds': max_seconds}
        server = proxy_server(config, tls_context(*pairs['server'][:2], ca, server=True))
        self.start(server)
        client = {'schema': 'ziokt.remote.v1', 'host': '127.0.0.1', 'port': server.server_address[1],
                  'certificate': str(pairs['client'][0]), 'private_key': str(pairs['client'][1]), 'ca': str(ca)}
        path = material/'client.json'; path.write_text(json.dumps(client)); make_private(path)
        return server, {'host': '127.0.0.1', 'port': server.server_address[1], 'tls_config': str(path)}

    def test_two_keyless_proxies_carry_restricted_sync_and_push_with_only_first_hop_opened_locally(self):
        payload = b'private binary through peers\x00\xff'*2000
        manifest = self.source.put_file(payload)
        self.source.publish(self.private, 'files', 'large', {'name': 'large', **manifest})
        opened = []; original = socket.create_connection
        captures = []
        def observe(handler):
            original_handle = handler.handle
            def handle(connection):
                original_recv = connection.request.recv
                data = bytearray()
                def recv(size, *args):
                    part = original_recv(size, *args); data.extend(part)
                    return part
                connection.request.recv = recv
                try: original_handle(connection)
                finally: captures.append(bytes(data))
            return patch.object(handler, 'handle', handle)
        caller = threading.get_ident()
        def dial(target, *args, **kwargs):
            if threading.get_ident() == caller: opened.append(target)
            return original(target, *args, **kwargs)
        with patch('socket.create_connection', side_effect=dial), observe(self.first.RequestHandlerClass), observe(self.last.RequestHandlerClass):
            result = sync_remote(self.target, self.endpoint, self.context, self.private, publisher=self.public)
            self.assertFalse(result['runtime_ready'])
            self.assertEqual(self.target.view('wiki'), self.source.view('wiki'))
            self.assertEqual(self.target.get_file(manifest), payload)
            self.target.publish(self.private, 'chat', 'reply', {'channel': 'private', 'text': 'return through two proxies'})
            push_remote(self.target, self.endpoint, self.context, self.private)
        self.assertEqual(self.source.view('chat'), self.target.view('chat'))
        self.assertGreater(len(opened), 2)
        self.assertTrue(all(target == ('127.0.0.1', self.first.server_address[1]) for target in opened))
        self.assertTrue(captures)
        for data in captures:
            self.assertNotIn(b'opaque through ordinary peers', data)
            self.assertNotIn(b'return through two proxies', data)
            self.assertNotIn(self.key, data)
            self.assertNotIn(b'private binary through peers', data)
        for server in (self.first, self.last):
            self.assertFalse(hasattr(server, 'community'))
            self.assertFalse(hasattr(server, 'cipher'))

    def test_four_proxies_preserve_all_tls_layers(self):
        third, third_hop = self.proxy('third', self.first.server_address[1])
        fourth, fourth_hop = self.proxy('fourth', third.server_address[1])
        endpoint = {**self.endpoint, 'carrier': {'kind': 'peer-multihop', 'hops': [fourth_hop, third_hop, self.first_hop, self.last_hop]}}
        sync_remote(self.target, endpoint, self.context, self.private, publisher=self.public)
        self.assertEqual(self.target.view('wiki'), self.source.view('wiki'))

    def test_disabled_proxy_cannot_bind_and_cli_needs_no_community_key(self):
        with patch('socketserver.ThreadingTCPServer.__init__') as bind:
            with self.assertRaises(ProtocolError) as error:
                proxy_server({'schema': 'ziokt.peer-proxy.v1', 'enabled': False, 'host': '127.0.0.1', 'port': 0,
                              'trusted_clients': [], 'targets': [], 'max_connections': 1, 'max_bytes': 1, 'max_seconds': 1}, None)
            self.assertEqual(error.exception.code, 'PROXY_DISABLED'); bind.assert_not_called()
        parser = argparse.ArgumentParser(); register(parser.add_subparsers(dest='action', required=True))
        config_path = self.root/'disabled.json'; config_path.write_text(json.dumps({'enabled': False})); make_private(config_path)
        args = parser.parse_args(['community', 'proxy-serve', '--config', str(config_path)])
        self.assertFalse(hasattr(args, 'encryption_key'))
        with self.assertRaises(ProtocolError): execute(args)

    def test_explicit_candidate_loading_and_tor_claim_rejected(self):
        candidate = {**self.endpoint, 'approved': True, 'observed': {'end_to_end_authentication': True,
                     'encrypted_content': True, 'private_discovery': True, 'direct_fallback': False}}
        parent = {**self.endpoint, 'connection_policy': {'mode': 'approved-paths', 'allow_direct_fallback': False}, 'candidates': [candidate]}
        parent.pop('carrier')
        parent.update({'schema': 'ziokt.remote.v1', 'certificate': str(self.pairs['client'][0]),
                       'private_key': str(self.pairs['client'][1]), 'ca': str(self.ca)})
        path = self.root/'remote.json'; path.write_text(json.dumps(parent)); make_private(path)
        loaded = load_remote(path)
        resolved = resolve_endpoint('restricted', loaded)
        self.assertEqual(resolved['carrier']['kind'], 'peer-multihop')
        sync_remote(self.target, loaded, self.context, self.private, publisher=self.public)
        with self.assertRaises(ProtocolError):
            resolve_endpoint('restricted', {**self.endpoint, 'connection_policy': {'mode': 'anonymous', 'allow_direct_fallback': False}})

    def test_invalid_hops_fail_before_any_connection(self):
        for hops in [[self.first_hop], [self.first_hop]*2, [self.first_hop]*5,
                     [{**self.first_hop, 'host': 'untrusted.example'}, self.last_hop]]:
            with patch('socket.create_connection') as dial:
                with self.assertRaises(ProtocolError): connect_peer('127.0.0.1', self.destination.server_port, {'kind': 'peer-multihop', 'hops': hops})
                dial.assert_not_called()

    def test_proxy_rejects_unapproved_targets_and_client_certificates(self):
        config = load_remote(self.first_hop['tls_config'])
        context = tls_context(config['certificate'], config['private_key'], config['ca'])
        with socket.create_connection(('127.0.0.1', self.first.server_address[1])) as raw:
            with context.wrap_socket(raw, server_hostname='127.0.0.1') as stream:
                stream.settimeout(5)
                with patch('ziokt.peer_proxy.socket.create_connection') as dial:
                    write_frame(stream, {'schema': 'ziokt.proxy-connect.v1', 'host': '127.0.0.1', 'port': 1})
                    with self.assertRaises(OSError): read_frame(stream)
                    dial.assert_not_called()
        material = self.root/'first'
        unpinned = proxy_server({'schema': 'ziokt.peer-proxy.v1', 'enabled': True, 'host': '127.0.0.1', 'port': 0,
                                'trusted_clients': ['0'*64], 'targets': [{'host': '127.0.0.1', 'port': self.last.server_address[1]}],
                                'max_connections': 1, 'max_bytes': 4096, 'max_seconds': 5},
                               tls_context(material/'server.pem', material/'server.key', material/'ca.pem', server=True))
        self.start(unpinned)
        with socket.create_connection(('127.0.0.1', unpinned.server_address[1])) as raw:
            with context.wrap_socket(raw, server_hostname='127.0.0.1') as stream:
                stream.settimeout(5)
                with patch('ziokt.peer_proxy.socket.create_connection') as dial:
                    with self.assertRaises(OSError): read_frame(stream)
                    dial.assert_not_called()
        # A hop cannot borrow a different proxy's client config, even if its
        # proposed target happens to share the same literal address.
        with self.assertRaises((OSError, ProtocolError)):
            wrong = {**self.last_hop, 'tls_config': self.first_hop['tls_config']}
            connect_peer('127.0.0.1', self.destination.server_port, {'kind': 'peer-multihop', 'hops': [self.first_hop, wrong]})

    def test_proxy_byte_limit_aborts_without_direct_fallback(self):
        limited, hop = self.proxy('limited', self.last.server_address[1], max_bytes=16)
        endpoint = {**self.endpoint, 'carrier': {'kind': 'peer-multihop', 'hops': [hop, self.last_hop]}}
        with self.assertRaises((ProtocolError, OSError)):
            sync_remote(self.target, endpoint, self.context, self.private, publisher=self.public)
        self.assertEqual(len(self.target.view('wiki')['events']), 0)

    def test_connection_budget_and_idle_deadline_close_unauthenticated_connections(self):
        server, _ = self.proxy('idle', self.last.server_address[1], max_seconds=1, max_connections=1)
        with socket.create_connection(('127.0.0.1', server.server_address[1])) as first:
            deadline = time.monotonic()+2
            while time.monotonic() < deadline:
                with server.active_lock:
                    if server.active: break
                threading.Event().wait(0.01)
            with server.active_lock: self.assertEqual(len(server.active), 1)
            with socket.create_connection(('127.0.0.1', server.server_address[1])) as second:
                second.settimeout(2)
                try: self.assertEqual(second.recv(1), b'')
                except ConnectionResetError: pass
            first.settimeout(3)
            self.assertEqual(first.recv(1), b'')

    def test_final_application_certificate_is_still_verified_inside_tunnels(self):
        config = load_remote(self.first_hop['tls_config'])
        unrelated = tls_context(config['certificate'], config['private_key'], config['ca'])
        with self.assertRaises((OSError, ProtocolError)):
            sync_remote(self.target, self.endpoint, unrelated, self.private, publisher=self.public)
        self.assertEqual(len(self.target.view('wiki')['events']), 0)


if __name__ == '__main__': unittest.main()

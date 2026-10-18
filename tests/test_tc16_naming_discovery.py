"""Comprehensive integration tests for TC-16 native naming, service discovery,
cross-companion ownership verification (Tri, ZDA, UFS, dCPM, Shadow6+Extensions),
multi-realm isolation, Ed25519 delegations, and wire-level DNS (UDP/TCP/DoH).
"""
import copy
import http.client
import json
from pathlib import Path
import secrets
import socket
import struct
import tempfile
import threading
import time
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ziokt.protocol import ProtocolError
from ziokt.security import sign
from ziokt.naming import Names, NameNetworks, public_records, split_name
from ziokt.naming_tc16 import TC16Names, verify_tc16_service, DOMAIN as TC16_DOMAIN
from ziokt.naming_community import ComponentNames, DOMAIN as COMMUNITY_DOMAIN
from ziokt.companion_services import verify_companion_service
from ziokt.dns_wire import wire_name, answer
from ziokt.dns_server import servers

DELEGATION_DOMAIN = 'Ziokt/name-delegation/v1'


def derive_public(key_bytes):
    return Ed25519PrivateKey.from_private_bytes(key_bytes).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


class TC16NamingAndDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tc16_key = secrets.token_bytes(32)
        self.tc16_public = derive_public(self.tc16_key)
        self.child_key = secrets.token_bytes(32)
        self.child_public = derive_public(self.child_key)
        self.now = 2000
        self.expiry = 3600

        # Verified TC-16 service objects
        self.vm_service = {
            'kind': 'tc16.vm_instance',
            'program_hash': 'sha256:' + 'a' * 64,
            'memory_size': 65536,
            'capabilities': ['arithmetic', 'tcc', 'syscall'],
            'entrypoint': 0,
        }
        self.repo_service = {
            'kind': 'tc16.program_repository',
            'repository_hash': 'sha256:' + 'b' * 64,
            'programs': [
                {'name': 'kernel.bin', 'program_hash': 'sha256:' + 'c' * 64, 'syntax': 'assembly', 'size': 1024},
                {'name': 'math.tcc', 'program_hash': 'sha256:' + 'd' * 64, 'syntax': 'tcc', 'size': 512},
            ],
        }
        self.compute_service = {
            'kind': 'tc16.compute_service',
            'endpoint': 'tcc',
            'service_object': 'sha256:' + 'e' * 64,
            'max_cycles': 50000,
            'accepted_syntaxes': ['assembly', 'tcc'],
        }

        # Descriptors
        self.tc16_descriptor = {
            'public_dns': [
                {'type': 'A', 'value': '93.184.216.34', 'ttl': 120},
                {'type': 'AAAA', 'value': '2606:2800:220:1:248:1893:25c8:1946', 'ttl': 120},
                {'type': 'TXT', 'value': 'ziokt-descriptor=sha256:' + 'f' * 64, 'ttl': 120},
                {'type': 'HTTPS', 'value': {'priority': 1, 'target': '.', 'alpn': ['h2', 'http/1.1'], 'port': 443, 'ech': ''}, 'ttl': 120},
            ],
            'services': {
                'tc16': {'object': 'sha256:' + '1' * 64, 'access': 'public'},
            },
            'private': None,
        }

        self.root_delegation = {
            'network_id': 'ziokt-main',
            'component': 'tc16',
            'path': 'compute',
            'parent_revision': 1,
            'revision': 1,
            'expires_at': self.expiry,
            'delegate': self.child_public,
            'descriptor': self.tc16_descriptor,
        }

        self.root_registration = {
            'network_id': 'ziokt-main',
            'component': 'tc16',
            'root': 'compute',
            'owner': self.tc16_public,
            'revision': 1,
            'expires_at': self.expiry,
            'published_suffixes': ['tc16', 'tcc', 'ttc'],
            'delegations': {
                'compute': sign(self.root_delegation, self.tc16_key, DELEGATION_DOMAIN),
            },
        }

        self.adapter = TC16Names(signing_key=self.tc16_key, network_id='ziokt-main', clock=lambda: self.now)
        self.adapter.register(sign(self.root_registration, self.tc16_key, TC16_DOMAIN))
        self.resolver = Names({'tc16': self.adapter}, network_id='ziokt-main', clock=lambda: self.now)

    def test_tc16_and_tcc_suffix_resolution(self):
        """TC-16 standard (.tc16), compute (.tcc), and (.ttc) namespaces resolve with authentic records."""
        for suffix in ('tc16', 'tcc', 'ttc'):
            answer = self.resolver.resolve(f'compute.{suffix}')
            self.assertEqual(answer['name'], f'compute.{suffix}')
            self.assertEqual(len(answer['records']), 4)
            record_types = {r['type']: r['value'] for r in answer['records']}
            self.assertEqual(record_types['A'], '93.184.216.34')
            self.assertEqual(record_types['AAAA'], '2606:2800:220:1:248:1893:25c8:1946')
            self.assertIn('ziokt-descriptor=sha256:', record_types['TXT'])
            self.assertEqual(record_types['HTTPS']['port'], 443)

    def test_arbitrary_self_signed_registration_rejected(self):
        """Rejects any unverified self-signed registration not authorized by native TC-16 authority."""
        attacker_key = secrets.token_bytes(32)
        attacker_pub = derive_public(attacker_key)
        bogus_reg = copy.deepcopy(self.root_registration)
        bogus_reg['root'] = 'imposter'
        bogus_reg['owner'] = attacker_pub
        bogus_reg['delegations'] = {
            'imposter': sign({**self.root_delegation, 'path': 'imposter'}, attacker_key, DELEGATION_DOMAIN),
        }
        # Signing with attacker's key must fail registration against TC-16 adapter
        bogus_envelope = sign(bogus_reg, attacker_key, TC16_DOMAIN)
        with self.assertRaises(ProtocolError):
            self.adapter.register(bogus_envelope)

    def test_tc16_service_discovery_and_strict_privacy(self):
        """TC-16 service discovery publishes VM, repository, and compute descriptors,
        strictly forbidding any private runtime state leakage.
        """
        # Verified services pass
        self.assertEqual(verify_tc16_service(self.vm_service)['kind'], 'tc16.vm_instance')
        self.assertEqual(verify_tc16_service(self.repo_service)['kind'], 'tc16.program_repository')
        self.assertEqual(verify_tc16_service(self.compute_service)['kind'], 'tc16.compute_service')

        # Any exposure of private execution state (registers, pc, sp, flags, trace, memory) MUST fail
        for forbidden in ('registers', 'pc', 'sp', 'flags', 'mode', 'cycles', 'trace', 'memory'):
            leaky_service = {**self.vm_service, forbidden: [0] * 16 if forbidden == 'registers' else 123}
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(ProtocolError) as ctx:
                    verify_tc16_service(leaky_service)
                self.assertEqual(ctx.exception.code, 'PRIVATE_STATE_EXPOSED')

    def test_ed25519_subdomain_delegation_and_parent_revision(self):
        """Subdomain delegation requires valid parent delegation key and matching parent revision."""
        # Delegate child: node.compute.tc16
        child_descriptor = {
            'public_dns': [{'type': 'A', 'value': '93.184.216.35', 'ttl': 60}],
            'services': {},
            'private': None,
        }
        child_delegation = {
            'network_id': 'ziokt-main',
            'component': 'tc16',
            'path': 'node.compute',
            'parent_revision': 5,
            'revision': 1,
            'expires_at': 3000,
            'delegate': None,
            'descriptor': child_descriptor,
        }
        updated_root = copy.deepcopy(self.root_registration)
        updated_root['revision'] = 2
        updated_root['delegations']['compute'] = sign({**self.root_delegation, 'parent_revision': 2, 'revision': 5}, self.tc16_key, DELEGATION_DOMAIN)
        # Child signed by child_key (authorized as delegate by root)
        updated_root['delegations']['node.compute'] = sign(child_delegation, self.child_key, DELEGATION_DOMAIN)
        
        self.adapter.register(sign(updated_root, self.tc16_key, TC16_DOMAIN))
        answer = self.resolver.resolve('node.compute.tc16')
        self.assertEqual(answer['records'][0]['value'], '93.184.216.35')

        # Child signed by wrong key rejected
        wrong_key = secrets.token_bytes(32)
        updated_root['revision'] = 3
        updated_root['delegations']['compute'] = sign({**self.root_delegation, 'parent_revision': 3, 'revision': 6}, self.tc16_key, DELEGATION_DOMAIN)
        updated_root['delegations']['node.compute'] = sign({**child_delegation, 'parent_revision': 6}, wrong_key, DELEGATION_DOMAIN)
        self.adapter.register(sign(updated_root, self.tc16_key, TC16_DOMAIN))
        with self.assertRaises(ProtocolError):
            self.resolver.resolve('node.compute.tc16')

    def test_revocation_and_expiration(self):
        """Revocation via suffix unpublication and expiration past bounds are enforced."""
        # Revoke by unpublishing suffixes
        revoked = copy.deepcopy(self.root_registration)
        revoked['revision'] = 10
        revoked['published_suffixes'] = []
        self.adapter.register(sign(revoked, self.tc16_key, TC16_DOMAIN))
        with self.assertRaises(ProtocolError):
            self.resolver.resolve('compute.tc16')

        # Expired registration rejected
        expired_adapter = TC16Names(signing_key=self.tc16_key, network_id='ziokt-main', clock=lambda: 5000)
        expired_reg = {**self.root_registration, 'expires_at': 4000}
        with self.assertRaises(ProtocolError):
            expired_adapter.register(sign(expired_reg, self.tc16_key, TC16_DOMAIN))

    def test_multi_realm_isolation_and_foreign_tld_refusal(self):
        """Cross-network fallback is strictly forbidden; foreign TLDs are rejected with REFUSED."""
        isolated_adapter = TC16Names(signing_key=self.tc16_key, network_id='ziokt-test', clock=lambda: self.now)
        test_reg = copy.deepcopy(self.root_registration)
        test_reg['network_id'] = 'ziokt-test'
        test_reg['delegations']['compute'] = sign({**self.root_delegation, 'network_id': 'ziokt-test'}, self.tc16_key, DELEGATION_DOMAIN)
        isolated_adapter.register(sign(test_reg, self.tc16_key, TC16_DOMAIN))

        networks = NameNetworks({
            'main': self.resolver,
            'test': Names({'tc16': isolated_adapter}, network_id='ziokt-test', clock=lambda: self.now),
        }, default='main')

        self.assertTrue(networks.resolve('compute.tc16', realm='main')['records'])
        self.assertTrue(networks.resolve('compute.tc16', realm='test')['records'])
        with self.assertRaises(ProtocolError) as ctx:
            networks.resolve('compute.tc16', realm='unknown-realm')
        self.assertEqual(ctx.exception.code, 'REFUSED')

        # Non-Ziokt TLD refusal
        for foreign in ('compute.com', 'google.org', 'test.net', 'invalid.xyz'):
            with self.assertRaises(ProtocolError) as ctx:
                networks.resolve(foreign)
            self.assertEqual(ctx.exception.code, 'REFUSED')

    def test_companion_service_discovery_tri_zda_ufs_dcpm_shadow6(self):
        """All companions (Tri, ZDA, UFS, dCPM, Shadow6+Extensions) successfully
        publish and verify their native service objects.
        """
        # Tri simulator project service
        tri_service = {
            'schema': 'ziokt.tri-project.v1',
            'engine': 'ternary-computer-simulator',
            'program': 'PUSH 1\nHALT',
            'state': {'registers': {'pc': 0}},
        }
        self.assertEqual(verify_companion_service('tri', tri_service)['schema'], 'ziokt.tri-project.v1')

        # ZDA laws and calculate services
        zda_laws = {'schema': 'ziokt.ano-laws.v1', 'laws': {'merge_associative': {'holds': True}}}
        zda_calc = {'schema': 'ziokt.ano-calculate.v1', 'kind': 'numeric', 'operation': 'add', 'commitment': 'sha256:' + '9' * 64}
        self.assertEqual(verify_companion_service('zda', zda_laws)['schema'], 'ziokt.ano-laws.v1')
        self.assertEqual(verify_companion_service('zda', zda_calc)['kind'], 'numeric')

        # UFS content-addressed object reference service
        ufs_service = {
            'schema': 'ziokt.object-reference.v1',
            'object': 'sha256:' + '8' * 64,
            'size': 4096,
            'ttl': 86400,
        }
        self.assertEqual(verify_companion_service('ufs', ufs_service)['size'], 4096)

        # dCPM package manifest service
        dcpm_service = {
            'package_schema': 'ziokt.dcpm-package.v2',
            'name': 'tc16-standard-library',
            'version': '1.2.0',
            'manifest_digest': 'sha256:' + '7' * 64,
            'publisher': self.tc16_public,
        }
        self.assertEqual(verify_companion_service('dcpm', dcpm_service)['name'], 'tc16-standard-library')

        # Shadow6 node profile & Extensions linkage service
        s6_profile = {'schema': 'ziokt.node-profile.v1', 'profile': 'core-6-isolated'}
        s6_extension = {
            'schema': 'ziokt.extension-event.v1',
            'kind': 'zkn-gift',
            'content_digest': 'sha256:' + '6' * 64,
            'private': True,
        }
        self.assertEqual(verify_companion_service('shadow6', s6_profile)['profile'], 'core-6-isolated')
        self.assertEqual(verify_companion_service('shadow6', s6_extension)['kind'], 'zkn-gift')

    def test_wire_level_dns_udp_tcp_doh(self):
        """End-to-end DNS protocol testing: UDP, TCP, and loopback DoH resolve
        A, AAAA, TXT, and HTTPS records for .tc16 and .tcc names.
        """
        opened = servers(self.resolver, port=0, doh_port=0)
        for s in opened:
            self.addCleanup(s.server_close)
            self.addCleanup(s.shutdown)
            threading.Thread(target=s.serve_forever, daemon=True).start()
        udp, tcp, doh = opened

        # 1. UDP query for A record
        query_a = struct.pack('!6H', 42, 0x0100, 1, 0, 0, 0) + wire_name('compute.tc16') + struct.pack('!HH', 1, 1)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(2)
            sock.sendto(query_a, udp.server_address)
            reply = sock.recv(4096)
            ident, flags, qd, an, ns, ar = struct.unpack('!6H', reply[:12])
            self.assertEqual(ident, 42)
            self.assertEqual(flags & 15, 0)  # NOERROR
            self.assertEqual(an, 1)

        # 2. TCP query for AAAA record
        query_aaaa = struct.pack('!6H', 43, 0x0100, 1, 0, 0, 0) + wire_name('compute.tcc') + struct.pack('!HH', 28, 1)
        with socket.create_connection(tcp.server_address, timeout=2) as sock:
            sock.sendall(struct.pack('!H', len(query_aaaa)) + query_aaaa)
            size = int.from_bytes(sock.recv(2), 'big')
            reply = sock.recv(size)
            ident, flags, qd, an, ns, ar = struct.unpack('!6H', reply[:12])
            self.assertEqual(ident, 43)
            self.assertEqual(flags & 15, 0)  # NOERROR
            self.assertEqual(an, 1)

        # 3. DoH query for TXT record
        query_txt = struct.pack('!6H', 44, 0x0100, 1, 0, 0, 0) + wire_name('compute.tc16') + struct.pack('!HH', 16, 1)
        conn = http.client.HTTPConnection(*doh.server_address, timeout=2)
        conn.request('POST', '/dns-query', query_txt, {'Content-Type': 'application/dns-message'})
        res = conn.getresponse()
        self.assertEqual(res.status, 200)
        body = res.read()
        ident, flags, qd, an, ns, ar = struct.unpack('!6H', body[:12])
        self.assertEqual(ident, 44)
        self.assertEqual(flags & 15, 0)  # NOERROR
        self.assertEqual(an, 1)
        conn.close()

        # 4. Refused foreign query
        query_refused = struct.pack('!6H', 45, 0x0100, 1, 0, 0, 0) + wire_name('external.com') + struct.pack('!HH', 1, 1)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(2)
            sock.sendto(query_refused, udp.server_address)
            reply = sock.recv(4096)
            flags = int.from_bytes(reply[2:4], 'big')
            self.assertEqual(flags & 15, 5)  # REFUSED


if __name__ == '__main__':
    unittest.main()

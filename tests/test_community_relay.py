"""Actual opaque mTLS jump rendezvous: neither client needs inbound reachability."""
import hashlib
from pathlib import Path
import secrets
import tempfile
import threading
import unittest

from test_community_network import certificates
from cryptography.hazmat.primitives import serialization
from ziokt.community import Community, RIGHTS, create_policy
from ziokt.protocol import ProtocolError
from ziokt.rendezvous import OpaqueRendezvous, RendezvousClient, RELAY_METHODS
from ziokt.remote import remote_server, tls_context
from ziokt.security import sign


class RelayTests(unittest.TestCase):
    def test_two_outbound_clients_exchange_without_relay_decryption_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); first, second, key = secrets.token_bytes(32), secrets.token_bytes(32), secrets.token_bytes(32)
            p1, p2 = sign({}, first, 'test')['public_key'], sign({}, second, 'test')['public_key']
            policy = create_policy(first, 'village', {p1: sorted(RIGHTS), p2: sorted(RIGHTS)}, privacy='private')
            d1, d2 = root/'tls1', root/'tls2'; d1.mkdir(); d2.mkdir()
            ca1, pairs1 = certificates(d1); ca2, pairs2 = certificates(d2)
            ca = root/'server-cas.pem'; ca.write_bytes(ca1.read_bytes()+ca2.read_bytes())
            trusted = {}
            for pairs, public in [(pairs1,p1),(pairs2,p2)]:
                fingerprint = hashlib.sha256(pairs['client'][2].public_bytes(serialization.Encoding.DER)).hexdigest()
                trusted[fingerprint] = {'public_key': public, 'methods': sorted(RELAY_METHODS), 'providers': ['village']}
            backend = OpaqueRendezvous(root/'relay', policy, p1)
            server = remote_server({'enabled': True, 'federation_id': 'village', 'providers': []},
                tls_context(*pairs1['server'][:2], ca, server=True), root/'replay.sqlite', trusted,
                allow_mutations=True, community=backend)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                endpoint = {'host':'127.0.0.1','port':server.server_port,'connection_policy':{'mode':'relay','allow_direct_fallback':False},'rendezvous':{'recipient':p2}}
                with Community(root/'first', policy, p1, key) as source, Community(root/'second', policy, p1, key) as receiver:
                    source.publish(first, 'wiki', 'home', {'title':'Private knowledge','text':'end-to-end content hidden from relay'})
                    manifest = source.put_file(b'opaque binary data')
                    source.publish(first, 'files', 'archive', {'name':'archive',**manifest})
                    a = RendezvousClient(source, endpoint, tls_context(*pairs1['client'][:2], ca1), first)
                    b = RendezvousClient(receiver, endpoint, tls_context(*pairs2['client'][:2], ca1), second)
                    result = a.send(p2); self.assertFalse(result['delivered'])
                    queued = backend.db.execute('SELECT size,document FROM envelopes').fetchone()
                    self.assertGreaterEqual(queued[0], 16384)
                    self.assertEqual(queued[0] & (queued[0]-1), 0)
                    self.assertIn(b'ziokt.rendezvous.v2', queued[1])
                    self.assertFalse(hasattr(backend, 'cipher'))
                    self.assertNotIn(b'end-to-end content hidden from relay', (root/'relay/relay.sqlite').read_bytes())
                    with self.assertRaises(ProtocolError):
                        backend.call('relay.part.get', {'packet_id':result['packet_id'],'part':0}, p1)
                    self.assertEqual(b.receive()['received'],1)
                    self.assertEqual(receiver.get_file(manifest), b'opaque binary data')
                    self.assertEqual(receiver.view('wiki'),source.view('wiki'))
                    self.assertEqual(b.receive()['received'],0)
                    self.assertEqual(backend.db.execute('SELECT COUNT(*) FROM envelopes').fetchone()[0],0)
            finally:
                server.shutdown(); server.server_close(); thread.join(5); backend.close()

    def test_direct_and_anonymous_choices_are_explicit(self):
        from ziokt.routes import admit_endpoint
        direct = {'host':'127.0.0.1','port':443,'connection_policy':{'mode':'direct','allow_direct_fallback':False}}
        self.assertEqual(admit_endpoint('private',direct)['mode'],'direct')
        with self.assertRaises(ProtocolError): admit_endpoint('restricted',direct)
        with self.assertRaises(ProtocolError): admit_endpoint('private',{'connection_policy':{'mode':'anonymous','allow_direct_fallback':False}})


if __name__ == '__main__': unittest.main()

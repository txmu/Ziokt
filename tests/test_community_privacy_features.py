"""Privacy and anonymity extensions: secret ballots, pseudonyms, route selection, and data erasure."""
import io
import json
import secrets
import tempfile
import unittest
import zipfile
from pathlib import Path

from ziokt.community import Community, RIGHTS, create_policy
from ziokt.community_privacy import (
    ballot_commitment, verify_ballot, seal_ballot, open_ballot,
    pseudonym_token, mailbox_public
)
from ziokt.community_site import build_site, publish_site
from ziokt.community_ui import portal_server
from ziokt.protocol import ProtocolError
from ziokt.registration import RegistrationGate
from ziokt.routes import validate_route, admit_endpoint
from ziokt.security import sign


class PrivacyAndAnonymityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private, self.key = secrets.token_bytes(32), secrets.token_bytes(32)
        self.public = sign({}, self.private, 'test')['public_key']
        self.policy = create_policy(self.private, 'village', {self.public: sorted(RIGHTS)}, privacy='restricted')
        self.community = Community(self.root / 'community', self.policy, self.public, self.key)
        self.addCleanup(self.community.close)

    def test_secret_ballot_commitment_and_sealing(self):
        tally_private = secrets.token_bytes(32)
        tally_mailbox = mailbox_public(tally_private)
        salt = secrets.token_hex(16)
        proposal = 'keep-offline-archives'

        commitment = ballot_commitment('yes', salt, proposal, self.public)
        self.assertIsInstance(commitment, str)
        self.assertEqual(len(commitment), 64)
        self.assertTrue(verify_ballot(commitment, 'yes', salt, proposal, self.public))
        self.assertFalse(verify_ballot(commitment, 'no', salt, proposal, self.public))
        self.assertFalse(verify_ballot(commitment, 'yes', salt, 'other-proposal', self.public))

        sealed = seal_ballot(tally_mailbox, 'yes', salt, proposal, self.public)
        self.assertEqual(sealed['commitment'], commitment)
        self.assertEqual(sealed['proposal'], proposal)

        opened = open_ballot(tally_private, proposal, sealed)
        self.assertEqual(opened['choice'], 'yes')
        self.assertEqual(opened['voter'], self.public)
        self.assertEqual(opened['salt'], salt)
        self.assertEqual(opened['commitment'], commitment)

        wrong_tally = secrets.token_bytes(32)
        with self.assertRaises(ProtocolError):
            open_ballot(wrong_tally, proposal, sealed)

        tampered = {**sealed, 'commitment': '0' * 64}
        with self.assertRaises(ProtocolError):
            open_ballot(tally_private, proposal, tampered)

        with self.assertRaises(ProtocolError):
            open_ballot(tally_private, 'different-proposal', sealed)

    def test_pseudonym_token_derivation_and_unlinkability(self):
        ctx1 = 'feedback-topic-alpha'
        ctx2 = 'feedback-topic-beta'
        token1a = pseudonym_token(self.private, ctx1)
        token1b = pseudonym_token(self.private, ctx1)
        token2 = pseudonym_token(self.private, ctx2)

        self.assertEqual(token1a, token1b)
        self.assertNotEqual(token1a, token2)
        self.assertEqual(len(token1a), 64)

        other_private = secrets.token_bytes(32)
        self.assertNotEqual(pseudonym_token(other_private, ctx1), token1a)

        with self.assertRaises(ProtocolError):
            pseudonym_token(b'short', ctx1)
        with self.assertRaises(ProtocolError):
            pseudonym_token(self.private, '')

    def test_approved_paths_route_validation_and_enforcement(self):
        direct_path = {'approved': True, 'observed': {
            'end_to_end_authentication': True, 'encrypted_content': True,
            'private_discovery': True, 'direct_fallback': True
        }}
        onion_path = {'approved': True, 'observed': {
            'end_to_end_authentication': True, 'encrypted_content': True,
            'private_discovery': True, 'anonymous_carrier': True, 'direct_fallback': False
        }}
        from test_community_network import ONION
        direct_path.update({'host': '127.0.0.1', 'port': 443})
        onion_path.update({'host': ONION, 'port': 443,
                           'carrier': {'kind': 'tor-socks5', 'proxy_host': '127.0.0.1', 'proxy_port': 9050}})

        endpoint_missing = {
            'connection_policy': {'mode': 'approved-paths', 'allow_direct_fallback': False}
        }
        with self.assertRaises(ProtocolError):
            validate_route(endpoint_missing['connection_policy'], endpoint_missing)

        endpoint_empty = {
            'connection_policy': {'mode': 'approved-paths', 'allow_direct_fallback': False},
            'candidates': []
        }
        with self.assertRaises(ProtocolError):
            validate_route(endpoint_empty['connection_policy'], endpoint_empty)

        endpoint_valid = {
            'connection_policy': {'mode': 'approved-paths', 'allow_direct_fallback': False},
            'candidates': [direct_path, onion_path]
        }
        validated = validate_route(endpoint_valid['connection_policy'], endpoint_valid)
        self.assertEqual(validated['mode'], 'approved-paths')

        admitted_restricted = admit_endpoint('restricted', endpoint_valid)
        self.assertEqual(admitted_restricted['mode'], 'approved-paths')
        self.assertEqual(admitted_restricted['selected'], onion_path)

        endpoint_no_anon = {
            'connection_policy': {'mode': 'approved-paths', 'allow_direct_fallback': False},
            'candidates': [direct_path]
        }
        with self.assertRaises(ProtocolError):
            admit_endpoint('restricted', endpoint_no_anon)

        admitted_private = admit_endpoint('private', endpoint_valid)
        self.assertEqual(admitted_private['mode'], 'approved-paths')
        self.assertIn('selected', admitted_private)

    def test_anonymous_site_generation_redacts_author_identity(self):
        self.community.publish(self.private, 'wiki', 'doc', {'title': 'Guide', 'text': 'Content'})
        self.community.publish(self.private, 'forum', 'topic', {'title': 'Hello', 'text': 'Discussion', 'reply_to': ''})

        zip_bytes, manifest = build_site(self.community, 'Village Site', anonymous=True)
        self.assertTrue(manifest['anonymous'])

        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
        event = self.community.view('wiki')['events'][0]
        all_bytes = b''.join(archive.read(name) for name in archive.namelist())
        self.assertNotIn(self.community.policy_id.encode(), all_bytes)
        self.assertNotIn(event['id'][7:19].encode(), all_bytes)
        self.assertNotIn(self.public.encode(), all_bytes)
        self.assertIsNone(manifest['community_id'])
        self.assertIsNone(manifest['policy'])
        self.assertIn('wiki-document-1.html', archive.namelist())
        for filename in archive.namelist():
            if filename.endswith('.html') and filename != 'index.html':
                content = archive.read(filename).decode('utf-8')
                self.assertIn('作者 匿名成员', content)
                self.assertNotIn(self.public, content)

        published = publish_site(self.community, self.private, 'anon-site', 'Village Site', anonymous=True)
        self.assertTrue(published['manifest']['anonymous'])

    def test_registration_purge_safely_removes_stored_materials(self):
        class DummyProviderClient:
            def call(self, method, params):
                if method == 'operation.prepare':
                    return {'plan_digest': 'sha256:' + 'a' * 64}
                if method == 'operation.commit':
                    return {'result': {'transaction_hash': 'tx123'}}
                if method == 'identity.fact':
                    return {
                        'registered': True, 'member_public': params['member_public'],
                        'policy_digest': params['policy_digest'], 'issuer': params['issuer'],
                        'document_commitment': 'commitment', 'transaction_hash': 'tx123',
                        'height': 100
                    }
                raise RuntimeError(method)

        config_file = self.root / 'fed.json'
        config_file.write_text(json.dumps({
            'schema': 'ziokt.federation.v1', 'enabled': True, 'federation_id': 'village',
            'providers': [{
                'native_project': 'corium', 'provider_id': 'reg-auth',
                'root': str(self.root / 'corium'), 'native_config': str(self.root / 'corium/etc/corix/networks/net1/corix.conf'),
                'entrypoint_digest': 'sha256:' + '0' * 64, 'network_id': 'net1', 'state_root': str(self.root / 'corium')
            }]
        }))
        from ziokt.protocol import make_private
        make_private(config_file)

        mailbox_priv = secrets.token_bytes(32)
        admin_mailbox = mailbox_public(mailbox_priv)
        reg_policy = {
            'required': True, 'provider_id': 'reg-auth', 'issuer': self.public,
            'admin_public': self.public, 'admin_mailbox': admin_mailbox
        }
        pol = create_policy(self.private, 'village', {self.public: sorted(RIGHTS)}, epoch=1, registration=reg_policy)
        with Community(self.root / 'reg_comm', pol, self.public, self.key) as comm:
            gate = RegistrationGate(comm, config_file)
            gate.client = DummyProviderClient()

            submit_res = gate.submit(self.public, b'My confidential identity text')
            self.assertTrue(submit_res['submitted'])

            uploads = comm.db.execute('SELECT cipher_digest FROM registration_uploads WHERE member=?', (self.public,)).fetchall()
            self.assertEqual(len(uploads), 1)
            cipher_file = gate.directory / uploads[0][0][7:]
            self.assertTrue(cipher_file.exists())

            purge_res = gate.purge(self.public)
            self.assertTrue(purge_res['purged'])
            self.assertFalse(cipher_file.exists())

            remaining = comm.db.execute('SELECT COUNT(*) FROM registration_uploads WHERE member=?', (self.public,)).fetchone()[0]
            self.assertEqual(remaining, 0)

            repeat_purge = gate.purge(self.public)
            self.assertFalse(repeat_purge['purged'])

    def test_portal_privacy_endpoints(self):
        import http.client
        import threading
        server, token = portal_server(self.community, self.private)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

            # 1. Check carrier_required in /api/status
            conn.request('GET', '/api/status', None, headers)
            res = conn.getresponse()
            self.assertEqual(res.status, 200)
            status_data = json.loads(res.read())
            self.assertTrue(status_data['carrier_required'])

            # 2. Mail send with auto-generated key
            mailbox_priv = secrets.token_bytes(32)
            m_pub = mailbox_public(mailbox_priv)
            mail_payload = json.dumps({
                'recipient': self.public,
                'mailbox': m_pub,
                'subject': 'Private ping',
                'text': 'Secret hello',
                'key': ''
            })
            conn.request('POST', '/api/mail-send', mail_payload, headers)
            mail_res = conn.getresponse()
            self.assertEqual(mail_res.status, 200)
            mail_out = json.loads(mail_res.read())
            self.assertIn('event', mail_out)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)


if __name__ == '__main__':
    unittest.main()


"""Application semantics, fork convergence, encrypted replicas and cold recovery."""
import copy
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest

from ziokt.community import Community, DOMAINS, RIGHTS, create_policy, content_id, CHUNK_FRAME
from ziokt.protocol import ProtocolError, encoded
from ziokt.security import sign


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private, self.key = secrets.token_bytes(32), secrets.token_bytes(32)
        self.public = sign({}, self.private, 'test')['public_key']
        self.policy = create_policy(self.private, 'village', {self.public: sorted(RIGHTS)}, privacy='private')
        self.a = self.node('a')

    def node(self, name, policy=None):
        node = Community(self.root/name, policy or self.policy, self.public, self.key)
        self.addCleanup(node.close)
        return node

    def test_every_application_signed_roundtrip_and_native_authority_boundary(self):
        manifest = self.a.put_file(b'community file')
        d = 'sha256:'+'a'*64
        bodies = {
            'forum': {'title': 'Discussion', 'text': 'hello', 'reply_to': ''},
            'chat': {'text': 'hello', 'channel': 'general'},
            'wiki': {'title': 'Knowledge', 'text': '# hello'},
            'files': {'name': 'document', **manifest},
            'packages': {'name': 'docs', 'version': '1', **manifest, 'native_kind': 'corium-package', 'native_signature': 'original signature required at activation'},
            'mail': __import__('ziokt.community_privacy', fromlist=['seal_mail']).seal_mail(self.public,
                __import__('ziokt.community_privacy', fromlist=['mailbox_public']).mailbox_public(self.key), 'hello', 'community mailbox'),
            'names': {'target': 'ziokt://village/wiki/home'},
            'governance': {'proposal': 'keep archives', 'choice': 'yes'},
            'hosting': {'service': 'wiki', 'workflow_digest': d, 'content': d},
            'compute': {'job': 'index', 'workflow_digest': d, 'result': d},
            'identity': {'name': 'alice', 'public_key': self.public,
                'mailbox_public': __import__('ziokt.community_privacy', fromlist=['mailbox_public']).mailbox_public(self.key)}}
        self.assertEqual(set(bodies), DOMAINS)
        for domain, body in bodies.items():
            object_key = self.public if domain == 'identity' else 'main'
            event = self.a.publish(self.private, domain, object_key, body)
            result = self.a.view(domain, object_key)
            self.assertEqual(result['heads'], [event]); self.assertFalse(result['runtime_ready'])
            self.assertEqual(result['events'][0]['body'], body)
        self.assertEqual(self.a.get_file(manifest), b'community file')
        b = self.node('b'); checkpoint = self.a.checkpoint(self.private)
        self.assertNotIn(b'Knowledge', checkpoint)
        b.restore(checkpoint, self.public)
        for domain in DOMAINS: self.assertEqual(self.a.view(domain), b.view(domain))
        self.assertEqual(b.get_file(manifest), b'community file')

    def test_concurrent_wiki_edits_preserve_both_then_explicit_merge(self):
        first = self.a.publish(self.private, 'wiki', 'page', {'title': 'Page', 'text': 'base'})
        b = self.node('b'); b.restore(self.a.checkpoint(self.private), self.public)
        left = self.a.publish(self.private, 'wiki', 'page', {'title': 'Page', 'text': 'left'})
        right = b.publish(self.private, 'wiki', 'page', {'title': 'Page', 'text': 'right'})
        self.a.restore(b.checkpoint(self.private), self.public)
        self.assertEqual(set(self.a.view('wiki', 'page')['conflicts']['page']), {left, right})
        merged = self.a.publish(self.private, 'wiki', 'page', {'title': 'Page', 'text': 'left + right'})
        b.restore(self.a.checkpoint(self.private), self.public)
        self.assertEqual(b.view('wiki', 'page')['heads'], [merged])
        self.assertEqual(len(b.view('wiki', 'page')['events']), 4)
        self.assertIn(first, {e['id'] for e in b.view('wiki', 'page')['events']})

    def test_node_loss_and_coordinator_absence_do_not_destroy_community(self):
        manifest = self.a.put_file(b'archive'*1000)
        self.a.publish(self.private, 'files', 'archive', {'name': 'archive', **manifest})
        self.a.publish(self.private, 'forum', 'general', {'title': 'Welcome', 'text': 'community history', 'reply_to': ''})
        b, c = self.node('b'), self.node('c')
        replicas = self.a.replicate([b, c], self.private)
        self.assertTrue(replicas['satisfied']); self.assertFalse(replicas['failure_domain_independence_verified'])
        # Delete the original on-disk node; no coordinator or native checkouts.
        self.a.close(); self.a.close = lambda: None; shutil.rmtree(self.root/'a')
        self.assertEqual(b.get_file(manifest), b'archive'*1000)
        b.publish(self.private, 'wiki', 'reorganized', {'title': 'Recovery', 'text': 'services can be rebuilt'})
        fresh = self.node('fresh'); fresh.restore(b.checkpoint(self.private), self.public)
        self.assertEqual(fresh.get_file(manifest), b'archive'*1000)
        self.assertEqual(fresh.view('wiki')['events'][0]['body']['title'], 'Recovery')

    def test_tampering_wrong_key_wrong_community_and_rollback(self):
        self.a.publish(self.private, 'wiki', 'home', {'title': 'T', 'text': 'private'})
        blob = self.a.checkpoint(self.private); b = self.node('b')
        for bad in [blob[:-1], blob[:-1]+bytes([blob[-1]^1])]:
            with self.assertRaises(ProtocolError): b.restore(bad, self.public)
        self.assertEqual(b.view('wiki')['events'], [])
        wrong = Community(self.root/'wrong', self.policy, self.public, secrets.token_bytes(32)); self.addCleanup(wrong.close)
        with self.assertRaises(ProtocolError): wrong.restore(blob, self.public)
        new_policy = create_policy(self.private, 'village', {self.public: sorted(RIGHTS)}, epoch=1, privacy='private')
        newer = self.node('b', new_policy)
        with self.assertRaises(ProtocolError): newer.restore(blob, self.public)
        with self.assertRaises(ProtocolError): Community(self.root/'b', self.policy, self.public, self.key)
        with self.assertRaises(ProtocolError): b.publish(self.private, 'wiki', 'home', {'title': 'T', 'text': 'stale'})

    def test_member_scopes_revoked_writers_and_historical_recovery(self):
        member = secrets.token_bytes(32); pub = sign({}, member, 'test')['public_key']
        policy = create_policy(self.private, 'village', {self.public: sorted(RIGHTS), pub: ['forum']}, privacy='private')
        c = self.node('scoped', policy)
        with self.assertRaises(ProtocolError): c.publish(member, 'wiki', 'page', {'title': 'T', 'text': 'forbidden'})
        c.publish(member, 'forum', 'post', {'title': 'Allowed', 'text': 'historic contribution', 'reply_to': ''})
        sealed = c.db.execute('SELECT sealed FROM records').fetchone()[0]
        updated = create_policy(self.private, 'village', {self.public: sorted(RIGHTS)}, epoch=1, privacy='private')
        current = self.node('scoped', updated)
        with self.assertRaises(ProtocolError): current.admit([sealed])
        with self.assertRaises(ProtocolError): current.publish(member, 'forum', 'new', {'title': 'T', 'text': 'revoked', 'reply_to': ''})
        fresh = self.node('fresh', updated)
        fresh.restore(current.checkpoint(self.private), self.public)
        self.assertEqual(fresh.view('forum')['events'][0]['body']['text'], 'historic contribution')

    def test_replay_idempotence_parent_scope_and_transaction_atomicity(self):
        self.a.publish(self.private, 'wiki', 'one', {'title': 'One', 'text': 'body'})
        sealed = self.a.db.execute('SELECT sealed FROM records').fetchone()[0]
        self.assertEqual(self.a.admit([sealed])['added'], 0)
        with self.assertRaises(ProtocolError): self.a.admit([sealed, b'wrong'])
        self.assertEqual(len(self.a.view('wiki')['events']), 1)
        first = self.a.view('wiki')['heads'][0]
        with self.assertRaises(ProtocolError): self.a.publish(self.private, 'wiki', 'two', {'title': 'Two', 'text': 'body'}, parents=[first])
        self.assertEqual(len(self.a.view('wiki')['events']), 1)

    def test_padded_ciphertext_and_corrupt_replica_content(self):
        short, long = self.a.put_file(b'a'), self.a.put_file(b'a'*2000)
        for d in short['chunks']+long['chunks']:
            self.assertEqual(len(self.a.store.get(d)), CHUNK_FRAME)
            self.assertNotIn(b'Ziokt', self.a.store.get(d))
        self.a.publish(self.private, 'files', 'short', {'name': 'secret', **short})
        d = short['chunks'][0]; (self.a.store.root/d[7:]).write_bytes(b'corruption')
        with self.assertRaises(ProtocolError): self.a.checkpoint(self.private)
        b = self.node('b')
        with self.assertRaises(ProtocolError): self.a.replicate([b, b], self.private)

    def test_deletion_is_signed_history_and_no_automatic_resurrection(self):
        self.a.publish(self.private, 'wiki', 'page', {'title': 'Page', 'text': 'old'})
        deleted = self.a.publish(self.private, 'wiki', 'page', {'reason': 'community moderation'}, deleted=True)
        b = self.node('b'); b.restore(self.a.checkpoint(self.private), self.public)
        self.assertEqual(b.view('wiki', 'page')['heads'], [deleted])
        self.assertTrue(next(e for e in b.view('wiki')['events'] if e['id'] == deleted)['deleted'])

    def test_cli_initialization_and_no_listener(self):
        proc = subprocess.run([sys.executable, '-m', 'ziokt', 'community', 'init', '--root', str(self.root/'cli'), '--name', 'village'], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout+proc.stderr)
        self.assertIn('"network_enabled": false', proc.stdout)
        again = subprocess.run([sys.executable, '-m', 'ziokt', 'community', 'init', '--root', str(self.root/'cli'), '--name', 'village'], capture_output=True)
        self.assertEqual(again.returncode, 2)

    def test_secure_binary_read_preserves_crlf_and_dos_eof(self):
        from ziokt.protocol import secure_read, make_private
        path = self.root/'binary'
        data = bytes(range(256))*32+b'\r\n\x1aafter-dos-eof'
        path.write_bytes(data); make_private(path)
        self.assertEqual(secure_read(path, len(data)), data)

    def test_large_file_encrypted_index_and_complete_cold_restore(self):
        data = bytes(range(256))*700
        manifest = self.a.put_file(data)
        self.assertIsInstance(manifest['chunks'], dict)
        self.a.publish(self.private, 'files', 'large', {'name': 'large', **manifest})
        b = self.node('indexed-replica'); b.restore(self.a.checkpoint(self.private), self.public)
        self.assertEqual(b.get_file(manifest), data)
        root = manifest['chunks']['root']
        (b.store.root/root[7:]).write_bytes(b'corrupt index')
        with self.assertRaises(ProtocolError): b.get_file(manifest)

    def test_confidentiality_rotation_preserves_authorship_and_blocks_old_keys(self):
        original = self.a.publish(self.private, 'wiki', 'home', {'title': 'Historic', 'text': 'signed author preserved'})
        materials = self.a.put_file(b'old encrypted file')
        self.a.publish(self.private, 'files', 'old', {'name': 'old', **materials})
        new_policy = create_policy(self.private, 'village', {self.public: sorted(RIGHTS)}, epoch=1, privacy='private')
        new_key = secrets.token_bytes(32)
        with self.a.rotate(new_policy, new_key, self.private) as rotated:
            self.assertEqual(rotated.get_file(materials), b'old encrypted file')
            self.assertEqual(rotated.view('wiki')['heads'], [original])
            rotated.publish(self.private, 'wiki', 'new', {'title': 'New', 'text': 'fresh confidentiality epoch'})
            archive = rotated.checkpoint(self.private)
            with Community(self.root/'rotated-peer', new_policy, self.public, new_key) as peer:
                peer.restore(archive, self.public)
                self.assertEqual(peer.get_file(materials), b'old encrypted file')
                self.assertEqual(peer.view('wiki'), rotated.view('wiki'))
            with self.assertRaises(ProtocolError): Community(self.root/'a', new_policy, self.public, self.key)
        with Community(self.root/'rotated-peer', new_policy, self.public, new_key) as reopened:
            self.assertEqual(reopened.get_file(materials), b'old encrypted file')
            self.assertEqual(len(reopened.view('wiki')['events']), 2)


if __name__ == '__main__': unittest.main()

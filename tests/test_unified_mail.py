"""Unit and integration tests for Unified Mail, ZDNS routing, Content Fabric attachments,
and authenticated anti-flood / anti-spam public relay.
"""
import hashlib
from pathlib import Path
import secrets
import tempfile
import time
import unittest

from ziokt.mail import (
    parse_mail_address, resolve_mail_destination, validate_attachment, validate_attachments,
    AntiFloodGuard, AntiSpamGuard, CoriumMailChannel, ETPMailChannel, CommunityMailChannel,
    MailRelay, UnifiedMail, MAX_ATTACHMENT_SIZE, MAX_TOTAL_ATTACHMENT_SIZE, MAIL_DOMAIN
)
from ziokt.protocol import ProtocolError, encoded
from ziokt.security import sign


class UnifiedMailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.forum_db = self.root / 'forum.db'
        self.objects_dir = self.root / 'objects'
        self.etp_store = self.root / 'etp_mailboxes'

        # Generate ed25519 sender key
        self.sender_key = secrets.token_bytes(32)
        # Generate relay signing key
        self.relay_key = secrets.token_bytes(32)

    def test_zdns_address_parsing_and_resolution(self):
        # Corium domain
        loc, dom, auth, root, _ = parse_mail_address('alice@node.corium')
        self.assertEqual(loc, 'alice')
        self.assertEqual(dom, 'node.corium')
        self.assertEqual(auth, 'corium')

        dest_cor = resolve_mail_destination('alice@node.corium')
        self.assertEqual(dest_cor['channel'], 'corium')
        self.assertEqual(dest_cor['local_part'], 'alice')

        # Corix alias
        dest_corix = resolve_mail_destination('bob@service.corix')
        self.assertEqual(dest_corix['channel'], 'corium')

        # ETP domain
        dest_etp = resolve_mail_destination('node1@mesh.etp')
        self.assertEqual(dest_etp['channel'], 'etp')

        # Community / Ziokt domain
        dest_zio = resolve_mail_destination('moderator@governance.ziokt')
        self.assertEqual(dest_zio['channel'], 'community')

        # Hex 64-char local part binds recipient_key
        raw_hex = 'a' * 64
        dest_hex = resolve_mail_destination(f'{raw_hex}@gateway.corium')
        self.assertEqual(dest_hex['recipient_key'], raw_hex)

        # Invalid addresses
        for bad in ['invalid-address', 'bad@', '@nodomain', 'alice@bad..domain', 'spaces in@domain.corium']:
            with self.assertRaises(ProtocolError):
                parse_mail_address(bad)

    def test_content_fabric_attachments_validation(self):
        cf_id = 'cf1-' + 'b' * 64
        valid_att = {
            'id': cf_id,
            'name': 'document.pdf',
            'size': 1024 * 1024,
            'digest': 'sha256:' + 'c' * 64,
            'mime': 'application/pdf',
            'merkle_root': 'd' * 64,
            'v': 1
        }
        res = validate_attachment(valid_att)
        self.assertEqual(res['id'], cf_id)

        # Invalid CF ID (missing cf1- or wrong length)
        with self.assertRaises(ProtocolError):
            validate_attachment({**valid_att, 'id': 'cf2-' + 'b' * 64})
        with self.assertRaises(ProtocolError):
            validate_attachment({**valid_att, 'id': 'cf1-' + 'b' * 63})
        with self.assertRaises(ProtocolError):
            validate_attachment({**valid_att, 'id': 'https://attacker.invalid/evil.bin'})

        # Path traversal in name
        with self.assertRaises(ProtocolError):
            validate_attachment({**valid_att, 'name': '../etc/passwd'})
        with self.assertRaises(ProtocolError):
            validate_attachment({**valid_att, 'name': 'sub/file.pdf'})

        # Oversized attachment (> 16 MiB)
        with self.assertRaises(ProtocolError):
            validate_attachment({**valid_att, 'size': MAX_ATTACHMENT_SIZE + 1})

        # List validation: max 4 attachments
        atts = [{**valid_att, 'id': f'cf1-{"%064x" % i}', 'name': f'file{i}.pdf'} for i in range(4)]
        self.assertEqual(len(validate_attachments(atts)), 4)

        # Rejection of 5 attachments (> MAX_ATTACHMENTS)
        too_many = [{**valid_att, 'id': f'cf1-{"%064x" % i}', 'name': f'file{i}.pdf'} for i in range(5)]
        with self.assertRaises(ProtocolError):
            validate_attachments(too_many)

        # Duplicate attachment IDs in same mail
        dups = [valid_att, valid_att]
        with self.assertRaises(ProtocolError):
            validate_attachments(dups)

        # Total size budget exceeded (> 32 MiB)
        big_atts = [
            {**valid_att, 'id': f'cf1-{"%064x" % 1}', 'size': 15 * 1024 * 1024},
            {**valid_att, 'id': f'cf1-{"%064x" % 2}', 'size': 15 * 1024 * 1024},
            {**valid_att, 'id': f'cf1-{"%064x" % 3}', 'size': 10 * 1024 * 1024},
        ]
        with self.assertRaises(ProtocolError):
            validate_attachments(big_atts)

    def test_corium_channel_roundtrip(self):
        channel = CoriumMailChannel(forum_db=self.forum_db, objects_dir=self.objects_dir)
        att = {
            'id': 'cf1-' + 'e' * 64,
            'name': 'archive.tar.gz',
            'size': 2048,
            'digest': 'sha256:' + 'f' * 64,
            'mime': 'application/gzip',
            'merkle_root': '0' * 64,
            'v': 1
        }
        res = channel.send(
            sender_key='sender1',
            recipient_id='recipient1',
            subject='Native Corium Mail',
            body='Hello Corium postal network!',
            attachments=[att]
        )
        self.assertEqual(res['channel'], 'corium')
        self.assertTrue(res['tx_hash'])
        self.assertTrue(res['local_path'])

        # Query inbox
        inbox = channel.inbox('recipient1')
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]['tx_hash'], res['tx_hash'])
        self.assertEqual(inbox[0]['content']['subject'], 'Native Corium Mail')
        self.assertEqual(inbox[0]['content']['attachments'][0]['id'], att['id'])

        # Read specific mail
        read_item = channel.read(res['tx_hash'])
        self.assertEqual(read_item['tx_hash'], res['tx_hash'])
        self.assertEqual(read_item['content']['body'], 'Hello Corium postal network!')

    def test_etp_channel_roundtrip(self):
        channel = ETPMailChannel(mailbox_store_dir=self.etp_store)
        res = channel.send(
            sender_key='sender_etp',
            recipient_key='recipient_etp_1',
            subject='ETP Sealed Notice',
            body='Noise envelope payload',
            attachments=[]
        )
        self.assertEqual(res['channel'], 'etp')
        self.assertTrue(res['message_id'])

        # Inbox retrieval
        inbox = channel.inbox('recipient_etp_1')
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]['payload']['subject'], 'ETP Sealed Notice')
        self.assertEqual(inbox[0]['payload']['body'], 'Noise envelope payload')

    def test_community_channel_roundtrip(self):
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        from ziokt.community_privacy import mailbox_public

        recipient_priv = X25519PrivateKey.generate().private_bytes_raw()
        recipient_pub = mailbox_public(recipient_priv)
        recipient_id = 'e' * 64

        channel = CommunityMailChannel()
        sent = channel.send(
            sender_key='sender',
            recipient=recipient_id,
            recipient_mailbox_key=recipient_pub,
            subject='Community Notice',
            body='Privately sealed community mail'
        )
        self.assertEqual(sent['channel'], 'community')
        self.assertTrue(sent['sealed'])

        # Decrypt
        opened = channel.open(recipient_priv, recipient_id, sent['sealed'])
        self.assertEqual(opened['subject'], 'Community Notice')
        self.assertIn('Privately sealed community mail', opened['text'])

    def test_anti_flood_guard_rate_limits_and_burst(self):
        guard = AntiFloodGuard(sender_limit=5, global_limit=10, window_seconds=60, burst_threshold=3)
        sender = 'sender_flood_test'
        now = 1000.0

        # Sending within limits with simulated spacing
        for i in range(3):
            guard.check_rate_limit(sender, now=now + i * 5.0)

        # Rapid burst (> 3 in <= 2.0s)
        guard_burst = AntiFloodGuard(sender_limit=10, global_limit=20, burst_threshold=3)
        guard_burst.check_rate_limit(sender, now=1000.0)
        guard_burst.check_rate_limit(sender, now=1000.5)
        guard_burst.check_rate_limit(sender, now=1001.0)
        with self.assertRaises(ProtocolError) as ctx:
            guard_burst.check_rate_limit(sender, now=1001.2)
        self.assertEqual(ctx.exception.code, 'BURST_LIMIT_EXCEEDED')

        # Sender rate limit exceeded (> sender_limit in window)
        guard_sender = AntiFloodGuard(sender_limit=3, global_limit=20, burst_threshold=10)
        for i in range(3):
            guard_sender.check_rate_limit(sender, now=1000.0 + i * 10.0)
        with self.assertRaises(ProtocolError) as ctx:
            guard_sender.check_rate_limit(sender, now=1040.0)
        self.assertEqual(ctx.exception.code, 'RATE_LIMITED')

        # After window passes, sending succeeds again
        guard_sender.check_rate_limit(sender, now=1065.0)

    def test_anti_spam_guard_freshness_and_replay(self):
        guard = AntiSpamGuard(tolerance=300)
        now = int(time.time())

        # Fresh timestamp accepted
        guard.check_freshness(now)
        guard.check_freshness(now - 100)
        guard.check_freshness(now + 100)

        # Stale timestamp rejected
        with self.assertRaises(ProtocolError):
            guard.check_freshness(now - 350)
        with self.assertRaises(ProtocolError):
            guard.check_freshness(now + 350)

        # Replay rejection
        msg_id = 'msg-unique-1234'
        guard.check_replay(msg_id)
        with self.assertRaises(ProtocolError) as ctx:
            guard.check_replay(msg_id)
        self.assertEqual(ctx.exception.code, 'REPLAY_DETECTED')

        # Bad subject/body
        with self.assertRaises(ProtocolError):
            guard.validate_content('', 'valid body')
        with self.assertRaises(ProtocolError):
            guard.validate_content('subject\nnewline', 'valid body')
        with self.assertRaises(ProtocolError):
            guard.validate_content('valid subject', '')

    def test_authenticated_relay_and_end_to_end_forwarding(self):
        corium_channel = CoriumMailChannel(forum_db=self.forum_db, objects_dir=self.objects_dir)
        etp_channel = ETPMailChannel(mailbox_store_dir=self.etp_store)

        unified = UnifiedMail(
            node_id='test-relay-node-1',
            signing_key=self.relay_key,
            corium_channel=corium_channel,
            etp_channel=etp_channel
        )

        att = {
            'id': 'cf1-' + '1' * 64,
            'name': 'data.csv',
            'size': 4096,
            'digest': 'sha256:' + '2' * 64,
            'mime': 'text/csv',
            'merkle_root': '3' * 64,
            'v': 1
        }

        # 1. Forward to Corium destination
        cor_dest = 'bob@gateway.corium'
        receipt_cor = unified.send(
            sender_private_key=self.sender_key,
            from_address='alice@node.ziokt',
            to_address=cor_dest,
            subject='Relayed Corium Dispatch',
            body='Authentic cross-node transmission',
            attachments=[att]
        )
        self.assertEqual(receipt_cor['schema'], 'ziokt.signed.v1')
        self.assertEqual(receipt_cor['payload']['channel'], 'corium')
        self.assertEqual(receipt_cor['payload']['status'], 'relayed')
        self.assertEqual(receipt_cor['payload']['sender'], 'alice@node.ziokt')

        # Verify Corium channel received the mail
        cor_inbox = corium_channel.inbox('bob')
        self.assertEqual(len(cor_inbox), 1)
        self.assertEqual(cor_inbox[0]['content']['subject'], 'Relayed Corium Dispatch')

        # 2. Forward to ETP destination
        etp_dest = 'carol@peer.etp'
        receipt_etp = unified.send(
            sender_private_key=self.sender_key,
            from_address='alice@node.ziokt',
            to_address=etp_dest,
            subject='Relayed ETP Notice',
            body='Sealed packet forwarded via relay',
            attachments=[]
        )
        self.assertEqual(receipt_etp['payload']['channel'], 'etp')
        etp_inbox = etp_channel.inbox('carol')
        self.assertEqual(len(etp_inbox), 1)
        self.assertEqual(etp_inbox[0]['payload']['subject'], 'Relayed ETP Notice')

        # 3. Tampered envelope signature must be rejected
        bad_envelope = unified.create_envelope(
            sender_private_key=self.sender_key,
            from_address='alice@node.ziokt',
            to_address=cor_dest,
            subject='Tamper Test',
            body='Original text'
        )
        bad_envelope['payload']['body'] = 'Forged altered text'
        with self.assertRaises(ProtocolError) as ctx:
            unified.relay.forward(bad_envelope)
        self.assertEqual(ctx.exception.code, 'SIGNATURE_REJECTED')


if __name__ == '__main__':
    unittest.main()

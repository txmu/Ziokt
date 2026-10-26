from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

from ziokt.mail import UnifiedMail,CommunityMailChannel
from ziokt.mcp import Service
from ziokt.protocol import ProtocolError


class MailSurvivalTests(unittest.TestCase):
    def test_long_outage_restart_retry_and_persistent_idempotency(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);key=secrets.token_bytes(32)
            channel=CommunityMailChannel(mailbox_db=root/'inbox.db')
            first=UnifiedMail(community_channel=channel,relay_db=root/'relay.db')
            envelope=first.create_envelope(key,'alice@node.ziokt','bob@home.ziokt','offline','survives a long outage',timestamp=1000)
            with patch('ziokt.mail.time.time',return_value=1000),patch.object(channel,'send',side_effect=OSError('offline')):
                self.assertEqual(first.relay.forward(envelope)['status'],'failed')
            resumed=UnifiedMail(community_channel=channel,relay_db=root/'relay.db')
            with patch('ziokt.mail.time.time',return_value=5000):
                self.assertEqual(resumed.retry_failed()['succeeded'],1)
                self.assertEqual(resumed.relay.forward(envelope)['status'],'relayed')
            self.assertEqual(len(channel.inbox('bob')),1)
            import sqlite3
            with sqlite3.connect(root/'relay.db') as db:self.assertEqual(db.execute('SELECT attempts FROM delivery_log').fetchone()[0],2)

    def test_distinct_same_second_messages_do_not_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as directory:
            channel=CommunityMailChannel(mailbox_db=Path(directory)/'mail.db')
            first=channel.send('sender','bob',subject='same',body='first',timestamp=1000)
            second=channel.send('sender','bob',subject='same',body='second',timestamp=1000)
            self.assertNotEqual(first['message_id'],second['message_id'])
            self.assertEqual(len(channel.inbox('bob')),2)

    def test_mcp_mail_identity_is_stable_and_mailbox_reads_are_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            config={'state':directory,'bridges':{},'clients':{},'issuer':'https://test.invalid'}
            service=Service(config);self.addCleanup(service.close)
            alice={'client':'alice','scopes':['mail:read','mail:write']};bob={'client':'bob','scopes':['mail:read','mail:write']}
            a=service.execute(alice,'mail_identity',{});b=service.execute(bob,'mail_identity',{})
            self.assertNotEqual(a['public_key'],b['public_key'])
            service.execute(alice,'mail_send',{'to':b['address'],'subject':'Hi','body':'persistent native delivery'})
            inbox=service.execute(bob,'mail_inbox',{'recipient':b['public_key'],'channel':'community'})
            self.assertEqual(len(inbox['community']),1)
            with self.assertRaises(ProtocolError):service.execute(alice,'mail_inbox',{'recipient':b['public_key']})
            restarted=Service(config);self.addCleanup(restarted.close)
            self.assertEqual(restarted.execute(alice,'mail_identity',{})['public_key'],a['public_key'])

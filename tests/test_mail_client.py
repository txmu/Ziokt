from contextlib import closing
from email.message import EmailMessage
from email.parser import BytesParser
from email import policy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from ziokt.mail_accounts import InternetAccounts
from ziokt.mail_internet import InternetMail
from ziokt.mail_receive import describe,quarantine,import_attachment
from ziokt.protocol import ProtocolError
from ziokt.security import sign

class MailClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.pub=sign({},secrets.token_bytes(32),'test')['public_key']
        self.secret=self.root/'secret';self.secret.write_text(json.dumps({'username':'alice','password':'test'}));self.secret.chmod(0o600)
        self.config={'account':'a','from_address':'alice@example.org','local_recipient':'alice','allowed_senders':[self.pub],'secret_file':str(self.secret),'smtp':{'host':'localhost','port':465,'tls':'implicit'}}
    def channel(self):return InternetMail(self.config,self.root/'state')
    def test_display_reply_to_and_thread_headers(self):
        self.config['identity_bindings']={self.pub:{'native_address':'alice@node.ziokt','addresses':['alice@example.org'],'display_name':'Alice 邮件','reply_to':'alice@example.org'}}
        channel=self.channel();channel.send(self.pub,'b@example.org','Re: Hello','reply',native_address='alice@node.ziokt',in_reply_to='<original@example.org>',references=['<first@example.org>','<original@example.org>'])
        with closing(sqlite3.connect(channel.db)) as db:raw=db.execute('SELECT raw FROM outbox').fetchone()[0]
        message=BytesParser(policy=policy.default).parsebytes(raw)
        self.assertIn('Alice',message['From']);self.assertEqual(message['Reply-To'],'alice@example.org');self.assertEqual(message['In-Reply-To'],'<original@example.org>')
        self.assertEqual(str(message['References']),'<first@example.org> <original@example.org>')
        with self.assertRaises(ProtocolError):channel.send(self.pub,'b@example.org','bad','x',native_address='alice@node.ziokt',in_reply_to='<bad@example.org>\r\nBcc: x')
    def test_external_html_is_inert_and_forged_auth_headers_untrusted(self):
        message=EmailMessage();message['Authentication-Results']='mx.example.org; spf=pass; dkim=pass; dmarc=pass';message['Message-ID']='<x@example.org>';message.set_content('<script>steal()</script><p>Hello</p><img src="https://tracker">',subtype='html')
        _,item=describe(message.as_bytes());self.assertFalse(item['authentication_results']['trusted']);self.assertFalse(item['sender_signature_verified']);self.assertNotIn('steal',item['body']);self.assertNotIn('<img',item['body'])
        _,item=describe(message.as_bytes(),['mx.example.org']);self.assertEqual(item['authentication_results']['dmarc'],'pass');self.assertFalse(item['internet_authentication_verified'])
        message['Authentication-Results']='mx.example.org; dkim=pass'
        self.assertFalse(describe(message.as_bytes(),['mx.example.org'])[1]['authentication_results']['trusted'])
    def test_inbound_mime_quarantine_scan_and_private_fabric_import(self):
        scanner=self.root/'scan.py';scanner.write_text('raise SystemExit(0)\n')
        self.config['attachment_export']={'scanner':[sys.executable,str(scanner)]};self.config['inbound_content']={'root':str(self.root/'fabric'),'owner':'alice'}
        channel=self.channel();message=EmailMessage();message.set_content('external');message.add_attachment(b'incoming bytes',maintype='application',subtype='octet-stream',filename='file.bin')
        ids=quarantine(channel,'7',1,message.as_bytes());self.assertEqual(quarantine(channel,'7',1,message.as_bytes()),ids)
        with closing(sqlite3.connect(channel.db)) as db:self.assertEqual(db.execute('SELECT status FROM attachments').fetchone()[0],'quarantined')
        descriptor=import_attachment(channel,ids[0]);self.assertEqual(import_attachment(channel,ids[0]),descriptor)
        from ziokt.content_fabric import Fabric
        fabric=Fabric(self.root/'fabric');self.addCleanup(fabric.close)
        self.assertEqual(fabric.read_chunk('alice',descriptor['id'],0),b'incoming bytes')
        with self.assertRaises(PermissionError):fabric.read_chunk('bob',descriptor['id'],0)
    def test_oauth_refresh_rotates_private_tokens_and_smtp_uses_xoauth2(self):
        self.config['auth']='oauth2';self.secret.write_text(json.dumps({'username':'alice@example.org','provider':'google','client_id':'test','access_token':'old','refresh_token':'refresh','expires_at':0}))
        response=unittest.mock.MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'access_token':'new','expires_in':3600,'refresh_token':'rotated'}).encode()
        with patch('ziokt.mail_oauth.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=response
            channel=self.channel();self.assertEqual(channel.credentials(),('alice@example.org','new'))
        self.assertEqual(json.loads(self.secret.read_text())['refresh_token'],'rotated');self.assertEqual(self.secret.stat().st_mode&0o777,0o600)
        channel.send(self.pub,'b@example.org','oauth','body')
        with patch('ziokt.mail_internet.smtplib.SMTP_SSL') as smtp:
            smtp.return_value.sendmail.return_value={};self.assertEqual(channel.flush()['results'][0]['status'],'sent');smtp.return_value.login.assert_not_called()
            callback=smtp.return_value.auth.call_args.args[1];self.assertIn('auth=Bearer new',callback());self.assertEqual(callback(b'error'),'')
    def test_multiple_accounts_are_isolated_and_scheduled_without_manual_flush(self):
        accounts=InternetAccounts({'accounts':[self.config,{**self.config,'account':'b','from_address':'other@example.org','allowed_senders':[]}],'sync_interval':30},self.root/'accounts')
        accounts.send(self.pub,'b@example.org','a','body',internet_account='a')
        with self.assertRaises(ProtocolError):accounts.send(self.pub,'b@example.org','b','body',internet_account='b')
        with patch.object(accounts.accounts['a'],'flush') as a,patch.object(accounts.accounts['b'],'flush') as b:
            accounts.start()
            for _ in range(100):
                if a.called and b.called:break
                time.sleep(.01)
            accounts.close();self.assertTrue(a.called and b.called)
        self.assertEqual(accounts.accounts['a'].status()['outbox'],{'queued':1});self.assertEqual(accounts.accounts['b'].status()['outbox'],{})
    def test_alfs_serial_marker_handles_real_carriage_return_and_exit_codes(self):
        spec=importlib.util.spec_from_file_location('alfs_boot',Path(__file__).resolve().parents[1]/'ci/openci/alfs/boot.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        marker=module.check_pattern('ROOTFS')
        self.assertEqual(re.search(marker,'\x1b[?2004l\rOPENCI_ALFS_ROOTFS:0\r\r\n')[1],'0')
        self.assertEqual(re.search(marker,'\nOPENCI_ALFS_ROOTFS:1\r\n')[1],'1')
        self.assertIsNone(re.search(marker,"printf '\\nOPENCI_ALFS_ROOTFS:%s\\n' \"$result\"\r\n"))
    def test_imap_xoauth2_and_scheduler_authorization_boundary(self):
        self.config.update(auth='oauth2',imap={'host':'localhost','port':993,'tls':'implicit'})
        self.secret.write_text(json.dumps({'username':'alice@example.org','provider':'microsoft','access_token':'access','expires_at':int(time.time())+3600}))
        channel=self.channel()
        with patch('ziokt.mail_internet.imaplib.IMAP4_SSL') as imap:
            client=imap.return_value;client.select.return_value=('OK',[]);client.uid.return_value=('OK',[b''])
            client.response.side_effect=lambda name:(name,[b'7' if name=='UIDVALIDITY' else b'1'])
            self.assertEqual(channel.poll()['imported'],0);client.login.assert_not_called()
            callback=client.authenticate.call_args.args[1];self.assertIn(b'auth=Bearer access',callback(b''));self.assertEqual(callback(b'error'),b'')
        accounts=InternetAccounts({'accounts':[self.config]},self.root/'revoked-worker');accounts.authorization=lambda scope:False
        with patch.object(accounts.accounts['a'],'flush') as flush,patch.object(accounts.accounts['a'],'poll') as poll:
            accounts.sync_once();flush.assert_not_called();poll.assert_not_called()
        self.assertEqual(accounts.last_sync['a']['flush'],'authorization_revoked')
    def test_scanner_failure_keeps_inbound_attachment_quarantined(self):
        scanner=self.root/'reject.py';scanner.write_text('raise SystemExit(1)\n')
        self.config['attachment_export']={'scanner':[sys.executable,str(scanner)]};self.config['inbound_content']={'root':str(self.root/'never-published'),'owner':'alice'}
        channel=self.channel();message=EmailMessage();message.set_content('text');message.add_attachment(b'bytes',maintype='application',subtype='octet-stream',filename='unsafe.bin')
        identity=quarantine(channel,'7',2,message.as_bytes())[0]
        with self.assertRaises(ProtocolError):import_attachment(channel,identity)
        with closing(sqlite3.connect(channel.db)) as db:self.assertEqual(db.execute('SELECT status FROM attachments').fetchone()[0],'quarantined')
        self.assertFalse((self.root/'never-published').exists())
    def test_read_receipts_default_deny_explicit_send_and_persistent_block(self):
        from ziokt.mail_receipts import preference,respond
        channel=self.channel();message=EmailMessage();message['From']='bob@example.net';message['Message-ID']='<original@example.net>';message['Disposition-Notification-To']='bob@example.net';message.set_content('external mail')
        with closing(sqlite3.connect(channel.db)) as db,db:
            for uid in (1,2):db.execute('INSERT INTO inbox VALUES(?,?,?,?,?,?)',('a','7',uid,'alice',message.as_bytes(),1234))
        self.assertEqual(preference(channel)['policy'],'deny')
        with self.assertRaises(ProtocolError):respond(channel,self.pub,'alice@node.ziokt','7:1','send')
        self.assertEqual(respond(channel,self.pub,'alice@node.ziokt','7:2','block')['status'],'blocked')
        preference(channel,'manual');result=respond(channel,self.pub,'alice@node.ziokt','7:1','send')
        self.assertEqual(result['status'],'queued');self.assertEqual(respond(channel,self.pub,'alice@node.ziokt','7:1','send')['message_id'],result['message_id'])
        self.assertEqual(respond(channel,self.pub,'alice@node.ziokt','7:2','send')['status'],'blocked')
        with closing(sqlite3.connect(channel.db)) as db:raw=db.execute('SELECT raw FROM outbox').fetchone()[0]
        parsed,item=describe(raw);self.assertEqual(parsed.get_content_type(),'multipart/report');self.assertEqual(item['receipt_reports'][0]['original_message_id'],'<original@example.net>');self.assertFalse(item['receipt_reports'][0]['trusted'])
        self.assertEqual(channel.status()['outbox'],{'queued':1})
    def test_outgoing_read_receipt_request_is_opt_in_and_cannot_be_redirected(self):
        channel=self.channel();channel.send(self.pub,'bob@example.net','no request','body',timestamp=1)
        channel.send(self.pub,'bob@example.net','request','body',timestamp=2,request_read_receipt=True)
        with closing(sqlite3.connect(channel.db)) as db:messages=[BytesParser(policy=policy.default).parsebytes(r[0]) for r in db.execute('SELECT raw FROM outbox')]
        self.assertEqual(sum(bool(m.get('Disposition-Notification-To')) for m in messages),1)
        for message in messages:
            if message.get('Disposition-Notification-To'):self.assertEqual(message['Disposition-Notification-To'],'alice@example.org')

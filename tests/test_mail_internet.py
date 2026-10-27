from contextlib import closing
import datetime
from pathlib import Path
import secrets
import smtplib
import socketserver
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from ziokt.mail import UnifiedMail
from ziokt.mail_internet import InternetMail
from ziokt.protocol import ProtocolError
from ziokt.security import sign


class MailInternetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.key=secrets.token_bytes(32);self.pub=sign({},self.key,'test')['public_key']
        secret=self.root/'secret';secret.write_text('{"username":"test","password":"test-secret"}');secret.chmod(0o600)
        self.config={'account':'primary','from_address':'alice@example.org','local_recipient':'alice','secret_file':str(secret),'allowed_senders':[self.pub],
                     'smtp':{'host':'localhost','port':465,'tls':'implicit'},'imap':{'host':'localhost','port':993,'tls':'implicit'}}

    def test_persistent_queue_sender_authorization_and_uncertain_delivery(self):
        channel=InternetMail(self.config,self.root/'state')
        with self.assertRaises(ProtocolError):channel.send('a'*64,'bob@example.net','Hi','Body')
        with self.assertRaises(ProtocolError):channel.send(self.pub,'bob@example.net','Hi\r\nBcc: evil@example.org','Body')
        message=channel.send(self.pub,'bob@example.net','Hi','offline body',timestamp=1234)
        again=InternetMail(self.config,self.root/'state')
        self.assertEqual(again.status()['outbox'],{'queued':1})
        with patch('ziokt.mail_internet.smtplib.SMTP_SSL') as smtp:
            smtp.return_value.sendmail.side_effect=smtplib.SMTPServerDisconnected('after DATA')
            result=again.flush()
        self.assertEqual(result['results'][0]['status'],'uncertain')
        with patch('ziokt.mail_internet.smtplib.SMTP_SSL') as smtp:
            self.assertEqual(again.flush()['results'],[]);smtp.assert_not_called()
        self.assertEqual(message['delivery_status'],'queued')

    def test_airgap_denies_network_without_losing_outbox(self):
        channel=InternetMail(self.config,self.root/'airgap')
        channel.send(self.pub,'bob@example.net','offline','queued safely')
        with patch('ziokt.mail_internet.require_network',side_effect=ProtocolError('AIRGAP_DENIED','offline')),patch('ziokt.mail_internet.smtplib.SMTP_SSL') as smtp:
            with self.assertRaises(ProtocolError):channel.flush()
            with self.assertRaises(ProtocolError):channel.poll()
            smtp.assert_not_called()
        self.assertEqual(channel.status()['outbox'],{'queued':1})

    def test_actual_tls_smtp_imap_roundtrip_and_uid_dedup(self):
        private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')]);now=datetime.datetime.now(datetime.timezone.utc)
        certificate=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False).sign(private,hashes.SHA256())
        cert=self.root/'cert.pem';cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM));key=self.root/'cert.key';key.write_bytes(private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
        messages=[]
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address=True
            daemon_threads=True
            def get_request(self):
                connection,remote=super().get_request();connection.settimeout(5)
                return context.wrap_socket(connection,server_side=True),remote
        class SMTP(socketserver.StreamRequestHandler):
            def handle(self):
                self.wfile.write(b'220 localhost test SMTP\r\n')
                while line:=self.rfile.readline(4096):
                    command=line.split()[0].upper()
                    if command==b'EHLO':self.wfile.write(b'250-localhost\r\n250 AUTH PLAIN\r\n')
                    elif command==b'AUTH':self.wfile.write(b'235 authenticated\r\n')
                    elif command in (b'MAIL',b'RCPT'):self.wfile.write(b'250 accepted\r\n')
                    elif command==b'DATA':
                        self.wfile.write(b'354 message\r\n');parts=[]
                        while (data:=self.rfile.readline(65536))!=b'.\r\n':
                            if not data:return
                            parts.append(data[1:] if data.startswith(b'..') else data)
                        messages.append(b''.join(parts));self.wfile.write(b'250 stored\r\n')
                    elif command==b'QUIT':self.wfile.write(b'221 bye\r\n');return
                    else:self.wfile.write(b'500 unknown\r\n')
        class IMAP(socketserver.StreamRequestHandler):
            def handle(self):
                self.wfile.write(b'* OK IMAP test ready\r\n')
                while line:=self.rfile.readline(4096):
                    tag,command,*arguments=line.strip().split();command=command.upper()
                    if command==b'CAPABILITY':self.wfile.write(b'* CAPABILITY IMAP4rev1 AUTH=PLAIN\r\n')
                    elif command==b'LOGIN':pass
                    elif command in (b'SELECT',b'EXAMINE'):self.wfile.write(b'* 1 EXISTS\r\n* OK [UIDVALIDITY 7] valid\r\n* OK [UIDNEXT 102] next\r\n')
                    elif command==b'UID' and arguments[0].upper()==b'SEARCH':
                        low=int(arguments[-1].split(b':')[0]);self.wfile.write(b'* SEARCH'+(b' 101' if low<=101 else b'')+b'\r\n')
                    elif command==b'UID' and b'RFC822.SIZE' in line:self.wfile.write(b'* 1 FETCH (UID 101 RFC822.SIZE '+str(len(messages[0])).encode()+b')\r\n')
                    elif command==b'UID' and b'BODY.PEEK' in line:self.wfile.write(b'* 1 FETCH (UID 101 BODY[] {'+str(len(messages[0])).encode()+b'}\r\n'+messages[0]+b')\r\n')
                    elif command==b'LOGOUT':self.wfile.write(b'* BYE closing\r\n'+tag+b' OK logout\r\n');return
                    else:self.wfile.write(tag+b' BAD unknown\r\n');continue
                    self.wfile.write(tag+b' OK done\r\n')
        servers=[]
        for handler in (SMTP,IMAP):
            server=Server(('127.0.0.1',0),handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();servers.append((server,thread))
            self.addCleanup(server.server_close);self.addCleanup(thread.join,3);self.addCleanup(server.shutdown)
        self.config['smtp']['port']=servers[0][0].server_address[1];self.config['imap']['port']=servers[1][0].server_address[1];self.config['ca_file']=str(cert)
        internet=InternetMail(self.config,self.root/'real')
        unified=UnifiedMail(internet_channel=internet,mailbox_db=self.root/'native.db',relay_db=self.root/'relay.db')
        receipt=unified.send(self.key,'alice@home.ziokt','bob@example.net','Hello internet','Unicode 邮件 survives')
        self.assertEqual(receipt['status'],'queued')
        self.assertEqual(internet.flush()['results'][0]['status'],'sent')
        self.assertEqual(len(messages),1);self.assertIn(b'Message-ID:',messages[0])
        self.assertEqual(internet.poll()['imported'],1)
        self.assertEqual(internet.poll()['imported'],0)
        inbox=unified.inbox('alice',channel='internet')['internet']
        self.assertEqual(len(inbox),1);self.assertIn('Unicode 邮件 survives',inbox[0]['body']);self.assertFalse(inbox[0]['sender_signature_verified'])
        self.assertEqual(internet.inbox('another-user'),[])

    def test_native_alias_mapping_is_signed_and_durable_and_revocable(self):
        import json,sqlite3
        from email.parser import BytesParser
        from email import policy
        self.config['identity_bindings']={self.pub:{'native_address':'alice@home.ziokt','addresses':['alice@example.org','a@example.org'],'email_verification':'operator_attested'}}
        channel=InternetMail(self.config,self.root/'aliases')
        unified=UnifiedMail(internet_channel=channel,mailbox_db=self.root/'mapping.db',relay_db=self.root/'mapping-relay.db')
        result=unified.send(self.key,'alice@home.ziokt','bob@example.net','alias','hello',internet_from='a@example.org')
        self.assertEqual(result['details']['internet_from'],'a@example.org');self.assertTrue(result['details']['native_signature_verified']);self.assertFalse(result['details']['email_ownership_verified'])
        with closing(sqlite3.connect(channel.db)) as db:raw,mail_from=db.execute('SELECT raw,mail_from FROM outbox').fetchone()
        self.assertEqual(BytesParser(policy=policy.default).parsebytes(raw)['From'],'a@example.org');self.assertEqual(mail_from,'a@example.org')
        with patch('ziokt.mail_internet.smtplib.SMTP_SSL') as smtp:
            smtp.return_value.sendmail.return_value={}
            self.assertEqual(channel.flush()['results'][0]['status'],'sent')
            self.assertEqual(smtp.return_value.sendmail.call_args.args[0],'a@example.org')
        with self.assertRaises(ProtocolError):channel.send(self.pub,'bob@example.net','x','x',native_address='wrong@home.ziokt')
        with self.assertRaises(ProtocolError):channel.send(self.pub,'bob@example.net','x','x',native_address='alice@home.ziokt',internet_from='evil@example.org')
        channel.send(self.pub,'bob@example.net','revoke','x',native_address='alice@home.ziokt',internet_from='a@example.org')
        self.config['identity_bindings'][self.pub]['addresses']=['alice@example.org']
        with patch('ziokt.mail_internet.smtplib.SMTP_SSL') as smtp:
            self.assertEqual(channel.flush()['results'][0]['status'],'failed');smtp.assert_not_called()

    def test_actual_content_fabric_authorization_mime_export_and_scan_failures(self):
        import hashlib,sqlite3,sys
        from email.parser import BytesParser
        from email import policy
        from ziokt.content_fabric import Fabric
        from ziokt.content_server import server
        fabric=Fabric(self.root/'fabric');self.addCleanup(fabric.close)
        data=b'Gmail-readable attachment bytes';digest='sha256:'+hashlib.sha256(data).hexdigest()
        fabric.begin('alice','upload',len(data),digest,'text/plain');fabric.put('alice','upload',0,data);obj=fabric.finish('alice','upload')
        http=server(fabric,{'port':0,'tokens':[{'account':'alice','token':'a'*40,'scopes':['content:read']},{'account':'bob','token':'b'*40,'scopes':['content:read']}]})
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        self.addCleanup(http.server_close);self.addCleanup(thread.join,3);self.addCleanup(http.shutdown)
        token=self.root/'content.token';token.write_text('a'*40);token.chmod(0o600)
        scanner=self.root/'scanner.py';scanner.write_text('import pathlib,sys\nassert pathlib.Path(sys.argv[1]).read_bytes()=='+repr(data)+'\n')
        self.config['attachment_export']={'mode':'mime','content_url':'http://127.0.0.1:'+str(http.server_port),'scanner':[sys.executable,str(scanner)]}
        self.config['identity_bindings']={self.pub:{'native_address':'alice@home.ziokt','addresses':['alice@example.org'],'content_token_file':str(token)}}
        channel=InternetMail(self.config,self.root/'mime')
        descriptor={'id':obj['id'],'size':len(data),'digest':digest,'name':'readme.txt','mime':'text/plain'}
        channel.send(self.pub,'bob@gmail.com','attachment','hello',[descriptor],native_address='alice@home.ziokt')
        with closing(sqlite3.connect(channel.db)) as db:raw=db.execute('SELECT raw FROM outbox').fetchone()[0]
        message=BytesParser(policy=policy.default).parsebytes(raw);part=list(message.iter_attachments())[0]
        self.assertEqual(part.get_filename(),'readme.txt');self.assertEqual(part.get_payload(decode=True),data)
        token.write_text('b'*40)
        with self.assertRaises(ProtocolError):channel.send(self.pub,'bob@gmail.com','denied','x',[descriptor],native_address='alice@home.ziokt')
        token.write_text('a'*40)
        for broken in [{**descriptor,'digest':'sha256:'+'0'*64},{**descriptor,'size':600000},{**descriptor,'mime':'text/plain\r\nInjected: yes'}]:
            with self.assertRaises(ProtocolError):channel.send(self.pub,'bob@gmail.com','invalid','x',[broken],native_address='alice@home.ziokt')
        scanner.write_text('raise SystemExit(1)\n')
        with self.assertRaises(ProtocolError):channel.send(self.pub,'bob@gmail.com','unsafe','x',[descriptor],native_address='alice@home.ziokt')
        self.assertEqual(channel.status()['outbox'],{'queued':1})

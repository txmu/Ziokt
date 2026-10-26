"""Explicit TLS-only SMTP submission and UID-based IMAP collection.

The durable outbox works while offline. Ambiguous SMTP DATA failures require
operator review rather than silently resending a potentially accepted message.
"""
from contextlib import closing
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
import hashlib
import imaplib
import json
from pathlib import Path
import re
import smtplib
import sqlite3
import ssl
import time

from .package_storage import safe_path
from .protocol import ProtocolError, secure_read, strict_json
from .runtime_policy import require_network

MAX_MESSAGE = 1024 * 1024


def address(value):
    if (not isinstance(value, str) or len(value) > 254 or
            not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9.-]{1,189}", value)):
        raise ProtocolError('INVALID_ADDRESS', 'plain internet mailbox address required')
    local, domain = value.rsplit('@', 1)
    if local.startswith('.') or local.endswith('.') or '..' in local or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in domain.split('.')):
        raise ProtocolError('INVALID_ADDRESS', 'canonical internet mailbox required')
    return local+'@'+domain.lower()


class InternetMail:
    def __init__(self, config, state):
        if (not isinstance(config, dict) or set(config)-{'account','from_address','local_recipient','smtp','imap','secret_file','ca_file','allowed_senders'} or
                not isinstance(config.get('account'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', config['account'])):
            raise ProtocolError('INVALID_CONFIG', 'explicit internet mail account required')
        self.config = config
        senders=config.get('allowed_senders',[])
        if not isinstance(senders,list) or len(senders)>64 or any(not isinstance(key,str) or not re.fullmatch('[a-f0-9]{64}',key) for key in senders):
            raise ProtocolError('INVALID_CONFIG','bounded authorized internet mail senders required')
        self.sender = address(config['from_address'])
        if not isinstance(config.get('local_recipient'),str) or not re.fullmatch(r'[A-Za-z0-9_.@+-]{1,160}',config['local_recipient']):
            raise ProtocolError('INVALID_CONFIG','explicit native inbox mapping required')
        for kind in ('smtp','imap'):
            settings = config.get(kind)
            if settings is None: continue
            if (not isinstance(settings,dict) or set(settings)-{'host','port','tls','mailbox'} or
                    not isinstance(settings.get('host'),str) or not re.fullmatch(r'[A-Za-z0-9.-]{1,253}',settings['host']) or
                    type(settings.get('port')) is not int or not 1<=settings['port']<=65535 or
                    settings.get('tls') not in {'implicit','starttls'}):
                raise ProtocolError('INVALID_CONFIG','explicit TLS mail endpoint required')
            if kind=='imap' and not re.fullmatch(r'[A-Za-z0-9_. /-]{1,64}',settings.get('mailbox','INBOX')):
                raise ProtocolError('INVALID_CONFIG','bounded IMAP mailbox required')
        self.root=Path(state);self.root.mkdir(parents=True,mode=0o700,exist_ok=True)
        self.db=safe_path(self.root,'internet-mail.db')
        with closing(sqlite3.connect(self.db)) as db,db:
            db.executescript('''CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, recipient TEXT, raw BLOB, status TEXT, attempts INTEGER, next_attempt INTEGER, error TEXT);
            CREATE TABLE IF NOT EXISTS inbox (account TEXT, validity TEXT, uid INTEGER, recipient TEXT, raw BLOB, received_at INTEGER, PRIMARY KEY(account,validity,uid));
            CREATE TABLE IF NOT EXISTS cursors (account TEXT, mailbox TEXT, validity TEXT, uid INTEGER, PRIMARY KEY(account,mailbox));''')
            db.execute('CREATE TABLE IF NOT EXISTS identity (id INTEGER PRIMARY KEY CHECK(id=1), binding TEXT)')
            binding=json.dumps([config['account'],self.sender,config['local_recipient']])
            previous=db.execute('SELECT binding FROM identity WHERE id=1').fetchone()
            if previous and previous[0]!=binding:raise ProtocolError('MAIL_ACCOUNT_MISMATCH','use an independent state directory for each account')
            db.execute('INSERT OR IGNORE INTO identity VALUES (1,?)',(binding,))
            # A process that died during DATA cannot safely assume delivery failed.
        self.db.chmod(0o600)

    def credentials(self):
        secret=strict_json(secure_read(Path(self.config['secret_file']),8192),8192)
        if (not isinstance(secret,dict) or set(secret)!={'username','password'} or
                any(not isinstance(secret[k],str) or not 1<=len(secret[k])<=2048 or '\r' in secret[k] or '\n' in secret[k] for k in secret)):
            raise ProtocolError('INVALID_CONFIG','private username/password file required')
        return secret['username'],secret['password']

    def context(self):
        return ssl.create_default_context(cafile=self.config.get('ca_file'))

    def send(self, sender_key, recipient, subject, body, attachments=None, timestamp=None, message_id=None):
        if sender_key not in self.config.get('allowed_senders',[]):
            raise ProtocolError('POLICY_DENIED','sender is not authorized for this SMTP account')
        recipient=address(recipient)
        if not self.config.get('smtp'):raise ProtocolError('MAIL_UNAVAILABLE','SMTP is not configured')
        if not isinstance(subject,str) or len(subject)>256 or '\r' in subject or '\n' in subject or not isinstance(body,str) or len(body)>65536:
            raise ProtocolError('INVALID_PAYLOAD','bounded mail text required')
        if attachments:
            from .mail import validate_attachments
            attachments=validate_attachments(attachments)
            body+='\n\nContent Fabric references (availability requires Ziokt):\n'+json.dumps(attachments,ensure_ascii=False)
        message=EmailMessage(policy=policy.SMTP)
        message['From']=self.sender;message['To']=recipient;message['Subject']=subject
        from email.utils import formatdate
        timestamp=timestamp if timestamp is not None else time.time_ns()
        message['Date']=formatdate(timestamp/1e9 if timestamp>2**40 else timestamp,usegmt=True)
        # Include the body digest so two distinct messages in the same second remain distinct.
        identity=hashlib.sha256((self.config['account']+'\0'+str(sender_key)+'\0'+recipient+'\0'+str(message_id or timestamp)+'\0'+subject+'\0'+body).encode()).hexdigest()
        message['Message-ID']='<'+identity+'@'+self.sender.rsplit('@',1)[1]+'>'
        message.set_content(body)
        raw=message.as_bytes()
        if len(raw)>MAX_MESSAGE:raise ProtocolError('MAIL_LIMIT','internet mail budget exceeded')
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute("INSERT OR IGNORE INTO outbox VALUES (?,?,?,'queued',0,0,'')",(identity,recipient,raw))
        return {'channel':'internet','message_id':identity,'delivery_status':'queued'}

    def flush(self, limit=10):
        require_network()
        if type(limit) is not int or not 1<=limit<=50:raise ProtocolError('MAIL_LIMIT','batch size 1..50 required')
        settings=self.config.get('smtp')
        if not settings:raise ProtocolError('MAIL_UNAVAILABLE','SMTP is not configured')
        results=[]
        for _ in range(limit):
            with closing(sqlite3.connect(self.db)) as db,db:
                db.execute('BEGIN IMMEDIATE')
                db.execute("UPDATE outbox SET status='uncertain',error='interrupted SMTP attempt' WHERE status='sending' AND next_attempt<?",(int(time.time()),))
                row=db.execute("SELECT id,recipient,raw,attempts FROM outbox WHERE status='queued' AND next_attempt<=? AND attempts<5 ORDER BY next_attempt,id LIMIT 1",(int(time.time()),)).fetchone()
                if not row:break
                identity,recipient,raw,attempts=row
                db.execute("UPDATE outbox SET status='sending',attempts=attempts+1,next_attempt=? WHERE id=?",(int(time.time())+120,identity))
            submitted=False;status='queued';error='';client=None
            try:
                username,password=self.credentials()
                if settings['tls']=='implicit':client=smtplib.SMTP_SSL(settings['host'],settings['port'],timeout=10,context=self.context())
                else:
                    client=smtplib.SMTP(settings['host'],settings['port'],timeout=10)
                    client.ehlo();client.starttls(context=self.context());client.ehlo()
                client.login(username,password)
                submitted=True
                refused=client.sendmail(self.sender,[recipient],raw)
                if refused:raise smtplib.SMTPRecipientsRefused(refused)
                status='sent'
            except smtplib.SMTPRecipientsRefused as exc:
                status='queued' if all(400<=entry[0]<500 for entry in exc.recipients.values()) else 'failed';error=type(exc).__name__
            except smtplib.SMTPResponseException as exc:
                status='queued' if 400<=exc.smtp_code<500 else 'failed';error=type(exc).__name__
            except (OSError,smtplib.SMTPException,ProtocolError) as exc:
                status='uncertain' if submitted else 'queued';error=type(exc).__name__
            finally:
                if client is not None:
                    try:client.close()
                    except OSError:pass
            if attempts+1>=5 and status=='queued':status='failed'
            with closing(sqlite3.connect(self.db)) as db,db:
                db.execute('UPDATE outbox SET status=?,next_attempt=?,error=? WHERE id=?',(status,int(time.time())+min(3600,30*2**attempts),error,identity))
            results.append({'message_id':identity,'status':status,'error':error})
        return {'results':results,'remaining':self.status()['outbox']}

    def resolve(self, message_id, decision):
        if not isinstance(message_id,str) or not re.fullmatch('[a-f0-9]{64}',message_id) or decision not in {'sent','retry'}:
            raise ProtocolError('INVALID_REQUEST','explicit uncertain message decision required')
        with closing(sqlite3.connect(self.db)) as db,db:
            changed=db.execute("UPDATE outbox SET status=?,next_attempt=0,attempts=0,error='' WHERE id=? AND status='uncertain'",('sent' if decision=='sent' else 'queued',message_id))
            if changed.rowcount!=1:raise ProtocolError('MAIL_NOT_FOUND','uncertain delivery not found')
        return {'message_id':message_id,'status':'sent' if decision=='sent' else 'queued'}

    def poll(self, limit=10):
        require_network()
        if type(limit) is not int or not 1<=limit<=50:raise ProtocolError('MAIL_LIMIT','batch size 1..50 required')
        settings=self.config.get('imap')
        if not settings:raise ProtocolError('MAIL_UNAVAILABLE','IMAP is not configured')
        username,password=self.credentials();client=None;imported=0
        try:
            if settings['tls']=='implicit':client=imaplib.IMAP4_SSL(settings['host'],settings['port'],ssl_context=self.context(),timeout=10)
            else:
                client=imaplib.IMAP4(settings['host'],settings['port'],timeout=10)
                client.starttls(ssl_context=self.context())
            client.login(username,password)
            mailbox=settings.get('mailbox','INBOX')
            if client.select(mailbox,readonly=True)[0]!='OK':raise ProtocolError('MAIL_UNAVAILABLE','IMAP mailbox rejected')
            validity=client.response('UIDVALIDITY')[1]
            if not validity or not isinstance(validity[0],bytes) or not re.fullmatch(rb'[1-9][0-9]{0,9}',validity[0]):raise ProtocolError('INVALID_MAIL','IMAP UIDVALIDITY required')
            validity=validity[0].decode();account=self.config['account']
            uidnext=client.response('UIDNEXT')[1]
            if not uidnext or not isinstance(uidnext[0],bytes) or not re.fullmatch(rb'[1-9][0-9]{0,9}',uidnext[0]):raise ProtocolError('INVALID_MAIL','IMAP UIDNEXT required')
            highest=int(uidnext[0])-1
            with closing(sqlite3.connect(self.db)) as db:
                cursor=db.execute('SELECT validity,uid FROM cursors WHERE account=? AND mailbox=?',(account,mailbox)).fetchone()
            last=cursor[1] if cursor and cursor[0]==validity else 0
            # UID windows bound SEARCH output, including after a long disconnected period.
            typ,values=client.uid('search',None,'UID',f'{last+1}:{last+500}')
            if typ!='OK' or not values or not isinstance(values[0],bytes) or len(values[0])>8192:raise ProtocolError('INVALID_MAIL','bounded IMAP UID search required')
            ids=values[0].split()
            if any(not re.fullmatch(rb'[1-9][0-9]{0,9}',uid) for uid in ids):raise ProtocolError('INVALID_MAIL','invalid IMAP UID')
            for uid in sorted({int(uid) for uid in ids if last<int(uid)<=last+500})[:limit]:
                typ,metadata=client.uid('fetch',str(uid),'(RFC822.SIZE)')
                sizes=re.findall(rb'RFC822.SIZE ([0-9]+)',b' '.join(item for item in metadata or [] if isinstance(item,bytes)))
                if typ!='OK' or len(sizes)!=1 or int(sizes[0])>MAX_MESSAGE:raise ProtocolError('MAIL_LIMIT','IMAP message exceeds budget')
                # Partial FETCH bounds literal allocation even if the server misreports size.
                typ,parts=client.uid('fetch',str(uid),f'(BODY.PEEK[]<0.{MAX_MESSAGE+1}>)')
                bodies=[item[1] for item in parts or [] if isinstance(item,tuple) and len(item)==2 and isinstance(item[1],bytes)]
                if typ!='OK' or len(bodies)!=1 or len(bodies[0])!=int(sizes[0]) or len(bodies[0])>MAX_MESSAGE:raise ProtocolError('INVALID_MAIL','complete bounded IMAP message required')
                with closing(sqlite3.connect(self.db)) as db,db:
                    db.execute('INSERT OR IGNORE INTO inbox VALUES (?,?,?,?,?,?)',(account,validity,uid,self.config['local_recipient'],bodies[0],int(time.time())))
                    db.execute('INSERT OR REPLACE INTO cursors VALUES (?,?,?,?)',(account,mailbox,validity,uid))
                imported+=1
            if not ids:
                with closing(sqlite3.connect(self.db)) as db,db:
                    db.execute('INSERT OR REPLACE INTO cursors VALUES (?,?,?,?)',(account,mailbox,validity,max(last,min(last+500,highest))))
        finally:
            if client is not None:
                try:client.logout()
                except (OSError,imaplib.IMAP4.error):pass
        return {'imported':imported,'account':self.config['account']}

    def inbox(self, recipient):
        if recipient!=self.config['local_recipient']:return []
        with closing(sqlite3.connect(self.db)) as db:
            rows=db.execute('SELECT validity,uid,raw,received_at FROM inbox WHERE recipient=? ORDER BY received_at DESC,uid DESC LIMIT 50',(recipient,)).fetchall()
        results=[]
        for validity,uid,raw,received in rows:
            message=BytesParser(policy=policy.default).parsebytes(raw)
            part=message.get_body(preferencelist=('plain',))
            try:body=part.get_content()[:65536] if part else ''
            except (LookupError,UnicodeError):body=''
            results.append({'id':f'{validity}:{uid}','subject':str(message.get('Subject',''))[:256],'from':str(message.get('From',''))[:320],
                            'body':body,'received_at':received,'channel':'internet','sender_signature_verified':False})
        return results

    def status(self):
        with closing(sqlite3.connect(self.db)) as db:
            counts=dict(db.execute('SELECT status,count(*) FROM outbox GROUP BY status'))
            incoming=db.execute('SELECT count(*) FROM inbox').fetchone()[0]
        return {'account':self.config['account'],'outbox':counts,'inbox_count':incoming,'offline_storage':True}

"""External MIME parsing: inert text, untrusted auth headers and private quarantine."""
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
import hashlib
import json
import re
from contextlib import closing
import sqlite3
from .protocol import ProtocolError

class InertHTML(HTMLParser):
    def __init__(self):super().__init__();self.hidden=0;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style','iframe','object'}:self.hidden+=1
    def handle_endtag(self,tag):
        if tag in {'script','style','iframe','object'}:self.hidden=max(0,self.hidden-1)
        if tag in {'p','div','br','li'}:self.parts.append('\n')
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)

def thread_id(value):
    if not isinstance(value,str) or len(value)>254 or not re.fullmatch(r'<[^<>\s\x00-\x1f\x7f]+@[^<>\s\x00-\x1f\x7f]+>',value):raise ProtocolError('INVALID_MAIL','bounded RFC message identifier required')
    return value

def describe(raw, authserv_ids=()):
    message=BytesParser(policy=policy.default).parsebytes(raw)
    part=message.get_body(preferencelist=('plain','html'))
    try:
        text=part.get_content() if part else ''
        if part and part.get_content_type()=='text/html':
            parser=InertHTML();parser.feed(text);text=''.join(parser.parts)
    except (LookupError,UnicodeError,ValueError):text=''
    auth={'trusted':False,'spf':'unverified','dkim':'unverified','dmarc':'unverified'}
    values=message.get_all('Authentication-Results',[])
    # Trust only an explicitly pinned receiving MTA that strips forged headers.
    if len(values)==1:
        header=str(values[0]);service=header.split(';',1)[0].strip()
        if service in authserv_ids:
            auth['trusted']=True
            for method in ('spf','dkim','dmarc'):
                found=re.search(r'(?:^|;)\s*'+method+r'=(pass|fail|softfail|neutral|none|temperror|permerror)\b',header,re.I)
                if found:auth[method]=found[1].lower()
    return message,{'subject':str(message.get('Subject',''))[:256],'from':str(message.get('From',''))[:320],
                    'to':str(message.get('To',''))[:2048],'cc':str(message.get('Cc',''))[:2048],'date':str(message.get('Date',''))[:128],'reply_to':str(message.get('Reply-To',''))[:320],'body':text[:65536],'body_format':'text/plain',
                    'rfc_message_id':str(message.get('Message-ID',''))[:254],'in_reply_to':str(message.get('In-Reply-To',''))[:254],
                    'references':str(message.get('References',''))[:4096],'authentication_results':auth,
                    'external_origin':True,'sender_signature_verified':False,'internet_authentication_verified':False}

def quarantine(channel,validity,uid,raw):
    message,_=describe(raw);attachments=[];total=0
    for position,part in enumerate(message.iter_attachments()):
        if position>=4:break
        data=part.get_payload(decode=True)
        if not isinstance(data,bytes):continue
        total+=len(data)
        if len(data)>256*1024 or total>512*1024:continue
        identity=hashlib.sha256((channel.config['account']+'\0'+validity+'\0'+str(uid)+'\0'+str(position)).encode()).hexdigest()
        name=part.get_filename() or 'attachment.bin'
        from .mail import sanitize_filename
        try:sanitize_filename(name)
        except ProtocolError:name='attachment.bin'
        with closing(sqlite3.connect(channel.db)) as db,db:
            db.execute('INSERT OR IGNORE INTO attachments VALUES(?,?,?,?,?,?,?,NULL)',(identity,validity,uid,name,part.get_content_type(),data,'quarantined'))
        attachments.append(identity)
    return attachments

def import_attachment(channel,identity):
    from .mail_export import scan
    with closing(sqlite3.connect(channel.db)) as db:
        row=db.execute('SELECT name,mime,data,status,descriptor FROM attachments WHERE id=?',(identity,)).fetchone()
    if row is None:raise ProtocolError('MAIL_NOT_FOUND','quarantined attachment unavailable')
    if row[3]=='imported':return json.loads(row[4])
    name,mime,data,_,_=row
    config=channel.config.get('inbound_content')
    if not config:raise ProtocolError('MAIL_UNAVAILABLE','private Content Fabric import target is not configured')
    scan(data,channel.exporter.config.get('scanner'))
    from .content_fabric import Fabric,CHUNK_BYTES
    fabric=Fabric(config['root'])
    try:
        owner=config['owner'];digest='sha256:'+hashlib.sha256(data).hexdigest();upload='mail-'+identity[:48]
        fabric.begin(owner,upload,len(data),digest,mime)
        for position,start in enumerate(range(0,len(data),CHUNK_BYTES)):fabric.put(owner,upload,position,data[start:start+CHUNK_BYTES])
        obj=fabric.finish(owner,upload)
        descriptor={'id':obj['id'],'name':name,'mime':mime,'size':len(data),'digest':digest}
    finally:fabric.close()
    with closing(sqlite3.connect(channel.db)) as db,db:db.execute("UPDATE attachments SET status='imported',descriptor=? WHERE id=?",(json.dumps(descriptor),identity))
    return descriptor

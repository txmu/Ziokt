"""Bounded NNTP reader/posting adapter (RFC 3977 subset).

Server transfer requires an explicit netnews:feed grant and feed_groups list.
Original article bytes and headers are retained as provenance; an authenticated
upstream is never reported as an independently verified publisher signature. AUTHINFO USER/PASS requires TLS
except for explicit loopback development. Anonymous access is public read only.
"""
from datetime import datetime, timezone
import hashlib
from .netnews_mime import content_parts,wire_with_attachments,stream_article
from email.parser import BytesParser
from email import policy
from email.header import Header
from email.utils import parsedate_to_datetime,parseaddr
import fnmatch
import hmac
import socketserver
import ssl
import threading
import tempfile

from .content_fabric import MESSAGE


class BoundedTCP(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True
    def __init__(self,*args,**kwargs):
        self.slots=threading.BoundedSemaphore(16)
        super().__init__(*args,**kwargs)
    def process_request(self,request,client_address):
        if not self.slots.acquire(False):self.shutdown_request(request);return
        try:super().process_request(request,client_address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,client_address):
        try:super().process_request_thread(request,client_address)
        finally:self.slots.release()


def article_headers(article):
    return [('From',article['from']),('Date',article['date']),('Newsgroups',','.join(article['newsgroups'])),('Subject',str(Header(article['subject'],'utf-8'))),('Message-ID',article['message_id']),('References',' '.join(article.get('references',[]))),('Path','!'.join(article.get('path',[]))+'!not-for-mail'),('MIME-Version','1.0'),('Content-Type','text/plain; charset=utf-8'),('Content-Transfer-Encoding','8bit')]


def wire_article(article,fabric=None,owner=None,base_url=None,inline_limit=32768):
    attached=wire_with_attachments(article,article_headers(article),fabric,owner,base_url,inline_limit)
    if attached is not None:return attached
    return '\r\n'.join(k+': '+v for k,v in article_headers(article))+'\r\n\r\n'+article['body'].replace('\r\n','\n').replace('\n','\r\n')


def server(fabric,config,tokens):
    wire_limit=config.get('max_article_bytes',12*1024*1024)
    decoded_limit=config.get('max_decoded_attachment_bytes',8*1024*1024)
    if type(wire_limit) is not int or not 49152<=wire_limit<=32*1024*1024 or type(decoded_limit) is not int or not 32768<=decoded_limit<=16*1024*1024:raise ValueError('NNTP receive budgets')
    if not hasattr(fabric,'nntp_receive_slots'):fabric.nntp_receive_slots=threading.BoundedSemaphore(1)
    class Handler(socketserver.StreamRequestHandler):
        def setup(self):
            super().setup();self.connection.settimeout(60)
            self.owner='@anonymous';self.authenticated=False;self.scopes=set();self.senders=[];self.group=None;self.current=None;self.user=None
        def line(self,value):self.wfile.write(value.encode('utf-8')+b'\r\n');self.wfile.flush()
        def block(self,code,lines):
            self.line(code)
            pending=bytearray()
            for line in lines:
                if line.startswith('.'):line='.'+line
                pending.extend(line.encode('utf-8')+b'\r\n')
                if len(pending)>=65536:self.wfile.write(pending);pending.clear()
            pending.extend(b'.\r\n');self.wfile.write(pending)
        def rows(self,low=1,limit=1000):return fabric.articles(self.owner,self.group,low,min(limit,fabric.optimizations.get(self.owner,'netnews')['effective']['nntp_max_range']))['items']
        def selected(self):
            if not self.group:self.line('412 No newsgroup selected');return False
            return True
        def readable(self):
            if not self.authenticated and not config.get('anonymous_read',False):self.line('480 Authentication required');return False
            if self.authenticated and 'netnews:read' not in self.scopes:self.line('502 Read access denied');return False
            return True
        def select_article(self,arg):
            if arg and arg.startswith('<'):
                with fabric.lock:article=fabric._get(self.owner,arg,'article')
                if article['message_id']!=arg:raise ValueError('ID')
                number=0
                if self.group:
                    with fabric.lock:row=fabric.db.execute('SELECT number FROM group_articles WHERE name=? AND message=?',(self.group,arg)).fetchone()
                    if row:number=row[0]
                return number,article
            if not self.selected():return None
            number=int(arg) if arg else self.current
            if not number:self.line('420 No current article');return None
            rows=self.rows(number,1)
            if not rows or rows[0]['number']!=number:self.line('423 No article with that number');return None
            self.current=number
            return number,rows[0]
        def receive_post(self,feed=False,expected_id=None):
            # Spool the wire representation and serialize MIME parsing across listeners.
            # The stdlib MIME parser still allocates memory, bounded by wire_limit.
            if not fabric.nntp_receive_slots.acquire(False):raise ValueError('NNTP ingest busy; retry')
            try:
                with tempfile.TemporaryFile(dir=fabric.root) as spool:return self.receive_spooled(spool,feed,expected_id)
            finally:fabric.nntp_receive_slots.release()
        def receive_spooled(self,spool,feed,expected_id):
            size=0;digest=hashlib.sha256(self.owner.encode())
            while True:
                raw=self.rfile.readline(1001)
                if not raw or len(raw)>1000 or not raw.endswith(b'\r\n'):raise ValueError('article line limit')
                if raw==b'.\r\n':break
                if raw.startswith(b'..'):raw=raw[1:]
                size+=len(raw)
                if size>wire_limit:raise ValueError('configured article limit')
                spool.write(raw);digest.update(raw)
            spool.seek(0);message=BytesParser(policy=policy.default).parse(spool)
            if message.defects:raise ValueError('MIME defects')
            for key in ('From','Subject','Newsgroups','Message-ID','Date','References'):
                if len(message.get_all(key,[]))>1:raise ValueError('duplicate header')
            if not all(message.get(k) for k in ('From','Subject','Newsgroups')):raise ValueError('missing headers')
            sender=str(message['From'])
            if not feed and sender!=self.owner and parseaddr(sender)[1] not in self.senders:raise PermissionError('From identity mismatch')
            mid=str(message['Message-ID']) if message.get('Message-ID') else None
            if expected_id is not None and mid!=expected_id:raise ValueError('feed Message-ID mismatch')
            names=str(message['Newsgroups']).split(',')
            body,parts=content_parts(message,decoded_limit)
            from .content_fabric import text,header,GROUP
            text(body,8192,empty=True);header(str(message['Subject']))
            references=str(message.get('References','')).split()
            if mid is not None and not MESSAGE.fullmatch(mid):raise ValueError('Message-ID')
            if len(references)>32 or any(not MESSAGE.fullmatch(ref) for ref in references):raise ValueError('References')
            if not 1<=len(names)<=8 or len(set(names))!=len(names) or any(not GROUP.fullmatch(name) for name in names):raise ValueError('Newsgroups')
            with fabric.lock:
                for name in names:
                    target=fabric.db.execute('SELECT * FROM groups WHERE name=?',(name,)).fetchone()
                    if not target or (target['owner']!=self.owner and (target['posting']=='owner' or target['visibility']=='private')):raise PermissionError('posting target denied')
            native=None
            if feed:
                if size>16000 or any(name not in config.get('feed_groups',[]) for name in names):raise PermissionError('bounded feed policy')
                if not message.get('Date') or not message.get('Path'):raise ValueError('feed requires Date and Path')
                if parsedate_to_datetime(str(message['Date'])).tzinfo is None:raise ValueError('article Date timezone')
                native={key:str(message[key]) for key in ('From','Date','Path','Organization') if message.get(key)}
                for value in native.values():header(value)
                if fabric.public in native['Path'].split('!'):raise ValueError('NNTP propagation loop')
            for name,_,_ in parts:fabric._attachment_name(name)
            attachments=[];staged=[]
            try:
                for index,(name,mime,payload) in enumerate(parts):
                    upload_digest=digest.copy();upload_digest.update(str(index).encode());upload='mime-'+upload_digest.hexdigest()[:48]
                    with fabric.lock:existing=fabric.db.execute('SELECT 1 FROM uploads WHERE id=?',(upload,)).fetchone()
                    if not existing:staged.append(upload)
                    fabric.begin(self.owner,upload,len(payload),'sha256:'+hashlib.sha256(payload).hexdigest(),mime,name)
                    if fabric.upload_status(self.owner,upload)['state']!='complete':
                        for position,start in enumerate(range(0,len(payload),16384)):fabric.put(self.owner,upload,position,payload[start:start+16384])
                    obj=fabric.finish(self.owner,upload);attachments.append({'id':obj['id'],'name':name})
                spool.seek(0)
                return fabric.post(self.owner,names,str(message['Subject']),body,message_id=mid,references=references,native_headers=native,raw_article=spool.read(16001) if feed else None,attachments=attachments,sender=sender if not feed else None)
            except Exception as error:
                cleanup_errors=[]
                for upload in reversed(staged):
                    try:fabric.discard_staged_upload(self.owner,upload)
                    except Exception as cleanup:cleanup_errors.append(type(cleanup).__name__)
                if cleanup_errors:raise ValueError('post rejected; staged cleanup requires recovery: '+','.join(cleanup_errors)) from error
                raise
        def handle(self):
            self.line('201 Ziokt Netnews reader ready; authenticate to post')
            for _ in range(1000):
                try:
                    raw=self.rfile.readline(513)
                    if not raw:return
                    if len(raw)>512 or not raw.endswith(b'\r\n'):self.line('500 Command line rejected');return
                    parts=raw[:-2].decode('ascii').split(' ',1);cmd=parts[0].upper();arg=parts[1].strip() if len(parts)>1 else ''
                    cmd={'XOVER':'OVER','XHDR':'HDR'}.get(cmd,cmd)
                    if cmd=='QUIT':self.line('205 Closing connection');return
                    if cmd=='CAPABILITIES':
                        caps=['VERSION 2','READER','LIST ACTIVE NEWSGROUPS OVERVIEW.FMT','OVER','HDR','IMPLEMENTATION Ziokt-Content-v1']
                        if config.get('tls') or config.get('allow_loopback_auth',False):caps+=['AUTHINFO USER']
                        if self.authenticated and 'netnews:write' in self.scopes:caps+=['POST']
                        if self.authenticated and 'netnews:feed' in self.scopes:caps+=['IHAVE','STREAMING']
                        self.block('101 Capability list follows',caps);continue
                    if cmd=='MODE' and arg.upper()=='READER':self.line('200 Posting allowed' if self.authenticated and 'netnews:write' in self.scopes else '201 Reader mode');continue
                    if cmd=='DATE':self.line('111 '+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S'));continue
                    if cmd=='HELP':self.block('100 Help follows',['CAPABILITIES AUTHINFO MODE READER LIST GROUP ARTICLE HEAD BODY STAT NEXT LAST OVER HDR POST DATE HELP QUIT']);continue
                    if cmd=='AUTHINFO':
                        mode,_,value=arg.partition(' ')
                        if not config.get('tls') and not config.get('allow_loopback_auth',False):self.line('483 TLS required');continue
                        if mode.upper()=='USER':self.user=value;self.line('381 Password required');continue
                        if mode.upper()=='PASS' and self.user:
                            found=next((t for t in tokens if t['account']==self.user and hmac.compare_digest(value,t['token'])),None)
                            if found:self.owner=found['account'];self.authenticated=True;self.scopes=set(found['scopes']);self.senders=found.get('senders',[]);self.group=None;self.current=None;self.line('281 Authentication accepted')
                            else:self.line('481 Authentication rejected');return
                            continue
                        self.line('501 AUTHINFO syntax');continue
                    if cmd=='MODE' and arg.upper()=='STREAM':
                        if not self.authenticated:self.line('480 Authentication required');continue
                        if 'netnews:feed' not in self.scopes:self.line('502 Feed permission required');continue
                        self.line('203 Streaming permitted');continue
                    if cmd in {'IHAVE','CHECK','TAKETHIS'}:
                        if not self.authenticated or 'netnews:feed' not in self.scopes:
                            self.line('502 Feed permission required')
                            if cmd=='TAKETHIS':return
                            continue
                        if not MESSAGE.fullmatch(arg):self.line('501 Message-ID required');continue
                        with fabric.lock:known=fabric.db.execute('SELECT 1 FROM records WHERE id=?',(arg,)).fetchone() is not None
                        if cmd=='CHECK':self.line(('438 ' if known else '238 ')+arg);continue
                        if cmd=='IHAVE' and known:self.line('435 Article already known');continue
                        if cmd=='IHAVE':self.line('335 Send article')
                        try:
                            self.receive_post(feed=True,expected_id=arg)
                            self.line(('239 '+arg) if cmd=='TAKETHIS' else '235 Article durably received')
                        except (ValueError,PermissionError):
                            self.line(('439 '+arg+' rejected') if cmd=='TAKETHIS' else '437 Article rejected')
                            return
                        continue
                    if cmd=='MODE':self.line('501 Unsupported mode');continue
                    if cmd=='POST':
                        if not self.authenticated:self.line('480 Authentication required');continue
                        if 'netnews:write' not in self.scopes:self.line('440 Posting prohibited');continue
                        self.line('340 Send article; end with a single dot')
                        try:self.receive_post();self.line('240 Article received and durably stored')
                        except (ValueError,PermissionError):self.line('441 Posting failed');return
                        continue
                    if not self.readable():continue
                    if cmd=='LIST':
                        keyword,_,pattern=arg.partition(' ');keyword=(keyword or 'ACTIVE').upper()
                        if keyword=='OVERVIEW.FMT':self.block('215 Overview format',['Subject:','From:','Date:','Message-ID:','References:',':bytes',':lines']);continue
                        if keyword not in {'ACTIVE','NEWSGROUPS'}:self.line('501 Unsupported LIST keyword');continue
                        lines=[]
                        for group in fabric.groups(self.owner)['items']:
                            if pattern and not fnmatch.fnmatchcase(group['name'],pattern):continue
                            name=group['name'];stats=fabric.article_numbers(self.owner,name)
                            low=stats['low'];high=stats['high']
                            lines.append(name+' '+group['description'] if keyword=='NEWSGROUPS' else f'{name} {high} {low} '+('n' if group['posting']=='owner' else 'y'))
                        self.block('215 Information follows',lines);continue
                    if cmd in {'GROUP','LISTGROUP'}:
                        arguments=arg.split()
                        if len(arguments)>(2 if cmd=='LISTGROUP' else 1):raise ValueError('group syntax')
                        name=arguments[0] if arguments else self.group
                        if not name:self.line('412 No newsgroup selected');continue
                        try:
                            stats=fabric.article_numbers(self.owner,name)
                        except PermissionError:self.line('411 No such newsgroup');continue
                        self.group=name;self.current=stats['low'] if stats['count'] else None
                        response=f"211 {stats['count']} {stats['low']} {stats['high']} {name}"
                        if cmd=='GROUP':self.line(response);continue
                        low,high=1,2**63-1
                        if len(arguments)==2:
                            start,sep,end=arguments[1].partition('-');low=int(start);high=int(end) if end else (2**63-1 if sep else low)
                        def numbers():
                            cursor=low
                            while cursor<=high:
                                batch=fabric.article_numbers(self.owner,name,cursor,high,limit=256)
                                if not batch:break
                                for item in batch:yield str(item['number'])
                                cursor=batch[-1]['number']+1
                        self.block(response,numbers());continue
                    if cmd in {'NEXT','LAST'}:
                        if not self.selected():continue
                        if self.current is None:self.line('420 No current article');continue
                        eligible=fabric.article_numbers(self.owner,self.group,self.current+1,limit=1) if cmd=='NEXT' else fabric.article_numbers(self.owner,self.group,1,self.current-1,previous=True,limit=1) if self.current>1 else []
                        if not eligible:self.line('421 No next article' if cmd=='NEXT' else '422 No previous article');continue
                        row=eligible[0];self.current=row['number'];self.line(f"223 {self.current} {row['message']}");continue
                    if cmd in {'ARTICLE','HEAD','BODY','STAT'}:
                        try:result=self.select_article(arg)
                        except PermissionError:self.line('430 No article with that message-id');continue
                        if result is None:continue
                        number,article=result;code={'ARTICLE':220,'HEAD':221,'BODY':222,'STAT':223}[cmd]
                        if cmd=='STAT':self.line(f'{code} {number} {article["message_id"]}');continue
                        heads,body=stream_article(article,article_headers(article),fabric,self.owner,config.get('attachment_base_url'),config.get('max_attachment_transfer_bytes'))
                        from itertools import chain
                        lines=chain(heads,[''],body) if cmd=='ARTICLE' else heads if cmd=='HEAD' else body
                        try:self.block(f'{code} {number} {article["message_id"]}',lines)
                        except (OSError,ValueError,PermissionError):return
                        continue
                    if cmd in {'OVER','HDR'}:
                        if not self.selected():continue
                        field=None
                        if cmd=='HDR':field,_,arg=arg.partition(' ')
                        if not arg:arg=str(self.current or 0)
                        start,sep,end=arg.partition('-');low=int(start);high=int(end) if end else (2**31 if sep else low)
                        items=[r for r in self.rows(low) if r['number']<=high]
                        if not items:self.line('423 Empty range');continue
                        lines=[]
                        for article in items:
                            if field:
                                headers={k.lower():v for k,v in article_headers(article)}
                                lines.append(str(article['number'])+' '+headers.get(field.lower(),''))
                            else:
                                values=[article['subject'],article['from'],article['date'],article['message_id'],' '.join(article.get('references',[])),str(len(wire_article(article).encode())),str(len(article['body'].splitlines()))]
                                lines.append(str(article['number'])+'\t'+'\t'.join(v.replace('\t',' ') for v in values))
                        self.block('225 Headers follow' if field else '224 Overview follows',lines);continue
                    self.line('500 Command not supported')
                except (OSError,UnicodeError):return
                except (ValueError,KeyError,TypeError):self.line('501 Invalid syntax')
                except PermissionError:self.line('502 Permission denied')
    address=config.get('listen','127.0.0.1')
    if address not in {'127.0.0.1','::1','localhost'} and not config.get('tls'):raise ValueError('NNTP public listener requires TLS')
    result=BoundedTCP((address,config.get('port',8119)),Handler)
    if config.get('tls'):
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(config['tls']['cert'],config['tls']['key'])
        result.socket=context.wrap_socket(result.socket,server_side=True)
    return result

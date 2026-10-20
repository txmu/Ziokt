"""Bounded NNTP MIME compatibility; native objects remain separately addressed."""
import hashlib
from email import policy
from email.message import EmailMessage

MAX_INLINE=32768


def content_parts(message,max_decoded_bytes=MAX_INLINE):
    """Decode a plain body and up to eight inert attachment byte strings."""
    if not message.is_multipart():
        if message.get_content_type()!='text/plain':raise ValueError('plain body required')
        body=message.get_content()
        if message.defects:raise ValueError('MIME defects')
        return body,[]
    if message.get_content_type()!='multipart/mixed':raise ValueError('multipart/mixed required')
    parts=list(message.iter_parts())
    if not 1<=len(parts)<=9:raise ValueError('MIME part count')
    body=None;attachments=[];total=0
    for part in parts:
        if part.is_multipart() or len(part.get_all('Content-Type',[]))>1 or len(part.get_all('Content-Transfer-Encoding',[]))>1:raise ValueError('nested or ambiguous MIME')
        if part.get_content_disposition()=='attachment':
            name=part.get_filename();data=part.get_payload(decode=True)
            if not name or not isinstance(data,bytes):raise ValueError('attachment filename/payload')
            total+=len(data)
            if total>max_decoded_bytes:raise ValueError('configured MIME attachment budget exceeded')
            attachments.append((name,part.get_content_type(),data))
        elif body is None and part.get_content_type()=='text/plain':body=part.get_content()
        else:raise ValueError('one plain body and explicit attachments required')
        if part.defects:raise ValueError('MIME decoding defects')
    if message.defects or body is None:raise ValueError('MIME body/defects')
    return body,attachments


def wire_with_attachments(article,headers,fabric,owner,base_url=None,inline_limit=MAX_INLINE):
    attachments=article.get('attachments',[])
    if not attachments:return None
    inline_limit=max(0,min(MAX_INLINE,inline_limit));parts=[];unavailable=False
    if fabric is not None and sum(item['size'] for item in attachments)<=inline_limit:
        for item in attachments:
            try:
                data=b''.join(fabric.read_chunk(owner,item['id'],pos) for pos in range((item['size']+16383)//16384))
                if len(data)!=item['size'] or 'sha256:'+hashlib.sha256(data).hexdigest()!=item['digest']:raise ValueError('attachment digest mismatch')
                parts.append((item,data))
            except (ValueError,PermissionError,OSError):unavailable=True;break
    else:unavailable=True
    if not unavailable:
        message=EmailMessage(policy=policy.SMTP)
        for key,value in headers:
            if key not in {'MIME-Version','Content-Type','Content-Transfer-Encoding'}:message[key]=value
        message.set_content(article['body'])
        # Stable boundary makes ARTICLE/HEAD/BODY deterministic for this immutable ID.
        for item,data in parts:
            mime=item['mime'].split(';',1)[0]
            major,sep,minor=mime.partition('/')
            if not sep:major,minor='application','octet-stream'
            message.add_attachment(data,maintype=major,subtype=minor,filename=item['name'])
        message.set_boundary('ziokt-'+hashlib.sha256(article['message_id'].encode()).hexdigest()[:40])
        return message.as_bytes().decode('ascii')
    # Legacy clients see usable HTTPS references, never a proprietary object hash
    # masquerading as attachment bytes. No large file is fetched just to read a post.
    lines=[article['body'],'','Ziokt attachment references (not embedded):']
    for item in attachments:
        lines.append(f"{item['name']} ({item['size']} bytes, {item['digest']})")
        lines.append(base_url.rstrip('/')+'/objects/'+item['id'] if base_url else 'Object: '+item['id'])
    lines.append('Retrieve through an authorized Ziokt node if this server has not cached the object.')
    return '\r\n'.join(key+': '+value for key,value in headers)+'\r\n\r\n'+'\r\n'.join('\n'.join(lines).replace('\r\n','\n').split('\n'))


def stream_article(article,headers,fabric,owner,base_url=None,max_attachment_bytes=None):
    """Prepare headers, then yield MIME body lines with O(chunk-size) byte buffers."""
    import base64,json
    attachments=article.get('attachments',[]);budget=fabric.max_object if max_attachment_bytes is None else max_attachment_bytes
    if type(budget) is not int or not 0<=budget<=fabric.max_object:raise ValueError('NNTP attachment transfer budget')
    available=bool(attachments) and sum(item['size'] for item in attachments)<=budget
    if available:
        for item in attachments:
            try:
                with fabric.lock:actual=json.loads(fabric.object_info(owner,item['id'])['metadata'])
                if any(actual[key]!=item[key] for key in ('size','digest','mime','merkle_root')):available=False;break
            except (PermissionError,ValueError,KeyError):available=False;break
    if not available:
        text=wire_with_attachments(article,headers,None,owner,base_url,0) if attachments else '\r\n'.join(k+': '+v for k,v in headers)+'\r\n\r\n'+article['body'].replace('\r\n','\n').replace('\n','\r\n')
        head,_,body=text.partition('\r\n\r\n');return head.split('\r\n'),iter(body.split('\r\n'))
    boundary='ziokt-'+hashlib.sha256(article['message_id'].encode()).hexdigest()[:40]
    container=EmailMessage(policy=policy.SMTP)
    for key,value in headers:
        if key not in {'MIME-Version','Content-Type','Content-Transfer-Encoding'}:container[key]=value
    container.set_type('multipart/mixed');container.set_boundary(boundary)
    head=container.as_bytes().split(b'\r\n\r\n',1)[0].decode('ascii').split('\r\n')
    def body_lines():
        yield '--'+boundary
        text=EmailMessage(policy=policy.SMTP);text.set_content(article['body'],cte='quoted-printable')
        yield from text.as_bytes().decode('ascii').rstrip('\r\n').split('\r\n')
        for item in attachments:
            yield '--'+boundary
            part=EmailMessage(policy=policy.SMTP);part.set_type(item['mime'].split(';',1)[0]);part['Content-Transfer-Encoding']='base64';part.add_header('Content-Disposition','attachment',filename=item['name'])
            yield from part.as_bytes().split(b'\r\n\r\n',1)[0].decode('ascii').split('\r\n');yield ''
            pending=b'';digest=hashlib.sha256();size=0
            for position in range((item['size']+16383)//16384):
                chunk=fabric.read_chunk(owner,item['id'],position);digest.update(chunk);size+=len(chunk);pending+=chunk;end=len(pending)//57*57
                for start in range(0,end,57):yield base64.b64encode(pending[start:start+57]).decode('ascii')
                pending=pending[end:]
            if pending:yield base64.b64encode(pending).decode('ascii')
            if size!=item['size'] or 'sha256:'+digest.hexdigest()!=item['digest']:raise ValueError('streamed attachment integrity failure')
        yield '--'+boundary+'--'
    return head,body_lines()

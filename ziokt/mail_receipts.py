"""Opt-in MDN requests and explicit per-message permission to send read receipts."""
from contextlib import closing
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
import hashlib
import sqlite3
from .protocol import ProtocolError


def preference(channel,value=None):
    if value is not None and value not in {'deny','manual'}:raise ProtocolError('INVALID_REQUEST','read receipts: deny or manual')
    with closing(sqlite3.connect(channel.db)) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS receipt_policy(id INTEGER PRIMARY KEY CHECK(id=1),policy TEXT)')
        if value is not None:db.execute('INSERT OR REPLACE INTO receipt_policy VALUES(1,?)',(value,))
        row=db.execute('SELECT policy FROM receipt_policy WHERE id=1').fetchone()
    return {'policy':row[0] if row else channel.config.get('read_receipts','deny'),'automatic_replies':False,'remote_images_loaded':False}


def respond(channel,sender_key,native_address,inbox_id,decision):
    if decision not in {'send','block'}:raise ProtocolError('INVALID_REQUEST','explicit send or block required')
    import re
    if not isinstance(inbox_id,str) or not re.fullmatch('[0-9]{1,10}:[0-9]{1,10}',inbox_id):raise ProtocolError('INVALID_REQUEST','account-local IMAP message id required')
    validity,uid=inbox_id.split(':')
    with closing(sqlite3.connect(channel.db)) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS read_receipts(inbox_id TEXT PRIMARY KEY,status TEXT,message_id TEXT)')
        row=db.execute('SELECT raw,received_at FROM inbox WHERE validity=? AND uid=?',(validity,int(uid))).fetchone()
        if row is None:raise ProtocolError('MAIL_NOT_FOUND','inbox message unavailable')
        old=db.execute('SELECT status,message_id FROM read_receipts WHERE inbox_id=?',(inbox_id,)).fetchone()
        if old:return {'status':old[0],'message_id':old[1]}
        if decision=='block':
            db.execute("INSERT INTO read_receipts VALUES(?,'blocked',NULL)",(inbox_id,));return {'status':'blocked','sent':False}
    if preference(channel)['policy']!='manual':raise ProtocolError('POLICY_DENIED','account blocks reading receipts')
    message=BytesParser(policy=policy.default).parsebytes(row[0])
    from .mail_internet import address
    from .mail_receive import thread_id
    sender=address(parseaddr(str(message.get('From','')))[1])
    notification=message.get_all('Disposition-Notification-To',[])
    if len(notification)!=1 or address(parseaddr(str(notification[0]))[1])!=sender:raise ProtocolError('POLICY_DENIED','receipt must return to the original sender, with an explicit MDN request')
    original=thread_id(str(message.get('Message-ID','')))
    digest=hashlib.sha256(('mdn\0'+inbox_id).encode()).hexdigest()
    with closing(sqlite3.connect(channel.db)) as db,db:
        claim=db.execute("INSERT OR IGNORE INTO read_receipts VALUES(?,'pending',NULL)",(inbox_id,))
        if claim.rowcount!=1:
            existing=db.execute('SELECT status,message_id FROM read_receipts WHERE inbox_id=?',(inbox_id,)).fetchone()
            return {'status':existing[0],'message_id':existing[1]}
    try:
        result=channel.send(sender_key,sender,'Read receipt','The recipient explicitly chose to report this message as displayed.',timestamp=row[1],message_id=digest,native_address=native_address,in_reply_to=original,references=[original],receipt_for=original)
    except BaseException:
        with closing(sqlite3.connect(channel.db)) as db,db:db.execute("DELETE FROM read_receipts WHERE inbox_id=? AND status='pending'",(inbox_id,))
        raise
    with closing(sqlite3.connect(channel.db)) as db,db:db.execute("UPDATE read_receipts SET status='queued',message_id=? WHERE inbox_id=?",(result['message_id'],inbox_id))
    return {'status':'queued','message_id':result['message_id'],'automatic':False}

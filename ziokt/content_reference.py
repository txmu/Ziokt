"""Versioned, signature-bound references shared by native content applications.

A reference conveys identity/integrity metadata, never read or execution rights.
"""
import hashlib
import json
import re
import time
from .content_fabric import EVENT_DOMAIN
from .protocol import ProtocolError,encoded
from .security import verify

SCHEMA='ziokt.content-reference.v1'
HEX=re.compile(r'[0-9a-f]{64}\Z')
DIGEST=re.compile(r'sha256:[0-9a-f]{64}\Z')


def from_event(envelope):
    if not isinstance(envelope,dict) or not isinstance(envelope.get('public_key'),str) or not HEX.fullmatch(envelope['public_key']):raise ProtocolError('CONTENT_REFERENCE','Signed origin identity required')
    value=verify(envelope,envelope['public_key'],EVENT_DOMAIN)
    if not isinstance(value,dict) or value.get('v')!=1 or value.get('kind') not in {'book','article'} or value.get('visibility')!='public' or value.get('deleted') is not False or type(value.get('expires')) is not int or value['expires']<0 or value['expires'] and value['expires']<=int(time.time()):raise ProtocolError('CONTENT_REFERENCE','Live explicitly public content event required')
    body=value.get('body');record=value.get('record')
    if not isinstance(body,dict) or not isinstance(record,str) or not 1<=len(record)<=300:raise ProtocolError('CONTENT_REFERENCE','Content record identity required')
    objects=[]
    if value['kind']=='book':
        entries=[{'id':body.get('file_id'),'role':'book','name':'','metadata':body.get('file')}]
        version=body.get('edition_id')
        if not isinstance(version,str) or not 1<=len(version.encode())<=2048:raise ProtocolError('CONTENT_REFERENCE','Pinned book edition required')
    else:
        if body.get('message_id')!=record:raise ProtocolError('CONTENT_REFERENCE','Article Message-ID mismatch')
        attachments=body.get('attachments',[])
        if not isinstance(attachments,list) or len(attachments)>8 or any(not isinstance(entry,dict) for entry in attachments):raise ProtocolError('CONTENT_REFERENCE','Bounded native attachment list required')
        entries=[{'id':entry.get('id'),'role':'attachment','name':entry.get('name'),'metadata':entry} for entry in attachments]
        version='sha256:'+hashlib.sha256(encoded(envelope)).hexdigest()
    for entry in entries:
        if not isinstance(entry['name'],str) or len(entry['name'].encode())>255 or '\x00' in entry['name']:raise ProtocolError('CONTENT_REFERENCE','Bounded object display name required')
        meta=entry['metadata']
        if not isinstance(entry['id'],str) or not re.fullmatch(r'cf1-[0-9a-f]{64}',entry['id']) or not isinstance(meta,dict):raise ProtocolError('CONTENT_REFERENCE','Native content object identity required')
        if type(meta.get('size')) is not int or not 0<=meta['size']<=512*1024*1024 or not isinstance(meta.get('digest'),str) or not DIGEST.fullmatch(meta['digest']) or not isinstance(meta.get('merkle_root'),str) or not HEX.fullmatch(meta['merkle_root']) or not isinstance(meta.get('mime'),str) or not 1<=len(meta['mime'])<=256:raise ProtocolError('CONTENT_REFERENCE','Bounded verified-format object metadata required')
        objects.append({'id':entry['id'],'role':entry['role'],'name':entry['name'],**{key:meta[key] for key in ('size','digest','merkle_root','mime')}})
    if len(objects)>8:raise ProtocolError('CONTENT_REFERENCE','Content object count limit')
    return {'schema':SCHEMA,'component':'content-fabric','origin':envelope['public_key'],'kind':value['kind'],'record':record,'event':'sha256:'+hashlib.sha256(encoded(envelope)).hexdigest(),'version':version,'objects':objects}


def verify_reference(reference,envelope):
    expected=from_event(envelope)
    if not isinstance(reference,dict) or reference!=expected:raise ProtocolError('CONTENT_REFERENCE_MISMATCH','Reference differs from its signed source version')
    return expected


def create(fabric,owner,record,*,verify_bytes=False):
    if type(verify_bytes) is not bool:raise ValueError('verification flag')
    with fabric.lock:
        fabric._get(owner,record)
        row=fabric.db.execute('SELECT * FROM records WHERE id=?',(record,)).fetchone()
        if row['visibility']!='public':raise PermissionError('private content cannot be converted to a public reference')
        if fabric.db.execute('SELECT 1 FROM local_content_policies WHERE record=? AND distribution_stopped=1',(record,)).fetchone():raise PermissionError('local content distribution stopped')
        source=fabric.db.execute('SELECT envelope FROM events WHERE id=?',(row['event'],)).fetchone()
        if not source:raise ProtocolError('CONTENT_SOURCE_EVENT','Original signed source event unavailable')
        envelope=json.loads(source['envelope']);reference=from_event(envelope)
        value=envelope['payload']
        if value['record']!=record or envelope['public_key']!=row['origin'] or encoded(value['body'])!=bytes(row['body']):raise ProtocolError('CONTENT_SOURCE_CHANGED','Stored projection differs from its signed origin')
        for entry in reference['objects']:
            obj=fabric.object_info('@anonymous',entry['id'])
            metadata=json.loads(obj['metadata'])
            if any(metadata.get(key)!=entry[key] for key in ('size','digest','merkle_root','mime')):raise ProtocolError('CONTENT_OBJECT_MISMATCH','Local object differs from signed source reference')
            if verify_bytes:fabric.verify_object('@anonymous',entry['id'])
        return {'reference':reference,'source_event':envelope,'content_bytes_verified':verify_bytes,'permission_granted_by_reference':False}


def resolve(fabric,owner,reference,*,verify_bytes=False):
    if not isinstance(reference,dict) or reference.get('schema')!=SCHEMA or reference.get('component')!='content-fabric':raise ProtocolError('CONTENT_REFERENCE','Versioned native content reference required')
    current=create(fabric,owner,reference.get('record'),verify_bytes=verify_bytes)
    if current['reference']!=reference:raise ProtocolError('CONTENT_VERSION_CHANGED','Requested version was withdrawn, replaced, conflicted or changed; reference never follows latest silently')
    return {'state':'available',**current}

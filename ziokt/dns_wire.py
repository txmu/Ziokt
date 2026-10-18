"""Bounded authoritative DNS projection; never invokes a system/public resolver."""
import ipaddress
import struct
import sqlite3
from .protocol import ProtocolError

TYPES = {1:'A',28:'AAAA',16:'TXT',65:'HTTPS'}


def wire_name(name):
    return b''.join(bytes([len(label)])+label.encode('ascii') for label in name.removesuffix('.').split('.'))+b'\0'


def read_question(packet):
    if not isinstance(packet,bytes) or not 12 <= len(packet) <= 4096:
        raise ValueError('bounded DNS packet required')
    ident,flags,qd,an,ns,ar=struct.unpack('!6H',packet[:12])
    if flags & 0xf800 or qd!=1 or an or ns or ar>1:
        raise ValueError('single ordinary query required')
    labels=[];offset=12
    while True:
        if offset>=len(packet):raise ValueError('truncated name')
        size=packet[offset];offset+=1
        # Compressed question names are unnecessary and reject pointer loops.
        if size>63 or offset+size>len(packet):raise ValueError('invalid name')
        if not size:break
        labels.append(packet[offset:offset+size].decode('ascii'));offset+=size
        if len(labels)>10:raise ValueError('name too deep')
    if offset+4>len(packet):raise ValueError('truncated question')
    kind,cls=struct.unpack('!HH',packet[offset:offset+4]);end=offset+4
    if cls!=1:raise ValueError('IN class required')
    budget=512
    if ar:
        if len(packet)<end+11 or packet[end]!=0:raise ValueError('invalid OPT')
        typ,udp,ttl,size=struct.unpack('!HHIH',packet[end+1:end+11])
        if typ!=41 or len(packet)!=end+11+size or ttl>>24:raise ValueError('invalid EDNS')
        budget=min(1232,max(512,udp))
    elif len(packet)!=end:raise ValueError('trailing data')
    return ident,flags,'.'.join(labels),kind,packet[12:end],budget


def rdata(kind,value):
    if kind in ('A','AAAA'):return ipaddress.ip_address(value).packed
    if kind=='TXT':
        text=value.encode('ascii');return bytes([len(text)])+text
    if kind=='HTTPS':
        # SvcParamKeys in ascending order: alpn=1, port=3, ech=5.
        alpn=b''.join(bytes([len(x)])+x.encode('ascii') for x in value['alpn'])
        import base64
        params=[(1,alpn),(3,struct.pack('!H',value['port']))]
        ech=base64.b64decode(value['ech'],validate=True)
        if ech:params.append((5,ech))
        target=b'\0' if value['target']=='.' else wire_name(value['target'])
        return struct.pack('!H',value['priority'])+target+b''.join(struct.pack('!HH',key,len(data))+data for key,data in params)
    raise ValueError('unsupported record')


def answer(packet,resolver,*,tcp=False):
    ident=int.from_bytes(packet[:2],'big') if len(packet)>=2 else 0
    try:ident,flags,name,kind,question,budget=read_question(packet)
    except (ValueError,UnicodeError,struct.error):return struct.pack('!6H',ident,0x8001,0,0,0,0)
    code=0;records=[]
    try:
        # Resolve scope even for unsupported/ANY types; do not amplify ANY.
        from .naming import split_name
        split_name(name)
        if kind in TYPES:
            result=resolver.resolve(name)
            import time
            for record in result['records']:
                if record['type']==TYPES[kind]:
                    data=rdata(record['type'],record['value'])
                    ttl=min(record['ttl'],max(0,int(result['expires_at']-time.time())))
                    records.append(b'\xc0\x0c'+struct.pack('!HHIH',kind,1,ttl,len(data))+data)
    except ProtocolError as error:
        code=5 if error.code=='REFUSED' else 3 if error.code=='NAME_NOT_FOUND' else 2
    except (ValueError,TypeError,KeyError,OSError,sqlite3.Error):code=2
    # AA is set only on successful authoritative answers. RD is echoed; RA/AD=0.
    response_flags=0x8000|(flags&0x0100)|(0x0400 if code==0 else 0)|code
    body=question+b''.join(records)
    if not tcp and len(body)+12>budget:
        response_flags|=0x0200;records=[];body=question
    return struct.pack('!6H',ident,response_flags,1,len(records),0,0)+body

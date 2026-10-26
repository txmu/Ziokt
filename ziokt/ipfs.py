"""Bounded CID-verified raw/UnixFS file exchange through standard CARv1.

No daemon, public pin, upload or external gateway is started implicitly.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import secrets
import time

from .protocol import ProtocolError,encoded,secure_read

MAX_FILE=16*1024*1024
MAX_CAR=18*1024*1024
BLOCK_BYTES=262144
BASE58='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def require(condition,message):
    if not condition:raise ProtocolError('IPFS_REJECTED',message)


def varint(value):
    output=bytearray()
    while value>=128:output.append((value&127)|128);value>>=7
    output.append(value);return bytes(output)


def integer(data,offset=0):
    value=0;start=offset
    for index in range(10):
        require(offset<len(data),'truncated varint');byte=data[offset];offset+=1;value|=(byte&127)<<(index*7)
        if byte<128:
            require(data[start:offset]==varint(value) and value<2**64,'canonical uint64 required');return value,offset
    raise ProtocolError('IPFS_REJECTED','excessive varint')


def cid_prefix(data,offset=0):
    start=offset
    if data[offset:offset+2]==b'\x12\x20':codec=0x70;offset+=2
    else:
        version,offset=integer(data,offset);codec,offset=integer(data,offset)
        require(version==1 and codec in {0x55,0x70},'supported CIDv1 raw/UnixFS codec required')
        algorithm,offset=integer(data,offset);size,offset=integer(data,offset)
        require(algorithm==0x12 and size==32,'SHA2-256 multihash required')
    require(offset+32<=len(data),'truncated CID digest')
    return data[start:offset+32],codec,data[offset:offset+32],offset+32


def parse_cid(value):
    require(isinstance(value,str) and 1<=len(value)<=128,'bounded CID required')
    if value.startswith('ipfs://'):value=value[7:]
    try:
        if value.startswith('Qm'):
            number=0
            for character in value:number=number*58+BASE58.index(character)
            data=number.to_bytes((number.bit_length()+7)//8,'big')
            require(len(data)==34 and data[:2]==b'\x12\x20','CIDv0 multihash required')
        else:
            require(value.startswith('b') and value==value.lower(),'CIDv1 lowercase base32 required')
            text=value[1:];data=base64.b32decode(text.upper()+'='*((-len(text))%8))
            require(cid_text(data)==value,'canonical CID encoding required')
        cid,codec,digest,end=cid_prefix(data);require(end==len(data),'CID trailing bytes')
        return cid
    except (ValueError,TypeError):raise ProtocolError('IPFS_REJECTED','invalid CID encoding') from None


def cid_text(value):
    if value[:2]==b'\x12\x20':
        number=int.from_bytes(value,'big');out=''
        while number:number,remainder=divmod(number,58);out=BASE58[remainder]+out
        return out
    return 'b'+base64.b32encode(value).decode().lower().rstrip('=')


def block_cid(data,codec=0x55):return varint(1)+varint(codec)+b'\x12\x20'+hashlib.sha256(data).digest()


def field(number,value):
    return varint(number*8+2)+varint(len(value))+value if isinstance(value,bytes) else varint(number*8)+varint(value)


def protobuf(data):
    fields=[];offset=0
    while offset<len(data):
        require(len(fields)<4096,'protobuf field budget');key,offset=integer(data,offset);number,wire=key>>3,key&7
        require(number>0 and wire in {0,2},'supported protobuf wire type required')
        value,offset=integer(data,offset)
        if wire==2:
            require(offset+value<=len(data),'truncated protobuf field');value,end=data[offset:offset+value],offset+value;offset=end
        fields.append((number,wire,value))
    return fields


def cbor_head(major,value):
    return bytes([major*32+value]) if value<24 else bytes([major*32+24,value]) if value<256 else bytes([major*32+25])+value.to_bytes(2,'big')


def cbor_read(data,offset=0,depth=0):
    require(depth<12 and offset<len(data),'bounded CBOR header required')
    first=data[offset];offset+=1;major,extra=first>>5,first&31
    if extra<24:size=extra
    else:
        width={24:1,25:2,26:4,27:8}.get(extra,0);require(width and offset+width<=len(data),'definite CBOR required')
        size=int.from_bytes(data[offset:offset+width],'big');offset+=width
    require(size<=4096,'CBOR header item budget')
    if major==0:return size,offset
    if major in {2,3}:
        require(offset+size<=len(data),'truncated CBOR value');value=data[offset:offset+size]
        return (value if major==2 else value.decode('utf-8')),offset+size
    if major in {4,5}:
        items=[]
        for _ in range(size*(2 if major==5 else 1)):
            item,offset=cbor_read(data,offset,depth+1);items.append(item)
        if major==4:return items,offset
        require(all(isinstance(key,str) for key in items[::2]) and len(set(items[::2]))==size,'unique CBOR map keys required')
        return dict(zip(items[::2],items[1::2])),offset
    if major==6:
        require(size==42,'CID tag 42 required');value,offset=cbor_read(data,offset,depth+1)
        require(isinstance(value,bytes) and value.startswith(b'\0'),'CID identity prefix required');return ('cid',value[1:]),offset
    raise ProtocolError('IPFS_REJECTED','unsupported CAR header value')


def export_car(payload):
    require(isinstance(payload,bytes) and len(payload)<=MAX_FILE,'16 MiB file budget')
    chunks=[payload[index:index+BLOCK_BYTES] for index in range(0,len(payload),BLOCK_BYTES)] or [b'']
    blocks={block_cid(chunk):chunk for chunk in chunks}
    if len(chunks)==1:root=block_cid(payload)
    else:
        metadata=field(1,2)+field(3,len(payload))+b''.join(field(4,len(chunk)) for chunk in chunks)
        links=b''.join(field(2,field(1,block_cid(chunk))+field(2,b'')+field(3,len(chunk))) for chunk in chunks)
        node=links+field(1,metadata);root=block_cid(node,0x70);blocks={root:node,**blocks}
    header=b'\xa2\x65roots\x81\xd8\x2a'+cbor_head(2,len(root)+1)+b'\0'+root+b'\x67version\x01'
    body=varint(len(header))+header+b''.join(varint(len(cid)+len(data))+cid+data for cid,data in blocks.items())
    return cid_text(root),body


def import_car(expected,archive):
    root=parse_cid(expected);require(isinstance(archive,bytes) and len(archive)<=MAX_CAR,'bounded CAR required')
    length,offset=integer(archive);require(length<=4096 and offset+length<=len(archive),'CAR header budget')
    header,end=cbor_read(archive[offset:offset+length]);require(end==length and header=={'roots':[('cid',root)],'version':1},'expected single CAR root required');offset+=length
    blocks={}
    while offset<len(archive):
        length,offset=integer(archive,offset);require(0<length<=2*1024*1024 and offset+length<=len(archive),'CAR block budget')
        section=archive[offset:offset+length];offset+=length;cid,codec,digest,start=cid_prefix(section);raw=section[start:]
        require(hashlib.sha256(raw).digest()==digest,'block CID digest mismatch')
        require(cid not in blocks or blocks[cid]==(codec,raw),'conflicting duplicate block')
        blocks[cid]=(codec,raw);require(len(blocks)<=4096,'CAR block count budget')
    visits=[0];total=[0]
    def walk(cid,stack=()):
        visits[0]+=1;require(len(stack)<64 and visits[0]<=8192 and cid not in stack,'bounded acyclic UnixFS graph required')
        require(cid in blocks,'required UnixFS block missing');codec,raw=blocks[cid]
        if codec==0x55:
            total[0]+=len(raw);require(total[0]<=MAX_FILE,'expanded file budget exceeded');return raw
        node=protobuf(raw);data=[value for n,w,value in node if n==1 and w==2];links=[value for n,w,value in node if n==2 and w==2]
        require(len(data)==1 and len(data)+len(links)==len(node),'UnixFS PBNode fields required')
        meta=protobuf(data[0]);types=[v for n,w,v in meta if n==1 and w==0];require(types in ([0],[2]),'UnixFS file required; directories and symlinks rejected')
        inline=[v for n,w,v in meta if n==2 and w==2];require(len(inline)<=1,'one inline payload required')
        body=inline[0] if inline else b'';total[0]+=len(body);require(total[0]<=MAX_FILE,'expanded file budget exceeded')
        sizes=[]
        for n,w,v in meta:
            if n==4:
                if w==0:sizes.append(v)
                else:
                    pos=0
                    while pos<len(v):size,pos=integer(v,pos);sizes.append(size)
        require(len(sizes)==len(links),'UnixFS link/size count mismatch')
        parts=[body]
        for index,link in enumerate(links):
            fields=protobuf(link);hashes=[v for n,w,v in fields if n==1 and w==2]
            require(len(hashes)==1 and all(n in {1,2,3} for n,w,v in fields),'file link CID required')
            require(all(v==b'' for n,w,v in fields if n==2),'UnixFS file link names must be empty')
            child,_,_,end=cid_prefix(hashes[0]);require(end==len(hashes[0]),'complete child CID required')
            payload=walk(child,stack+(cid,));require(len(payload)==sizes[index],'UnixFS block size mismatch');parts.append(payload)
        result=b''.join(parts);declared=[v for n,w,v in meta if n==3 and w==0]
        require(len(declared)==1 and declared[0]==len(result),'UnixFS filesize mismatch')
        return result
    return walk(root)


def fetch_car(gateways,source,cid):
    """Fetch only an operator-configured source; use the shared native carrier."""
    import http.client,ipaddress,ssl
    from urllib.parse import urlsplit
    from .carrier import open_carrier
    from .runtime_policy import require_network
    require_network();cid=cid_text(parse_cid(cid))
    setting=gateways.get(source) if isinstance(gateways,dict) else None
    require(isinstance(setting,dict) and {'url'}<=set(setting) and not set(setting)-{'url','carrier','token_file'},'configured IPFS source alias required')
    target=urlsplit(setting['url']);require(target.hostname and not target.username and not target.password and not target.query and not target.fragment,'fixed gateway URL required')
    local=False
    try:local=ipaddress.ip_address(target.hostname).is_loopback
    except ValueError:pass
    require(target.scheme=='https' or target.scheme=='http' and local,'gateway HTTPS required outside loopback')
    headers={'Accept':'application/vnd.ipld.car','Connection':'close'}
    if setting.get('token_file'):headers['Authorization']='Bearer '+secure_read(Path(setting['token_file']),2048).decode().strip()
    port=target.port or (443 if target.scheme=='https' else 80);connection=http.client.HTTPConnection(target.hostname,port,timeout=8)
    raw=None;deadline=time.monotonic()+12
    try:
        raw=open_carrier(target.hostname,port,setting.get('carrier'),timeout=8)
        if target.scheme=='https':
            context=ssl.create_default_context()
            if (setting.get('carrier') or {}).get('kind') in {'shadow6-stream','peer-multihop'}:
                from .peer_proxy import TLSStream
                connection.sock=TLSStream(raw,context,target.hostname,deadline)
            else:connection.sock=context.wrap_socket(raw,server_hostname=target.hostname)
        else:connection.sock=raw
        connection.request('GET',target.path.rstrip('/')+'/ipfs/'+cid+'?format=car&dag-scope=all',headers=headers)
        response=connection.getresponse();require(response.status==200,'IPFS gateway rejected request or redirected')
        chunks=[];size=0
        while True:
            chunk=response.read1(65536)
            if not chunk:break
            chunks.append(chunk);size+=len(chunk);require(size<=MAX_CAR and time.monotonic()<deadline,'gateway response budget exceeded')
        return b''.join(chunks)
    finally:
        connection.close()
        if raw is not None:raw.close()


class IpfsBridge:
    def __init__(self,fabric):
        self.fabric=fabric
        with fabric.transaction():fabric.db.execute('CREATE TABLE IF NOT EXISTS ipfs_links(owner TEXT,cid TEXT,object TEXT,PRIMARY KEY(owner,cid))')

    def store(self,owner,payload,*,name='ipfs-content',mime='application/octet-stream'):
        from .chunkstore import CHUNK_BYTES
        upload='ipfs-'+secrets.token_hex(16);self.fabric.begin(owner,upload,len(payload),'sha256:'+hashlib.sha256(payload).hexdigest(),mime,name)
        for position,index in enumerate(range(0,len(payload),CHUNK_BYTES)):self.fabric.put(owner,upload,position,payload[index:index+CHUNK_BYTES])
        return self.fabric.finish(owner,upload)

    def ingest(self,owner,cid,archive,*,name='ipfs-content',mime='application/octet-stream'):
        payload=import_car(cid,archive);cid=cid_text(parse_cid(cid))
        previous=self.fabric.db.execute('SELECT object FROM ipfs_links WHERE owner=? AND cid=?',(owner,cid)).fetchone()
        if previous:
            self.fabric.object_info(owner,previous[0]);return {'cid':cid,'id':previous[0],'duplicate':True,'cid_verified':True}
        result=self.store(owner,payload,name=name,mime=mime)
        with self.fabric.transaction():self.fabric.db.execute('INSERT OR REPLACE INTO ipfs_links VALUES (?,?,?)',(owner,cid,result['id']))
        return dict(result,cid=cid,duplicate=False,cid_verified=True)

    def export(self,owner,oid):
        from .chunkstore import CHUNK_BYTES
        info=self.fabric.object_info(owner,oid);metadata=json.loads(info['metadata']);size=metadata['size']
        require(size<=MAX_FILE,'16 MiB file budget')
        payload=b''.join(self.fabric.read_chunk(owner,oid,index) for index in range((size+CHUNK_BYTES-1)//CHUNK_BYTES))
        require(len(payload)==size and 'sha256:'+hashlib.sha256(payload).hexdigest()==metadata['digest'],'Fabric content digest mismatch')
        cid,archive=export_car(payload);stored=self.store(owner,archive,name=cid+'.car',mime='application/vnd.ipld.car')
        with self.fabric.transaction():self.fabric.db.execute('INSERT OR REPLACE INTO ipfs_links VALUES (?,?,?)',(owner,cid,oid))
        return {'cid':cid,'uri':'ipfs://'+cid,'archive':stored['id'],'size':size,'car_bytes':len(archive),'publicly_pinned':False}

    def import_object(self,owner,cid,oid):
        from .chunkstore import CHUNK_BYTES
        info=self.fabric.object_info(owner,oid);meta=json.loads(info['metadata']);require(meta['size']<=MAX_CAR,'bounded CAR object required')
        archive=b''.join(self.fabric.read_chunk(owner,oid,i) for i in range((meta['size']+CHUNK_BYTES-1)//CHUNK_BYTES))
        return self.ingest(owner,cid,archive)

    def fetch(self,owner,cid,source):
        return self.ingest(owner,cid,fetch_car(getattr(self.fabric,'ipfs_gateways',{}),source,cid))


def main(argv=None):
    parser=argparse.ArgumentParser(prog='ziokt ipfs');sub=parser.add_subparsers(dest='action',required=True)
    for action in ('import','export','fetch'):
        command=sub.add_parser(action);command.add_argument('--root',type=Path,required=True);command.add_argument('--owner',required=True)
        if action in {'import','fetch'}:
            command.add_argument('--cid',required=True)
            if action=='import':command.add_argument('--car',type=Path,required=True)
            else:command.add_argument('--gateway-config',type=Path,required=True);command.add_argument('--source',required=True)
        else:command.add_argument('--id',required=True);command.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    from .content_fabric import Fabric
    fabric=Fabric(args.root)
    try:
        bridge=IpfsBridge(fabric)
        if args.action=='import':result=bridge.ingest(args.owner,args.cid,secure_read(args.car,MAX_CAR,private=None))
        elif args.action=='fetch':
            from .protocol import strict_json
            fabric.ipfs_gateways=strict_json(secure_read(args.gateway_config,65536),65536)
            result=bridge.fetch(args.owner,args.cid,args.source)
        else:
            result=bridge.export(args.owner,args.id);info=fabric.object_info(args.owner,result['archive']);meta=json.loads(info['metadata'])
            from .chunkstore import CHUNK_BYTES
            data=b''.join(fabric.read_chunk(args.owner,result['archive'],i) for i in range((meta['size']+CHUNK_BYTES-1)//CHUNK_BYTES))
            from .cli import write_binary_exclusive
            write_binary_exclusive(args.output,data)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:fabric.close()

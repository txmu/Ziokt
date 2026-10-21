"""Typed binding to the native ETP FileShare v1 engine; no substitute file wire."""
import base64
import ipaddress
import re
from .protocol import ProtocolError

METHODS=frozenset({'etp.fileshare.list','etp.fileshare.manifest','etp.fileshare.chunk','etp.fileshare.request','etp.fileshare.status'})
HEX=re.compile('[a-f0-9]{64}\\Z')
NAME=re.compile('[A-Za-z0-9_-]{1,64}\\Z')


def native_hash(value):
    if not isinstance(value,str) or not HEX.fullmatch(value):raise ValueError('exact native BLAKE3 root required')


def params(method,value):
    fields=set() if method=='etp.fileshare.list' else {'hash','index'} if method=='etp.fileshare.chunk' else {'hash','peer'} if method=='etp.fileshare.request' else {'hash'}
    if not isinstance(value,dict) or set(value)!=fields:raise ProtocolError('INVALID_PARAMS','Exact native FileShare fields required')
    try:
        if fields:native_hash(value['hash'])
        if 'index' in value and (type(value['index']) is not int or not 0<=value['index']<1024):raise ValueError()
        if 'peer' in value:
            if not isinstance(value['peer'],str):raise ValueError()
            host,separator,port=value['peer'].rpartition(':')
            if not separator or not port.isascii() or not port.isdecimal() or not 1<=int(port)<=65535:raise ValueError()
            ipaddress.ip_address(host[1:-1] if host.startswith('[') and host.endswith(']') else host)
    except ValueError:raise ProtocolError('INVALID_PARAMS','Bounded native root, chunk and literal approved peer required') from None


def result(method,request,value):
    try:
        if not isinstance(value,dict):raise ValueError()
        if method=='etp.fileshare.list':
            if set(value)!={'schema','exports','chunk_bytes','file_bytes_limit'} or value['schema']!='ziokt.etp-fileshare-list.v1' or value['chunk_bytes']!=16384 or value['file_bytes_limit']!=16777216 or not isinstance(value['exports'],list) or len(value['exports'])>16:raise ValueError()
            names=set()
            for entry in value['exports']:
                if not isinstance(entry,dict) or set(entry)!={'name','hash'} or not isinstance(entry['name'],str) or not NAME.fullmatch(entry['name']) or entry['name'] in names:raise ValueError()
                names.add(entry['name']);native_hash(entry['hash'])
        elif method in {'etp.fileshare.status','etp.fileshare.request'}:
            if set(value)!={'schema','state','received','total','content_verified'} or value['schema']!='ziokt.etp-fileshare-status.v1' or value['state'] not in {'absent','requested','downloading','timed_out','locally_indexed'} or value['content_verified'] is not False:raise ValueError()
            if type(value['received']) is not int or type(value['total']) is not int or not 0<=value['received']<=value['total']<=1024:raise ValueError()
            if value['state']=='locally_indexed' and not 0<value['received']==value['total']:raise ValueError()
        elif method=='etp.fileshare.manifest':
            if set(value)!={'schema','hash','name','size','mime','chunk_bytes','chunks','content_verified'} or value['schema']!='ziokt.etp-fileshare-manifest.v1' or value['hash']!=request['hash'] or value['chunk_bytes']!=16384 or value['content_verified'] is not False:raise ValueError()
            if not isinstance(value['name'],str) or len(value['name'].encode())>255 or not isinstance(value['mime'],str) or len(value['mime'].encode())>128:raise ValueError()
            if type(value['size']) is not int or not 1<=value['size']<=16777216 or not isinstance(value['chunks'],list) or len(value['chunks'])!=(value['size']+16383)//16384:raise ValueError()
            for digest in value['chunks']:native_hash(digest)
        else:
            if set(value)!={'schema','hash','index','data_base64','native_chunk_verified'} or value['schema']!='ziokt.etp-fileshare-chunk.v1' or value['hash']!=request['hash'] or type(value['index']) is not int or value['index']!=request['index'] or value['native_chunk_verified'] is not True:raise ValueError()
            parts=value['data_base64']
            if not isinstance(parts,list) or not 1<=len(parts)<=6 or any(not isinstance(part,str) or not 1<=len(part)<=4096 for part in parts):raise ValueError()
            decoded=[base64.b64decode(part,validate=True) for part in parts]
            if any(base64.b64encode(raw).decode()!=part for raw,part in zip(decoded,parts)) or not 1<=sum(map(len,decoded))<=16384:raise ValueError()
    except (ValueError,TypeError,KeyError):raise ProtocolError('INVALID_RESPONSE','Native FileShare response schema/integrity contract rejected') from None
    return value

"""Pinned interpreted coordinator for the native ETP onion gateway.

The native binary is built in CI; no host configuration or silent direct route.
"""
import base64
import hashlib
import os
from pathlib import Path
import select
import subprocess
import threading
import tempfile
import time
from .protocol import ProtocolError,encoded,secure_read,strict_json

from .etp_fileshare import METHODS as FILESHARE_METHODS

FORUM_METHODS=frozenset({'etp.forum.identity','etp.forum.subscribe','etp.forum.publish','etp.forum.get','etp.forum.scan'})

def _forum_text(value, maximum, *, empty=False):
    try:valid=isinstance(value,str) and (empty or bool(value)) and len(value.encode('utf-8'))<=maximum
    except UnicodeError:valid=False
    if not valid:raise ProtocolError('INVALID_ETP','bounded UTF-8 Forum text required')
    return value

def _forum_id(value):
    if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdefABCDEF' for c in value):raise ProtocolError('INVALID_ETP','32-byte hexadecimal Forum ID required')
    return value

def _forum_name(value):
    if not isinstance(value,str) or not 1<=len(value)<=64 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in value):raise ProtocolError('INVALID_ETP','configured Forum identity name required')

def _forum_params(method,params):
    fields={'etp.forum.identity':{'name'},'etp.forum.subscribe':{'topic'},'etp.forum.get':{'id'},'etp.forum.scan':{'topic','author_id','snapshot','after','limit'}}
    if method=='etp.forum.publish':
        if not {'topic','content','author'}<=set(params) or set(params)-{'topic','content','author','parent_id','timestamp'}:raise ProtocolError('INVALID_ETP','explicit named author or null and exact Forum fields required')
        _forum_text(params['content'],32768)
        if 'timestamp' in params and (type(params['timestamp']) is not int or not 0<=params['timestamp']<(1<<53)):raise ProtocolError('INVALID_ETP','bounded native timestamp required')
        if params['author'] is not None:_forum_name(params['author'])
        if params.get('parent_id') is not None:_forum_id(params['parent_id'])
    elif set(params)!=fields[method]:raise ProtocolError('INVALID_ETP','exact Forum query fields required')
    if method=='etp.forum.scan':
        _forum_id(params['author_id'])
        for field in ('snapshot','after'):
            if params[field]!='':_forum_id(params[field])
        if type(params['limit']) is not int or not 1<=params['limit']<=64 or params['after'] and not params['snapshot']:raise ProtocolError('INVALID_ETP','bounded native snapshot cursor required')
    if 'topic' in params:
        value=_forum_text(params['topic'],256)
        if any(ord(c)<32 or 127<=ord(c)<=159 for c in value):raise ProtocolError('INVALID_ETP','printable Forum topic required')
    if 'name' in params:_forum_name(params['name'])
    if 'id' in params:_forum_id(params['id'])

def _forum_result(method,params,result):
    if not isinstance(result,dict):raise ProtocolError('INVALID_RESPONSE','typed Forum response required')
    try:
        if method=='etp.forum.identity':
            if set(result)!={'schema','name','author_id'} or result['schema']!='ziokt.etp-forum-identity.v1' or result['name']!=params['name']:raise ValueError()
            _forum_id(result['author_id'])
        elif method=='etp.forum.subscribe':
            if set(result)!={'subscribed','topic_hash'} or result['subscribed'] is not True:raise ValueError()
            _forum_id(result['topic_hash'])
        elif method=='etp.forum.scan':
            if set(result)!={'schema','state','topic_hash','author_id','snapshot','ids','after','complete'} or result['schema']!='ziokt.etp-forum-scan.v1' or result['state'] not in {'page','snapshot_changed'} or result['author_id'].lower()!=params['author_id'].lower() or type(result['complete']) is not bool:raise ValueError()
            for field in ('topic_hash','author_id','snapshot'):_forum_id(result[field])
            ids=result['ids']
            if not isinstance(ids,list) or len(ids)>params['limit'] or len(set(ids))!=len(ids) or ids!=sorted(ids):raise ValueError()
            for identifier in ids:_forum_id(identifier)
            if result['after']!='':_forum_id(result['after'])
            if result['state']=='snapshot_changed':
                if ids or result['after'] or result['complete']:raise ValueError()
            elif ids and result['after']!=ids[-1]:raise ValueError()
            elif not ids and (not result['complete'] or result['after']!=params['after']):raise ValueError()
            if result['state']=='page' and params['snapshot'] and result['snapshot']!=params['snapshot'].lower():raise ValueError()
            if ids and params['after'] and ids[0]<=params['after'].lower():raise ValueError()
        elif method=='etp.forum.publish':
            if set(result)!={'schema','id','stored','dht_enqueued','delivery_confirmed','state','gossip'} or result['schema']!='ziokt.etp-forum-publish.v1' or result['stored'] is not True or type(result['dht_enqueued']) is not bool or result['delivery_confirmed'] is not False or result['state']!='stored_locally' or result['gossip']!='best_effort':raise ValueError()
            _forum_id(result['id'])
        else:
            if set(result)!={'post'}:raise ValueError()
            post=result['post']
            if post is None:return result
            if not isinstance(post,dict) or set(post)!={'id','topic_hash','author_id','timestamp','content_base64','parent_id','signature_base64','parent_status'}:raise ValueError()
            if post['id'].lower()!=params['id'].lower() or type(post['timestamp']) is not int or not 0<=post['timestamp']<(1<<53):raise ValueError()
            for field in ('id','topic_hash'):_forum_id(post[field])
            for field in ('author_id','parent_id'):
                if post[field] is not None:_forum_id(post[field])
            chunks=post['content_base64']
            if not isinstance(chunks,list) or not 1<=len(chunks)<=11 or any(not isinstance(c,str) or not 1<=len(c)<=4096 for c in chunks):raise ValueError()
            content=b''.join(base64.b64decode(c,validate=True) for c in chunks)
            if not 1<=len(content)<=32768:raise ValueError()
            content.decode('utf-8')
            if not isinstance(post['signature_base64'],str) or len(post['signature_base64'])>128:raise ValueError()
            signature=base64.b64decode(post['signature_base64'],validate=True)
            if len(signature)!=(0 if post['author_id'] is None else 96):raise ValueError()
            if post['parent_status'] not in ('not_reply','available','missing_or_expired') or (post['parent_id'] is None)!=(post['parent_status']=='not_reply'):raise ValueError()
    except (ValueError,TypeError,KeyError,AttributeError,ProtocolError,UnicodeError):raise ProtocolError('INVALID_RESPONSE','native Forum response shape rejected')
    return result

class EtpGateway:
    def __init__(self,binary,digest,config):
        self.binary=Path(binary).absolute();self.config=Path(config).absolute();self.digest=digest;self.config_bytes=secure_read(self.config)
        if 'sha256:'+hashlib.sha256(secure_read(self.binary,128*1024*1024,private=False)).hexdigest()!=digest:raise ProtocolError('ARTIFACT_DIGEST_MISMATCH','reviewed ETP binary changed')
        secure_read(self.config);self.process=None;self._snapshot=None;self.lock=threading.RLock();self.sequence=0
    def close(self,*,graceful=True):
        with self.lock:
            if self.process is not None:
                if graceful and self.process.poll() is None:
                    try:
                        self.sequence+=1
                        self.process.stdin.write(encoded({'id':self.sequence,'method':'etp.shutdown','params':{}})+b'\n');self.process.stdin.flush()
                        self.process.wait(timeout=1)
                    except (OSError,ValueError,subprocess.TimeoutExpired):pass
                if self.process.poll() is None:
                    self.process.terminate()
                    try:self.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
                for stream in (self.process.stdin,self.process.stdout):
                    if stream is not None:
                        try:stream.close()
                        except OSError:pass
                self.process=None
            if self._snapshot is not None:
                self._snapshot.cleanup();self._snapshot=None
    def call(self,method,params):
        from .runtime_policy import require_network
        require_network()
        if not isinstance(method,str) or method not in {'etp.stats','etp.onion.send','etp.receive','etp.shutdown','etp.mailbox.status','etp.mailbox.request'}|FORUM_METHODS|FILESHARE_METHODS or not isinstance(params,dict):raise ProtocolError('METHOD_UNSUPPORTED','bounded native ETP operation required')
        if method=='etp.onion.send':
            if set(params)!={'hops','ciphertext'} or not isinstance(params['hops'],list) or not 2<=len(params['hops'])<=4:raise ProtocolError('INVALID_ETP','private 2..4-hop path required')
            try:data=base64.b64decode(params['ciphertext'],validate=True)
            except (ValueError,TypeError):raise ProtocolError('INVALID_ETP','sealed ETP packet required')
            if not 16384<=len(data)<=65536 or len(data)&(len(data)-1):raise ProtocolError('INVALID_ETP','power-of-two sealed ETP packet required')
        elif method=='etp.mailbox.request':
            if set(params)!={'frame_base64'} or not isinstance(params['frame_base64'],str) or len(params['frame_base64'])>12000:raise ProtocolError('INVALID_ETP','bounded mailbox v2 frame required')
            try:frame=base64.b64decode(params['frame_base64'],validate=True)
            except (ValueError,TypeError):raise ProtocolError('INVALID_ETP','mailbox frame encoding')
            if len(frame)<2 or frame[0]!=2 or frame[1] not in {1,2,4,6}:raise ProtocolError('INVALID_ETP','recipient mailbox operations only')
        elif method in FORUM_METHODS:_forum_params(method,params)
        elif method in FILESHARE_METHODS:
            from .etp_fileshare import params as file_params
            file_params(method,params)
        elif params:raise ProtocolError('INVALID_ETP','exact native query required')
        with self.lock:
            try:current=secure_read(self.config)
            except (OSError,ProtocolError):self.close(graceful=False);raise
            if current!=self.config_bytes:
                self.close(graceful=False);raise ProtocolError('STALE_PLAN','ETP node configuration changed')
            if self.process is None:
                binary=secure_read(self.binary,128*1024*1024,private=False)
                if 'sha256:'+hashlib.sha256(binary).hexdigest()!=self.digest:raise ProtocolError('ARTIFACT_DIGEST_MISMATCH','reviewed ETP binary changed')
                # Execute exactly the reviewed bytes in an owner-private directory.
                # A rename of the original path after hashing cannot change this child.
                self._snapshot=tempfile.TemporaryDirectory(prefix='ziokt-etp-')
                executable=Path(self._snapshot.name)/'gateway'
                try:
                    with executable.open('xb') as target:target.write(binary)
                    executable.chmod(0o700)
                    env={k:v for k,v in os.environ.items() if k in {'PATH','LANG','LC_ALL'}}
                    self.process=subprocess.Popen([str(executable),str(self.config)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env,start_new_session=True)
                except BaseException:self.close(graceful=False);raise
            self.sequence+=1;request=encoded({'id':self.sequence,'method':method,'params':params})+b'\n'
            if len(request)>131072:raise ProtocolError('REQUEST_LIMIT','native ETP request exceeds budget')
            try:
                self.process.stdin.write(request);self.process.stdin.flush();data=bytearray();deadline=time.monotonic()+10
                while not data.endswith(b'\n'):
                    remaining=deadline-time.monotonic()
                    if remaining<=0 or not select.select([self.process.stdout],[],[],remaining)[0]:raise ProtocolError('PROVIDER_TIMEOUT','native ETP deadline exceeded')
                    byte=os.read(self.process.stdout.fileno(),1)
                    if not byte or len(data)>=131072:raise ProtocolError('INVALID_RESPONSE','native ETP bounded response required')
                    data.extend(byte)
                response=strict_json(bytes(data),131072,string_limit=90000 if method.startswith('etp.mailbox.') else 8192)
                if not isinstance(response,dict) or response.get('id')!=self.sequence:raise ProtocolError('INVALID_RESPONSE','native ETP correlation rejected')
                if response.get('ok') is not True:
                    code='METHOD_UNSUPPORTED' if isinstance(response.get('error'),dict) and response['error'].get('code')=='METHOD_UNSUPPORTED' else 'ETP_REJECTED'
                    raise ProtocolError(code,'native ETP gateway rejected the operation')
                result=response.get('result')
                if method in FILESHARE_METHODS:
                    from .etp_fileshare import result as file_result
                    return file_result(method,params,result)
                return _forum_result(method,params,result) if method in FORUM_METHODS else result
            except ProtocolError as error:
                # A well-formed native `{ok:false}` is an operation rejection,
                # not a broken child process. Keep its in-memory native state.
                if error.code not in {'ETP_REJECTED','METHOD_UNSUPPORTED'}:self.close(graceful=False)
                raise
            except BaseException:self.close(graceful=False);raise

class EtpRecordSocket:
    """Actual ETP message-boundary adapter for Corium's signed data channel.

    Native onion transport wraps independent, direction-keyed AEAD records.
    This is a message carrier; it does not pretend to be a TCP/mTLS stream.
    """
    def __init__(self,gateway,hops,key,scope,*,server=False,max_record=4096):
        from .protocol import identifier
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes
        identifier(scope,'ETP scope')
        if not isinstance(key,bytes) or len(key)!=32 or not isinstance(hops,list) or not 2<=len(hops)<=4 or len(set(hops))!=len(hops):raise ProtocolError('INVALID_ETP','independent key and distinct approved 2..4-hop path required')
        if type(max_record) is not int or not 1<=max_record<=60000:raise ProtocolError('INVALID_ETP','bounded record size required')
        self.max_record=max_record
        self.gateway=gateway;self.hops=list(hops);self.timeout=10;self.aad=('Ziokt/ETP/record/v1/'+scope).encode()
        keys=[HKDF(hashes.SHA256(),32,None,self.aad+b'/'+direction).derive(key) for direction in (b'client-to-server',b'server-to-client')]
        self.sender=AESGCM(keys[1 if server else 0]);self.receiver=AESGCM(keys[0 if server else 1])
    def gettimeout(self):return self.timeout
    def settimeout(self,value):
        if value is None:value=10
        if type(value) not in {int,float} or not 0<value<=30:raise ProtocolError('INVALID_ETP','bounded ETP timeout required')
        self.timeout=value
    def send(self,data):
        if not isinstance(data,bytes) or not 1<=len(data)<=self.max_record:raise ProtocolError('DATA_FRAME_LIMIT','bounded native Corium record required')
        budget=max(16384,1<<(len(data)+31).bit_length())
        nonce=os.urandom(12);plain=len(data).to_bytes(4,'big')+data+os.urandom(budget-28-4-len(data));packet=nonce+self.sender.encrypt(nonce,plain,self.aad)
        result=self.gateway.call('etp.onion.send',{'hops':self.hops,'ciphertext':base64.b64encode(packet).decode()})
        if result.get('accepted') is not True:raise ProtocolError('ETP_REJECTED','native onion submission denied')
        return len(data)
    def recv(self,maximum):
        from cryptography.exceptions import InvalidTag
        value=self.gateway.call('etp.receive',{}).get('ciphertext')
        if value is None:
            import socket
            raise socket.timeout('ETP record receive deadline')
        if not isinstance(value,list) or len(value)>22 or any(not isinstance(chunk,str) or len(chunk)>4096 for chunk in value):raise ProtocolError('INVALID_RESPONSE','bounded ETP encoded chunks required')
        try:
            data=b''.join(base64.b64decode(chunk,validate=True) for chunk in value)
            if len(data) not in (16384,32768,65536) or (self.max_record==4096 and len(data)!=16384):raise ValueError()
            plain=self.receiver.decrypt(data[:12],data[12:],self.aad);size=int.from_bytes(plain[:4],'big')
            if not 1<=size<=min(maximum,self.max_record):raise ValueError()
            return plain[4:4+size]
        except (ValueError,InvalidTag):raise ProtocolError('DATA_AUTH_REJECTED','ETP frame authentication, scope or budget rejected')
    def close(self):self.gateway.close()


def corium_channel(gateway,hops,transport_key,application_key,native_private,expected_peer,network,*,scope):
    """Native Corium signatures, existing fragmentation/retries and ETP onion hops."""
    from types import SimpleNamespace
    from ._runtime import CoriumDataChannel
    if transport_key==application_key:raise ProtocolError('INVALID_ETP','transport and Corium application keys must be independent')
    handle=SimpleNamespace(socket=EtpRecordSocket(gateway,hops,transport_key,scope),boundary=SimpleNamespace(kind='message',max_record=4096))
    return CoriumDataChannel(handle,application_key,native_private,expected_peer,network,privacy_profile='private')

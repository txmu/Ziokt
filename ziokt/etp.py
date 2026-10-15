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
import time
from .protocol import ProtocolError,encoded,secure_read,strict_json

class EtpGateway:
    def __init__(self,binary,digest,config):
        self.binary=Path(binary).absolute();self.config=Path(config).absolute();self.digest=digest;self.config_bytes=secure_read(self.config)
        if 'sha256:'+hashlib.sha256(secure_read(self.binary,128*1024*1024,private=None)).hexdigest()!=digest:raise ProtocolError('ARTIFACT_DIGEST_MISMATCH','reviewed ETP binary changed')
        secure_read(self.config);self.process=None;self.lock=threading.RLock();self.sequence=0
    def close(self):
        if self.process is not None:
            self.process.terminate()
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
            if self.process.stdin is not None:self.process.stdin.close()
            if self.process.stdout is not None:self.process.stdout.close()
            self.process=None
    def call(self,method,params):
        from .runtime_policy import require_network
        require_network()
        if method not in {'etp.stats','etp.onion.send','etp.receive','etp.shutdown'} or not isinstance(params,dict):raise ProtocolError('METHOD_UNSUPPORTED','bounded native ETP operation required')
        if method=='etp.onion.send':
            if set(params)!={'hops','ciphertext'} or not isinstance(params['hops'],list) or not 2<=len(params['hops'])<=4:raise ProtocolError('INVALID_ETP','private 2..4-hop path required')
            try:data=base64.b64decode(params['ciphertext'],validate=True)
            except (ValueError,TypeError):raise ProtocolError('INVALID_ETP','sealed ETP packet required')
            if not 16384<=len(data)<=65536 or len(data)&(len(data)-1):raise ProtocolError('INVALID_ETP','power-of-two sealed ETP packet required')
        elif params:raise ProtocolError('INVALID_ETP','exact native query required')
        with self.lock:
            if secure_read(self.config)!=self.config_bytes:raise ProtocolError('STALE_PLAN','ETP node configuration changed')
            if self.process is None:
                if 'sha256:'+hashlib.sha256(secure_read(self.binary,128*1024*1024,private=None)).hexdigest()!=self.digest:raise ProtocolError('ARTIFACT_DIGEST_MISMATCH','reviewed ETP binary changed')
                env={k:v for k,v in os.environ.items() if k in {'PATH','LANG','LC_ALL'}}
                self.process=subprocess.Popen([str(self.binary),str(self.config)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env,start_new_session=True)
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
                response=strict_json(bytes(data),131072)
                if response.get('id')!=self.sequence or response.get('ok') is not True:raise ProtocolError('ETP_REJECTED','native ETP gateway rejected the operation')
                return response['result']
            except BaseException:self.close();raise

class EtpRecordSocket:
    """Actual ETP message-boundary adapter for Corium's signed data channel.

    Native onion transport wraps independent, direction-keyed AEAD records.
    This is a message carrier; it does not pretend to be a TCP/mTLS stream.
    """
    def __init__(self,gateway,hops,key,scope,*,server=False):
        from .protocol import identifier
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes
        identifier(scope,'ETP scope')
        if not isinstance(key,bytes) or len(key)!=32 or not isinstance(hops,list) or not 2<=len(hops)<=4 or len(set(hops))!=len(hops):raise ProtocolError('INVALID_ETP','independent key and distinct approved 2..4-hop path required')
        self.gateway=gateway;self.hops=list(hops);self.timeout=10;self.aad=('Ziokt/ETP/record/v1/'+scope).encode()
        keys=[HKDF(hashes.SHA256(),32,None,self.aad+b'/'+direction).derive(key) for direction in (b'client-to-server',b'server-to-client')]
        self.sender=AESGCM(keys[1 if server else 0]);self.receiver=AESGCM(keys[0 if server else 1])
    def gettimeout(self):return self.timeout
    def settimeout(self,value):
        if value is None:value=10
        if type(value) not in {int,float} or not 0<value<=30:raise ProtocolError('INVALID_ETP','bounded ETP timeout required')
        self.timeout=value
    def send(self,data):
        if not isinstance(data,bytes) or not 1<=len(data)<=4096:raise ProtocolError('DATA_FRAME_LIMIT','bounded native Corium record required')
        nonce=os.urandom(12);plain=len(data).to_bytes(4,'big')+data+os.urandom(16384-28-4-len(data));packet=nonce+self.sender.encrypt(nonce,plain,self.aad)
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
            if len(data)!=16384:raise ValueError()
            plain=self.receiver.decrypt(data[:12],data[12:],self.aad);size=int.from_bytes(plain[:4],'big')
            if not 1<=size<=min(maximum,4096):raise ValueError()
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

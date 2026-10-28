"""Explicit bounded file carrier over the native authenticated RetroShare F2F API.

Native SHA1 addresses locate files; only caller-pinned SHA256 and exact size
accept received bytes. Queueing a native transfer is never reported as delivery.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
from .protocol import ProtocolError,secure_read

MAX_BYTES=64*1024

def identifier(value,size):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{'+str(size)+'}',value):raise ProtocolError('INVALID_REQUEST','canonical RetroShare transport identifier required')
    return value

class FileCarrier:
    def __init__(self,native):
        self.native=native;config=native.config.get('transport')
        if not native.enabled or not isinstance(config,dict) or set(config)!={'root','allowed_peers'}:raise ProtocolError('POLICY_DENIED','explicit RetroShare transport root and peer allowlist required')
        root=Path(config['root'])
        if not root.is_absolute() or '..' in root.parts or root.is_symlink():raise ProtocolError('INVALID_CONFIG','absolute private RetroShare spool required')
        peers=config['allowed_peers']
        if not isinstance(peers,list) or len(peers)>64:raise ProtocolError('INVALID_CONFIG','bounded RetroShare peer allowlist required')
        self.peers={identifier(peer,32) for peer in peers};self.root=root;root.mkdir(parents=True,mode=0o700,exist_ok=True);root.chmod(0o700)
        for name in ('outgoing','incoming','jobs'):
            path=root/name
            if path.is_symlink():raise ProtocolError('INVALID_CONFIG','private spool cannot contain symlinks')
            path.mkdir(mode=0o700,exist_ok=True)
    def offer(self,data,seconds=3600):
        if type(seconds)is not int or not 60<=seconds<=86400:raise ProtocolError('INVALID_REQUEST','bounded RetroShare offer TTL required')
        if not isinstance(data,bytes) or not 1<=len(data)<=MAX_BYTES:raise ProtocolError('LIMIT_EXCEEDED','RetroShare file carrier accepts 1..65536 bytes')
        digest=hashlib.sha256(data).hexdigest();path=self.root/'outgoing'/(digest+'.bin')
        if path.exists():
            if secure_read(path,MAX_BYTES)!=data:raise ProtocolError('DIGEST_MISMATCH','RetroShare spool differs')
        else:
            if len(list((self.root/'outgoing').iterdir()))>=128:raise ProtocolError('LIMIT_EXCEEDED','RetroShare outgoing spool is full')
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(data)
        result=self.native._request('rsFiles/ExtraFileHash',{'localpath':str(path),'period':seconds,'flags':0})
        if result.get('retval') is not True:raise ProtocolError('NATIVE_REJECTED','RetroShare did not queue the offer')
        return {'carrier':'retroshare-f2f-files','state':'hashing','sha256':digest,'size':len(data),'delivered':False,'scope':'existing native friend policy; no anonymous routing requested'}
    def offer_status(self,digest):
        digest=identifier(digest,64);path=self.root/'outgoing'/(digest+'.bin');data=secure_read(path,MAX_BYTES)
        if hashlib.sha256(data).hexdigest()!=digest:raise ProtocolError('DIGEST_MISMATCH','RetroShare offered object changed')
        result=self.native._request('rsFiles/ExtraFileStatus',{'localpath':str(path)},allow_false=True)
        info=result.get('info',{})
        if result.get('retval') is not True:return {'state':'hashing','sha256':digest,'delivered':False}
        native_hash=identifier(info.get('hash'),40)
        if native_hash!=hashlib.sha1(data).hexdigest() or info.get('size') not in (len(data),{'xint64':len(data),'xstr64':str(len(data))}):raise ProtocolError('DIGEST_MISMATCH','RetroShare native offer metadata differs')
        return {'carrier':'retroshare-f2f-files','state':'offered','hash':native_hash,'sha256':digest,'size':len(data),'delivered':False}
    def request(self,native_hash,digest,size,peer):
        native_hash=identifier(native_hash,40);digest=identifier(digest,64);peer=identifier(peer,32)
        if peer not in self.peers or peer not in {p.lower() for p in self.native.inspect('friends')['items']}:raise ProtocolError('POLICY_DENIED','RetroShare source must be both configured and a native friend')
        if type(size)is not int or not 1<=size<=MAX_BYTES:raise ProtocolError('LIMIT_EXCEEDED','bounded RetroShare download size required')
        destination=self.root/'incoming'/digest
        if destination.is_symlink():raise ProtocolError('INVALID_REQUEST','RetroShare destination cannot be a symlink')
        if not destination.exists() and len(list((self.root/'incoming').iterdir()))>=128:raise ProtocolError('LIMIT_EXCEEDED','RetroShare incoming spool is full')
        destination.mkdir(mode=0o700,exist_ok=True)
        record={'hash':native_hash,'sha256':digest,'size':size,'source':peer}
        job=self.root/'jobs'/(digest+'.json')
        if job.exists() and json.loads(secure_read(job,4096))!=record:raise ProtocolError('CONFLICT','RetroShare digest already bound to another transfer')
        from .retroshare_node import private_json
        private_json(job,record)
        # Direct configured source only; request encryption, disable source search.
        response=self.native._request('rsFiles/FileRequest',{'fileName':digest+'.bin','hash':native_hash,'size':{'xint64':size,'xstr64':str(size)},'destPath':str(destination),'flags':0x02000080,'srcIds':[peer]})
        if response.get('retval') is not True:raise ProtocolError('NATIVE_REJECTED','RetroShare did not accept the transfer request')
        return {'carrier':'retroshare-f2f-files','state':'queued','sha256':digest,'delivered':False}
    def collect(self,digest):
        digest=identifier(digest,64);record=json.loads(secure_read(self.root/'jobs'/(digest+'.json'),4096));destination=self.root/'incoming'/digest
        if destination.is_symlink():raise ProtocolError('INVALID_REQUEST','RetroShare destination changed')
        path=destination/(digest+'.bin')
        if not path.exists():return {'state':'pending','sha256':digest,'delivered':False}
        data=secure_read(path,MAX_BYTES,private=None)
        if len(data)!=record['size'] or hashlib.sha256(data).hexdigest()!=digest or hashlib.sha1(data).hexdigest()!=record['hash']:raise ProtocolError('DIGEST_MISMATCH','RetroShare received object not verified')
        return {'carrier':'retroshare-f2f-files','state':'verified','sha256':digest,'size':len(data),'data':base64.b64encode(data).decode(),'delivered':True}

"""XOAUTH2 token refresh against fixed provider endpoints, with private rotation."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.parse
import urllib.request
from .protocol import ProtocolError,secure_read,strict_json
from .runtime_policy import require_network
_LOCK=threading.Lock()

@contextmanager
def token_lock(path):
    secure_read(path,16384)
    lock=path.with_name(path.name+'.refresh-lock')
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'a+b') as stream:
        if os.name=='nt':
            import msvcrt
            stream.write(b'0');stream.flush();stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_LOCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX)
        try:yield
        finally:
            if os.name=='nt':stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream,fcntl.LOCK_UN)

def credentials(path):
    path=Path(path)
    with _LOCK,token_lock(path):
        data=strict_json(secure_read(path,16384),16384)
        if not isinstance(data,dict) or set(data)-{'username','access_token','expires_at','refresh_token','client_id','client_secret','provider','tenant'}:raise ProtocolError('INVALID_CONFIG','OAuth private credential fields')
        for field in ('username','access_token'):
            if not isinstance(data.get(field),str) or not data[field] or len(data[field])>8192 or any(ord(c)<32 for c in data[field]):raise ProtocolError('INVALID_CONFIG','OAuth credential missing')
        if type(data.get('expires_at')) not in (int,float):raise ProtocolError('INVALID_CONFIG','OAuth expiry required')
        if data['expires_at']>time.time()+60:return data['username'],data['access_token']
        provider=data.get('provider')
        if provider=='google':endpoint='https://oauth2.googleapis.com/token'
        elif provider=='microsoft':
            tenant=data.get('tenant','common')
            if not isinstance(tenant,str) or not re.fullmatch(r'[A-Za-z0-9.-]{1,128}',tenant):raise ProtocolError('INVALID_CONFIG','Microsoft tenant')
            endpoint='https://login.microsoftonline.com/'+tenant+'/oauth2/v2.0/token'
        else:raise ProtocolError('INVALID_CONFIG','OAuth provider must be google or microsoft')
        if any(not isinstance(data.get(f),str) or not 1<=len(data[f])<=8192 for f in ('refresh_token','client_id')):raise ProtocolError('MAIL_AUTH_REQUIRED','OAuth consent and refresh token required')
        require_network()
        payload={f:data[f] for f in ('refresh_token','client_id','client_secret') if f in data};payload['grant_type']='refresh_token'
        request=urllib.request.Request(endpoint,data=urllib.parse.urlencode(payload).encode(),headers={'Content-Type':'application/x-www-form-urlencoded'})
        from .mail_export import NoRedirect
        try:
            with urllib.request.build_opener(NoRedirect()).open(request,timeout=10) as response:token=strict_json(response.read(16385),16384)
        except (OSError,ValueError) as exc:raise ProtocolError('MAIL_AUTH_REQUIRED','OAuth refresh failed; reauthorize this account') from exc
        access=token.get('access_token');expiry=token.get('expires_in')
        if not isinstance(access,str) or not 1<=len(access)<=8192 or any(ord(c)<32 for c in access) or type(expiry)is not int or not 60<=expiry<=86400:raise ProtocolError('MAIL_AUTH_REQUIRED','invalid OAuth token response')
        data.update(access_token=access,expires_at=int(time.time())+expiry)
        if 'refresh_token' in token:
            if not isinstance(token['refresh_token'],str) or not 1<=len(token['refresh_token'])<=8192:raise ProtocolError('MAIL_AUTH_REQUIRED','invalid refresh rotation')
            data['refresh_token']=token['refresh_token']
        import tempfile
        fd,temporary=tempfile.mkstemp(prefix='.mail-oauth-',dir=path.parent)
        try:
            with os.fdopen(fd,'w') as stream:json.dump(data,stream);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)
        return data['username'],access

def sasl(username,access):
    return 'user='+username+'\x01auth=Bearer '+access+'\x01\x01'

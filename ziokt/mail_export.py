"""Bounded, authenticated Content Fabric export; fail closed before SMTP queueing."""
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from .protocol import ProtocolError, secure_read

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

class MimeExport:
    def __init__(self, config):
        if not isinstance(config,dict) or set(config)-{'mode','content_url','scanner','max_file_bytes','max_total_bytes'}:
            raise ProtocolError('INVALID_CONFIG','bounded MIME export configuration required')
        self.mode=config.get('mode','references')
        if self.mode not in {'references','mime'}:raise ProtocolError('INVALID_CONFIG','mail export mode')
        self.config=config
        self.file_limit=config.get('max_file_bytes',256*1024);self.total_limit=config.get('max_total_bytes',512*1024)
        if any(type(x)is not int or not 1<=x<=512*1024 for x in [self.file_limit,self.total_limit]):raise ProtocolError('INVALID_CONFIG','MIME byte budget 1..524288')
        if self.mode=='mime':
            url=urllib.parse.urlsplit(config.get('content_url',''))
            if url.username or url.password or url.query or url.fragment or url.path not in {'','/'} or not url.hostname or (url.scheme!='https' and not(url.scheme=='http' and url.hostname in {'127.0.0.1','::1','localhost'})):
                raise ProtocolError('INVALID_CONFIG','HTTPS or loopback Content Fabric endpoint required')
            scanner=config.get('scanner')
            if not isinstance(scanner,list) or not 1<=len(scanner)<=16 or any(not isinstance(x,str) or not x or '\x00' in x for x in scanner) or not Path(scanner[0]).is_absolute():raise ProtocolError('INVALID_CONFIG','explicit absolute scanner argv required')

    def export(self, descriptors, token_file):
        if not token_file:raise ProtocolError('POLICY_DENIED','sender-scoped Content Fabric token required')
        total=sum(d['size'] for d in descriptors)
        if total>self.total_limit or any(d['size']>self.file_limit for d in descriptors):raise ProtocolError('MAIL_LIMIT','MIME export budget exceeded')
        token=secure_read(Path(token_file),8192).decode().strip()
        if not token or '\r' in token or '\n' in token:raise ProtocolError('INVALID_CONFIG','single Content Fabric bearer token required')
        output=[]
        for d in descriptors:
            if not re.fullmatch(r'[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+',d['mime']):raise ProtocolError('INVALID_ATTACHMENT','canonical MIME type required')
            request=urllib.request.Request(self.config['content_url'].rstrip('/')+'/objects/'+d['id'],headers={'Authorization':'Bearer '+token,'Accept-Encoding':'identity'})
            try:
                with urllib.request.build_opener(NoRedirect()).open(request,timeout=10) as response:
                    data=response.read(d['size']+1)
            except (OSError,urllib.error.URLError) as exc:raise ProtocolError('CONTENT_FABRIC_UNAVAILABLE','authorized attachment export failed') from exc
            if len(data)!=d['size'] or 'sha256:'+hashlib.sha256(data).hexdigest()!=d['digest']:raise ProtocolError('INVALID_ATTACHMENT','export size or digest mismatch')
            scan(data,self.config.get('scanner'))
            output.append((d,data))
        return output


def scan(data,scanner):
    if not isinstance(scanner,list) or not scanner or not Path(scanner[0]).is_absolute():raise ProtocolError('MAIL_SCAN_FAILED','an explicit scanner is required')
    with tempfile.TemporaryDirectory(prefix='ziokt-mail-scan-') as directory:
        path=Path(directory)/'attachment';path.write_bytes(data);path.chmod(0o600)
        try:result=subprocess.run([*scanner,str(path)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15,check=False)
        except (OSError,subprocess.TimeoutExpired) as exc:raise ProtocolError('MAIL_SCAN_FAILED','attachment scanner unavailable') from exc
        if result.returncode!=0:raise ProtocolError('MAIL_SCAN_FAILED','attachment rejected by scanner')

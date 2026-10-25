"""Bounded authenticated API client; streamed native content uploads/downloads."""
import base64
import hashlib
import json
from pathlib import Path
import secrets
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from .state import Error


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


class Client:
    def __init__(self, origin, token, tick=lambda: None):
        url = urlsplit(origin)
        if url.scheme not in ('http', 'https') or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
            raise Error('INVALID_CONTROLLER', 'Controller origin required')
        if url.scheme == 'http' and url.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise Error('TLS_REQUIRED', 'Remote Controllers require verified HTTPS')
        self.origin, self.token, self.tick = origin.rstrip('/'), token.strip(), tick
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, value=None, raw=None):
        self.tick()
        data = raw if raw is not None else json.dumps(value, allow_nan=False).encode() if value is not None else None
        request = Request(self.origin+path, data=data, method=method,
            headers={'Authorization':'Bearer '+self.token, 'Content-Type':'application/octet-stream' if raw is not None else 'application/json'})
        try:
            with self.opener.open(request, timeout=20) as response:
                body = response.read(2*1024*1024+1)
                if len(body) > 2*1024*1024: raise Error('RESPONSE_LIMIT', 'Controller response exceeds budget')
                return json.loads(body)
        except HTTPError as error:
            try: value = json.loads(error.read(4096))['error']
            except (ValueError, KeyError): raise Error('HTTP_ERROR', 'Controller rejected request', error.code) from None
            raise Error(value['code'], value['message'], error.code) from None

    def upload(self, project, path, *, mime='application/octet-stream'):
        path = Path(path)
        with path.open('rb') as stream: digest = 'sha256:'+hashlib.file_digest(stream, 'sha256').hexdigest()
        with path.open('rb') as stream:return self.upload_stream(project,stream,path.stat().st_size,digest,mime=mime)

    def upload_stream(self,project,stream,size,digest,*,mime='application/octet-stream'):
        upload = 'upload-'+secrets.token_hex(16)
        query = '?project='+quote(project, safe='')
        self.request('POST', '/v1/objects/begin'+query, {'upload':upload, 'size':size, 'digest':digest,'mime':mime})
        position,total=0,0
        while chunk := stream.read(16384):
            total+=len(chunk)
            if total>size:raise Error('UPLOAD_SIZE','Input changed during upload')
            self.request('PUT', '/v1/objects/'+upload+'/chunks/'+str(position)+query, raw=chunk)
            position += 1
        if total!=size:raise Error('UPLOAD_SIZE','Input truncated during upload')
        return self.request('POST', '/v1/objects/finish'+query, {'upload':upload})['reference']

    def download_artifact_file(self,project,artifact,path,destination):
        from .artifacts import validate_set,output_path
        import tempfile
        with tempfile.TemporaryDirectory(prefix='openci-artifact-set-') as temporary:
            manifest=Path(temporary)/'set.json';self.download(project,artifact,manifest,65536)
            value=validate_set(json.loads(manifest.read_bytes()))
        selected=next((entry for entry in value['files'] if entry['path']==output_path(path)),None)
        if selected is None:raise Error('ARTIFACT_NOT_FOUND','File is not in the verified artifact set',404)
        return self.download(project,selected['reference'],destination,selected['size'])

    def download(self, project, reference, path, max_size=64*1024*1024):
        query = '?project='+quote(project, safe='')
        info = self.request('GET', '/v1/objects/'+reference['object']+query)
        meta = info['metadata']
        if meta['digest'] != reference['digest'] or not 0 <= meta['size'] <= max_size:
            raise Error('SOURCE_REJECTED', 'Source digest or size rejected')
        full, size = hashlib.sha256(), 0
        with Path(path).open('xb') as stream:
            for position in range((meta['size']+16383)//16384):
                result = self.request('GET', '/v1/objects/'+reference['object']+'/chunks/'+str(position)+query)
                chunk = base64.b64decode(result['data_base64'], validate=True)
                if len(chunk) > 16384: raise Error('CHUNK_LIMIT', 'Native chunk exceeds budget')
                full.update(chunk); size += len(chunk); stream.write(chunk)
        if size != meta['size'] or 'sha256:'+full.hexdigest() != reference['digest']:
            Path(path).unlink(missing_ok=True)
            raise Error('CONTENT_INTEGRITY', 'Downloaded bytes do not match native reference')
        return path

    def cache_lookup(self, project, key):
        return self.request('GET', f'/v1/cache/lookup?project={quote(project, safe="")}&key={quote(key, safe="")}')

    def cache_store(self, project, key, artifact):
        return self.request('POST', f'/v1/cache/store?project={quote(project, safe="")}', {'key': key, 'artifact': artifact})

    def cache_list(self, project, limit=100):
        return self.request('GET', f'/v1/cache/list?project={quote(project, safe="")}&limit={limit}')

    def cache_prune(self, project, max_bytes=64*1024*1024, max_age=86400*30):
        return self.request('POST', f'/v1/cache/prune?project={quote(project, safe="")}', {'max_bytes': max_bytes, 'max_age': max_age})

    def sync_fabric_releases(self, project=None):
        body = {'project': project} if project else {}
        return self.request('POST', '/v1/releases/sync-fabric', body)

    def list_pending_fabric_releases(self, project=None):
        url = f'/v1/releases/pending-fabric?project={quote(project, safe="")}' if project else '/v1/releases/pending-fabric'
        return self.request('GET', url)

"""Read-only NNS static assets: content integrity, clean URLs, executable JS isolation."""
import base64 as _cs_b64
import hashlib as _cs_hash
import json as _cs_json
import re as _cs_re
import mimetypes as _cs_mime
from html.parser import HTMLParser as _CSParser
from urllib.parse import unquote as _cs_unquote


def cs_path(path):
    if not isinstance(path,str) or len(path)>2048 or _cs_re.search('%(?:2f|5c|00)',path,_cs_re.I):raise ValueError('invalid static path')
    path=_cs_unquote(path,errors='strict').lstrip('/')
    if any(c in path for c in ('\\','\0','?','#')) or any(x in {'.','..'} for x in path.split('/')):raise ValueError('invalid static path')
    if any(ord(c)<32 for c in path):raise ValueError('invalid static path')
    return path


def cs_resolve(manifest,path):
    if not isinstance(manifest,dict) or not isinstance(manifest.get('files'),dict) or len(manifest['files'])>100000:raise ValueError('invalid static manifest')
    path=cs_path(path);files=manifest['files']
    if not path:path=manifest.get('index','index.html')
    candidates=[path]
    if path.endswith('/'):candidates.append(path+'index.html')
    elif not path.rsplit('/',1)[-1].count('.'):candidates.extend([path+'/index.html',path+'.html'])
    for candidate in candidates:
        if candidate in files:return candidate,files[candidate],200
    # SPA fallback is opt-in; never turn missing .js assets into HTML.
    if manifest.get('static_routing')=='spa' and not path.rsplit('/',1)[-1].count('.') and 'index.html' in files:return 'index.html',files['index.html'],200
    if '404.html' in files:return '404.html',files['404.html'],404
    raise FileNotFoundError('static file unavailable')


def cs_content(digest,fetch,maximum=64*1024*1024):
    def get(key):
        if not isinstance(key,str) or not _cs_re.fullmatch('[a-f0-9]{64}',key):raise ValueError('invalid static object reference')
        data=fetch(key)
        if not isinstance(data,bytes) or len(data)>maximum or _cs_hash.sha256(data).hexdigest()!=key:raise ValueError('static object missing or corrupt')
        return data
    raw=get(digest)
    try:value=_cs_json.loads(raw)
    except (UnicodeError,ValueError):return raw
    if not isinstance(value,dict) or 'chunks' not in value or 'size' not in value:return raw
    if (type(value['size']) is not int or not 0<=value['size']<=maximum or not isinstance(value['chunks'],list) or len(value['chunks'])>4096):raise ValueError('static chunk manifest rejected')
    output=bytearray()
    for chunk in value['chunks']:
        part=get(chunk)
        if len(output)+len(part)>value['size']:raise ValueError('static content exceeds declared size')
        output.extend(part)
    if len(output)!=value['size']:raise ValueError('static content truncated')
    return bytes(output)


class _CSInline(_CSParser):
    def __init__(self):super().__init__(convert_charrefs=False);self.script=False;self.parts=[];self.hashes=set();self.handlers=set()
    def handle_starttag(self,tag,attrs):
        if tag=='script':self.script=True;self.parts=[]
        for key,value in attrs:
            if key.lower().startswith('on') and value:self.handlers.add(self.digest(value))
    def handle_endtag(self,tag):
        if tag=='script' and self.script:
            if self.parts:self.hashes.add(self.digest(''.join(self.parts)))
            self.script=False
    def handle_data(self,data):
        if self.script:self.parts.append(data)
    def digest(self,value):return "'sha256-"+_cs_b64.b64encode(_cs_hash.sha256(value.replace('\r\n','\n').replace('\r','\n').encode()).digest()).decode()+"'"


def cs_headers(path,content,*,isolated=False,wasm=False):
    kind,encoding=_cs_mime.guess_type(path)
    kind={'.mjs':'text/javascript','.wasm':'application/wasm','.webmanifest':'application/manifest+json'}.get('.'+path.rsplit('.',1)[-1],kind) or 'application/octet-stream'
    script=["'self'"];parser=_CSInline()
    if kind in {'text/html','application/xhtml+xml'}:
        parser.feed(content.decode('utf-8'));script.extend(sorted(parser.hashes))
        if parser.handlers:script.extend(["'unsafe-hashes'",*sorted(parser.handlers)])
    if wasm:script.append("'wasm-unsafe-eval'")
    # Opaque origin on a shared portal; origin-preserving sandbox only on an
    # independently routed static-only origin, never selected by public input.
    sandbox='sandbox allow-scripts'+(' allow-same-origin' if isolated else '')
    policy=sandbox+"; default-src 'none'; script-src "+' '.join(script)+"; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; media-src 'self' blob:; connect-src 'self'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    headers={'Content-Type':kind+('; charset=utf-8' if kind.startswith('text/') or kind in {'application/javascript','application/json'} else ''),
        'Content-Security-Policy':policy,'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
        'Permissions-Policy':'camera=(), microphone=(), geolocation=(), browsing-topics=()',
        'Access-Control-Allow-Origin':'*','Cross-Origin-Resource-Policy':'cross-origin','X-DNS-Prefetch-Control':'off',
        'ETag':'"'+_cs_hash.sha256(content).hexdigest()+'"','Cache-Control':'public, max-age=60, must-revalidate'}
    if encoding=='gzip':headers['Content-Encoding']='gzip'
    return headers

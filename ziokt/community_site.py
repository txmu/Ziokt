"""Deterministic portable community websites built from signed current versions."""
import html
import io
import os
from pathlib import Path
import zipfile

from .community import content_id
from .protocol import ProtocolError, encoded, identifier

STYLE = '''body{font:17px/1.65 system-ui,sans-serif;max-width:900px;margin:auto;padding:24px;color:#172b3a;background:#f6f8fa}a{color:#006c67}article{background:white;padding:24px;margin:16px 0;border:1px solid #c5cfd6;border-radius:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}small{overflow-wrap:anywhere}nav{display:flex;flex-wrap:wrap;gap:16px}@media(prefers-color-scheme:dark){body{background:#101b24;color:#eef5f8}article{background:#172b38;border-color:#476170}a{color:#72d2c2}}'''


def page(title, body):
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'self\'; base-uri \'none\'; form-action \'none\'">'
        '<title>'+html.escape(title)+'</title><link rel="stylesheet" href="style.css"></head><body>'+body+'</body></html>').encode()


def build_site(community, title, *, domains=('wiki', 'forum'), anonymous=False):
    if not isinstance(title, str) or not 1 <= len(title) <= 128 or not isinstance(domains, (tuple, list)) or not domains or any(d not in {'wiki', 'forum'} for d in domains):
        raise ProtocolError('INVALID_SITE', 'bounded title and explicit public document domains required')
    files = {'style.css': STYLE.encode()}; sections = []
    for domain in sorted(set(domains)):
        state = community.view(domain); heads = set(state['heads']); links = []
        for event in state['events']:
            if event['id'] not in heads or event['deleted']: continue
            name = domain+'-'+event['key']+'-'+event['id'][7:19]+'.html'
            body = event['body']; heading = body['title']
            conflict = '<p>此内容存在并发版本；全部当前版本均保留。</p>' if event['key'] in state['conflicts'] else ''
            author_label = '匿名成员' if anonymous else event['author']
            id_label = event['id'][:19] if anonymous else event['id']
            files[name] = page(heading, '<nav><a href="index.html">返回社区</a></nav><article><h1>'+html.escape(heading)+
                '</h1>'+conflict+'<pre>'+html.escape(body['text'])+'</pre><small>作者 '+html.escape(author_label)+
                ' · 记录 '+html.escape(id_label)+'</small></article>')
            links.append('<li><a href="'+name+'">'+html.escape(heading)+'</a></li>')
        sections.append('<section><h2>'+html.escape(domain)+'</h2><ul>'+''.join(links)+'</ul></section>')
    files['index.html'] = page(title, '<h1>'+html.escape(title)+'</h1><p>可携带的社区文档与讨论副本</p>'+''.join(sections))
    manifest = {'schema': 'ziokt.site.v1', 'community_id': community.community_id,
                'policy': community.policy_id, 'anonymous': bool(anonymous), 'files': {name: content_id(data) for name, data in sorted(files.items())}}
    files['site-manifest.json'] = encoded(manifest)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            item = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            archive.writestr(item, data)
    return output.getvalue(), manifest


def publish_site(community, private, name, title, *, anonymous=False):
    identifier(name, 'website name')
    if len(name) > 59: raise ProtocolError('INVALID_SITE', 'website name must fit the signed file namespace')
    from .security import sign
    public = sign({}, private, 'test')['public_key']
    community._member(public, 'files'); community._member(public, 'names')
    with community.lock:
        community._current()
        archive, manifest = build_site(community, title, anonymous=anonymous)
        materials = community.put_file(archive)
        event = community.publish(private, 'files', 'site-'+name, {'name': name+'.zip', **materials})
        reference = 'ziokt://'+community.community_id+'/files/site-'+name
        binding = community.publish(private, 'names', name, {'target': reference})
        return {'materials': materials, 'manifest': manifest, 'file_event': event, 'name_event': binding,
                'reference': reference, 'runtime_ready': False, 'plaintext_publication_automatic': False}


def list_sites(community):
    state = community.view('files')
    heads = set(state['heads'])
    sites = []
    for event in state['events']:
        if event['id'] not in heads or event['deleted']:
            continue
        if event['key'].startswith('site-'):
            site_name = event['key'][5:]
            body = event['body']
            sites.append({
                'name': site_name,
                'key': event['key'],
                'author': event['author'],
                'event_id': event['id'],
                'size': body.get('size', 0),
                'digest': body.get('digest', '')
            })
    return sorted(sites, key=lambda s: s['name'])


def load_site_file(community, name, subpath='index.html'):
    identifier(name, 'website name')
    subpath_str = (subpath or 'index.html').strip()
    if not subpath_str or subpath_str == '/':
        subpath_str = 'index.html'
    subpath_str = subpath_str.lstrip('/')
    norm = os.path.normpath(subpath_str).replace('\\', '/')
    if norm.startswith('../') or norm == '..' or norm.startswith('/'):
        raise ProtocolError('INVALID_SITE', 'invalid subpath for site file')
    target_key = 'site-' + name
    state = community.view('files', target_key)
    heads = set(state['heads'])
    active = [e for e in state['events'] if e['id'] in heads and not e['deleted']]
    if not active:
        raise ProtocolError('NOT_FOUND', f'site {name} not found')
    event = active[-1]
    archive_bytes = community.get_file(event['body'])
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        try:
            content = archive.read(norm)
        except KeyError:
            raise ProtocolError('NOT_FOUND', f'file {norm} not found in site {name}')

    ext = Path(norm).suffix.lower()
    content_types = {
        '.html': 'text/html; charset=utf-8',
        '.css': 'text/css; charset=utf-8',
        '.js': 'application/javascript; charset=utf-8',
        '.json': 'application/json; charset=utf-8',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.svg': 'image/svg+xml',
        '.txt': 'text/plain; charset=utf-8',
        '.ico': 'image/x-icon',
        '.woff2': 'font/woff2',
        '.woff': 'font/woff',
    }
    content_type = content_types.get(ext, 'application/octet-stream')
    return {
        'content': content,
        'content_type': content_type,
        'path': norm,
        'size': len(content),
        'site': name,
        'author': event['author']
    }

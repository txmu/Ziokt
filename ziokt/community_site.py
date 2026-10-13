"""Deterministic portable community websites built from signed current versions."""
import html
import io
import zipfile

from .community import content_id
from .protocol import ProtocolError, encoded, identifier

STYLE = '''body{font:17px/1.65 system-ui,sans-serif;max-width:900px;margin:auto;padding:24px;color:#172b3a;background:#f6f8fa}a{color:#006c67}article{background:white;padding:24px;margin:16px 0;border:1px solid #c5cfd6;border-radius:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}small{overflow-wrap:anywhere}nav{display:flex;flex-wrap:wrap;gap:16px}@media(prefers-color-scheme:dark){body{background:#101b24;color:#eef5f8}article{background:#172b38;border-color:#476170}a{color:#72d2c2}}'''


def page(title, body):
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'self\'; base-uri \'none\'; form-action \'none\'">'
        '<title>'+html.escape(title)+'</title><link rel="stylesheet" href="style.css"></head><body>'+body+'</body></html>').encode()


def build_site(community, title, *, domains=('wiki', 'forum')):
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
            files[name] = page(heading, '<nav><a href="index.html">返回社区</a></nav><article><h1>'+html.escape(heading)+
                '</h1>'+conflict+'<pre>'+html.escape(body['text'])+'</pre><small>作者 '+html.escape(event['author'])+
                ' · 记录 '+html.escape(event['id'])+'</small></article>')
            links.append('<li><a href="'+name+'">'+html.escape(heading)+'</a></li>')
        sections.append('<section><h2>'+html.escape(domain)+'</h2><ul>'+''.join(links)+'</ul></section>')
    files['index.html'] = page(title, '<h1>'+html.escape(title)+'</h1><p>可携带的社区文档与讨论副本</p>'+''.join(sections))
    manifest = {'schema': 'ziokt.site.v1', 'community_id': community.community_id,
                'policy': community.policy_id, 'files': {name: content_id(data) for name, data in sorted(files.items())}}
    files['site-manifest.json'] = encoded(manifest)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            item = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            archive.writestr(item, data)
    return output.getvalue(), manifest


def publish_site(community, private, name, title):
    identifier(name, 'website name')
    if len(name) > 59: raise ProtocolError('INVALID_SITE', 'website name must fit the signed file namespace')
    from .security import sign
    public = sign({}, private, 'test')['public_key']
    community._member(public, 'files'); community._member(public, 'names')
    with community.lock:
        community._current()
        archive, manifest = build_site(community, title)
        materials = community.put_file(archive)
        event = community.publish(private, 'files', 'site-'+name, {'name': name+'.zip', **materials})
        reference = 'ziokt://'+community.community_id+'/files/site-'+name
        binding = community.publish(private, 'names', name, {'target': reference})
        return {'materials': materials, 'manifest': manifest, 'file_event': event, 'name_event': binding,
                'reference': reference, 'runtime_ready': False, 'plaintext_publication_automatic': False}

#!/usr/bin/env python3
"""Verify released installers and add them to the existing GUI download page.

Does not fetch arbitrary URLs, extract archives, replace GUI installers or reload
services. The caller obtains the release files through the existing GitHub CLI.
"""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

PACKAGES = {
    'chromium': 'ziokt-companion-chromium.zip',
    'firefox': 'ziokt-companion-firefox.xpi',
    'thunderbird': 'ziokt-companion-thunderbird.xpi',
}
START = '<!-- BEGIN ZIOKT WEBEXTENSION DOWNLOADS -->'
END = '<!-- END ZIOKT WEBEXTENSION DOWNLOADS -->'


def atomic_write(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix='.'+path.name+'-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def verified(source, commit):
    if not re.fullmatch('[0-9a-f]{40}', commit):raise ValueError('exact source commit required')
    source=Path(source)
    names=set(PACKAGES.values())|{'build-source.json'}
    checksums={}
    for line in (source/'SHA256SUMS').read_text().splitlines():
        match=re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)',line)
        if not match or match[2] not in names or match[2] in checksums:raise ValueError('invalid checksum list')
        checksums[match[2]]=match[1]
    if set(checksums)!=names:raise ValueError('incomplete checksum list')
    for name,digest in checksums.items():
        path=source/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size>4*1024*1024:raise ValueError('installer file boundary')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('installer digest mismatch')
    manifest=json.loads((source/'build-source.json').read_bytes())
    if manifest.get('schema')!='ziokt.webextensions.build.v1' or manifest.get('source_commit')!=commit or manifest.get('source_dirty') is not False or manifest.get('store_signed') is not False:
        raise ValueError('release provenance mismatch')
    records=manifest.get('packages',[])
    if len(records)!=3 or {r.get('target') for r in records}!=set(PACKAGES):raise ValueError('installer target set')
    for record in records:
        if record.get('file')!=PACKAGES[record['target']] or record.get('sha256')!=checksums[record['file']] or record.get('store_signed') is not False:raise ValueError('installer manifest mismatch')
    return manifest,checksums


def install(source, destination, commit):
    source=Path(source);destination=Path(destination)
    manifest,checksums=verified(source,commit)
    index=destination/'index.html'
    if destination.is_symlink() or index.is_symlink() or not index.is_file():raise ValueError('existing GUI downloads page required')
    page=index.read_text()
    if page.count(START)!=page.count(END) or page.count(START)>1:raise ValueError('ambiguous download section')
    directory=destination/'extensions'
    if directory.is_symlink():raise ValueError('download symlink')
    directory.mkdir(exist_ok=True)
    release=directory/commit
    if release.is_symlink():raise ValueError('release symlink')
    files=set(checksums)|{'SHA256SUMS'}
    if release.exists():
        for name in files:
            path=release/name
            if path.is_symlink() or not path.is_file() or path.read_bytes()!=(source/name).read_bytes():raise ValueError('immutable release conflict')
    else:
        with tempfile.TemporaryDirectory(prefix='.extensions-',dir=destination) as temporary:
            staged=Path(temporary)/'release';staged.mkdir(mode=0o755)
            for name in sorted(files):
                shutil.copyfile(source/name,staged/name);os.chmod(staged/name,0o644)
            os.rename(staged,release)
    prefix='extensions/'+commit+'/'
    items=[]
    for target,name in PACKAGES.items():
        items.append({'target':target,'file':name,'url':prefix+name,'sha256':checksums[name],'version':manifest['versions'][target],'store_signed':False})
    catalogue={'schema':'ziokt.webextensions.downloads.v1','source_commit':commit,'packages':items,'checksums':prefix+'SHA256SUMS','provenance':prefix+'build-source.json'}
    atomic_write(destination/'extensions.json',(json.dumps(catalogue,ensure_ascii=False,indent=2)+'\n').encode())
    links=''.join('<li>'+html.escape(item['target'].title())+' — <a download href="'+item['url']+'">'+item['file']+'</a><br><code>SHA-256 '+item['sha256']+'</code></li>' for item in items)
    section=START+'\n<section aria-labelledby="extensions-title"><h2 id="extensions-title">浏览器扩展 / Browser extensions</h2><p>未签名开发包 / Unsigned development packages · '+commit[:12]+'</p><ul>'+links+'</ul><p><a href="'+prefix+'SHA256SUMS">SHA-256 校验清单</a> · <a href="'+prefix+'build-source.json">构建来源</a> · <a href="extensions.json">扩展机器可读清单</a></p><p>Chromium：解压 ZIP，在 chrome://extensions 开启开发者模式并加载目录。Firefox：在 about:debugging 临时加载开发扩展；本 XPI 未经 Mozilla 签名，不保证正式版永久安装。Thunderbird：在附加组件管理中选择 XPI，具体兼容性受版本及客户端策略限制。</p><p>Chromium: unzip and load unpacked in Developer mode. Firefox: temporary installation through about:debugging; unsigned, no permanent consumer installation claim. Thunderbird: install XPI through Add-ons, subject to version compatibility. Android 真机尚未验收；不支持扩展的设备使用 <a href="https://read.ziokt.com/">Content Web</a>。</p></section>\n'+END
    if START in page:
        page=re.sub(re.escape(START)+r'[\s\S]*?'+re.escape(END),lambda _:section,page)
    else:
        match=re.search(r'</(?:body|html)>',page,re.I)
        point=match.start() if match else len(page)
        page=page[:point]+section+page[point:]
    atomic_write(index,page.encode())
    return catalogue


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--source-commit',required=True)
    args=parser.parse_args()
    print(json.dumps(install(args.source,args.destination,args.source_commit),ensure_ascii=False))

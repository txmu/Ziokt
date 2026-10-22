#!/usr/bin/env python3
"""Install verified Windows CI files alongside existing GUI downloads, preserving them."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import shutil


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def install(source,root):
    source=source.resolve();root=root.resolve()
    manifest=json.loads((source/'build-source.json').read_text(encoding='utf-8-sig'))
    commit=manifest.get('source_commit','')
    if not re.fullmatch('[0-9a-f]{40}',commit) or manifest.get('schema')!='ziokt.effort.windows-build.v1' or manifest.get('signing')!='unsigned-development':raise ValueError('exact unsigned build provenance required')
    checks={}
    for line in (source/'SHA256SUMS').read_text(encoding='utf-8-sig').splitlines():
        match=re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)',line)
        if not match or match[2] in checks:raise ValueError('bounded unique checksum entries required')
        name=match[2];path=source/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size>512*1024*1024 or digest(path)!=match[1]:raise ValueError('CI file hash mismatch: '+name)
        checks[name]=match[1]
    required={'ziokt-effort-windows-x64-unsigned.exe','ziokt-effort-windows-x64-unsigned.msi','build-source.json','README.md','self-test.json','ui-test.json'}
    if not required<=checks.keys() or json.loads((source/'self-test.json').read_text()).get('success') is not True or json.loads((source/'ui-test.json').read_text()).get('success') is not True:raise ValueError('actual executable evidence and installers required')
    index=root/'index.html'
    if not index.is_file():raise ValueError('existing GUI downloads index required')
    target=root/'effort'/commit;target.mkdir(parents=True,exist_ok=True)
    for name in sorted(set(checks)|{'SHA256SUMS'}):
        destination=target/name
        if destination.exists() and digest(destination)!=digest(source/name):raise ValueError('immutable download version changed')
        if not destination.exists():
            temp=destination.with_suffix(destination.suffix+'.new');shutil.copyfile(source/name,temp);temp.chmod(0o644);temp.replace(destination)
    prefix='effort/'+commit+'/'
    body='<section aria-labelledby="effort-title"><h2 id="effort-title">Windows 助力客户端</h2><p>Windows 10/11 x64 · 未签名开发包 · '+commit[:12]+'</p><ul>'
    for name in sorted(required & {n for n in checks if n.endswith(('.msi','.exe'))}):body+='<li><a href="'+prefix+name+'">'+html.escape(name)+'</a><br><code>SHA-256 '+checks[name]+'</code></li>'
    body+='</ul><p>MSI 安装到当前用户；EXE 可直接运行。自启需要用户勾选，断网暂停、联网恢复。需要微软 WebView2 Runtime。<a href="'+prefix+'README.md">安装说明</a> · <a href="'+prefix+'SHA256SUMS">校验清单</a> · <a href="'+prefix+'build-source.json">构建来源</a> · <a href="https://fendou.ziokt.com/">打开奋斗页</a></p></section>'
    begin='<!-- BEGIN ZIOKT EFFORT DOWNLOADS -->';end='<!-- END ZIOKT EFFORT DOWNLOADS -->';section=begin+body+end
    original=index.read_text()
    if begin in original:
        before,rest=original.split(begin,1);_,after=rest.split(end,1);updated=before+section+after
    else:
        position=original.lower().rfind('</html>');updated=original[:position]+section+original[position:] if position>=0 else original+section
    temp=index.with_suffix('.html.new');temp.write_text(updated);temp.chmod(0o644);temp.replace(index)
    receipt={'schema':'ziokt.effort.downloads.v1','source_commit':commit,'ci_run_id':manifest.get('run_id'),'files':checks,'base_url':'https://app.ziokt.com/downloads/'+prefix,'signing':'unsigned-development'}
    temp=root/'effort.json.new';temp.write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n');temp.chmod(0o644);temp.replace(root/'effort.json')
    return receipt

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--downloads-root',type=Path,required=True);args=parser.parse_args();print(json.dumps(install(args.source,args.downloads_root)))

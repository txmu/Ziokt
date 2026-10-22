#!/usr/bin/env python3
"""Publish the small signed CI APK without altering existing Windows/GUI installers."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def install(source,root):
    source=source.resolve();root=root.resolve();manifest=json.loads((source/'build-source.json').read_text());commit=manifest.get('source_commit','')
    if manifest.get('schema')!='ziokt.effort.android-build.v1' or not re.fullmatch('[0-9a-f]{40}',commit) or manifest.get('min_sdk')!=28:raise ValueError('Android 9 source provenance required')
    checks={}
    for line in (source/'SHA256SUMS').read_text().splitlines():
        match=re.fullmatch(r'([a-f0-9]{64})  ([A-Za-z0-9_.-]+)',line)
        if not match or match[2] in checks:raise ValueError('exact unique checksum entries required')
        path=source/match[2]
        if path.is_symlink() or not path.is_file() or path.stat().st_size>1024*1024 or sha(path)!=match[1]:raise ValueError('Android delivery hash/budget mismatch')
        checks[match[2]]=match[1]
    apk='ziokt-effort-android-universal.apk'
    if not {apk,'build-source.json','signature.txt','package-badging.txt'}<=checks.keys():raise ValueError('APK and actual CI signature/badging evidence required')
    if manifest.get('apk_bytes')!=(source/apk).stat().st_size:raise ValueError('APK size differs from CI')
    with zipfile.ZipFile(source/apk) as z:
        if any(name.startswith('lib/') for name in z.namelist()):raise ValueError('unexpected bundled native runtime')
    if 'Verified using v2 scheme (APK Signature Scheme v2): true' not in (source/'signature.txt').read_text():raise ValueError('actual v2 signature evidence required')
    index=root/'index.html'
    if not index.is_file():raise ValueError('existing GUI downloads index required')
    dest=root/'effort-android'/commit;dest.mkdir(parents=True,exist_ok=True)
    for name in sorted(set(checks)|{'SHA256SUMS'}):
        target=dest/name
        if target.exists() and sha(target)!=sha(source/name):raise ValueError('immutable Android download version conflict')
        if not target.exists():temp=target.with_suffix(target.suffix+'.new');shutil.copyfile(source/name,temp);temp.chmod(0o644);temp.replace(target)
    prefix='effort-android/'+commit+'/'
    body='<section aria-labelledby="effort-android-title"><h2 id="effort-android-title">Android 轻量助力客户端</h2><p><a href="'+prefix+apk+'">Android 9+ 通用 APK（ARM 32/64 位）</a> · '+str(manifest['apk_bytes'])+' 字节 · 开发证书签名</p><p>单工作线程，不捆绑浏览器或运行时。默认不自启；启用后有可停止的常驻通知。断网暂停、恢复后继续，不进行网络连通性轮询。低配设备内存和实体 ARM 设备以实际验收记录为准。</p><p><code>SHA-256 '+checks[apk]+'</code></p><p><a href="'+prefix+'SHA256SUMS">校验清单</a> · <a href="'+prefix+'build-source.json">构建来源</a> · <a href="'+prefix+'signature.txt">签名信息</a> · <a href="https://github.com/txmu/Ziokt/actions/runs/'+str(manifest['run_id'])+'">实际 CI 与设备验证状态</a></p></section>'
    begin='<!-- BEGIN ZIOKT ANDROID EFFORT DOWNLOADS -->';end='<!-- END ZIOKT ANDROID EFFORT DOWNLOADS -->';section=begin+body+end;current=index.read_text()
    if begin in current:before,rest=current.split(begin,1);_,after=rest.split(end,1);updated=before+section+after
    else:
        point=current.lower().rfind('</html>');updated=current[:point]+section+current[point:] if point>=0 else current+section
    temp=index.with_suffix('.html.new');temp.write_text(updated);temp.chmod(0o644);temp.replace(index)
    receipt={'schema':'ziokt.effort.android-downloads.v1','source_commit':commit,'ci_run_id':manifest['run_id'],'apk_bytes':manifest['apk_bytes'],'apk_sha256':checks[apk],'url':'https://app.ziokt.com/downloads/'+prefix+apk,'physical_arm_device':'not_assessed'}
    temp=root/'effort-android.json.new';temp.write_text(json.dumps(receipt,indent=2)+'\n');temp.chmod(0o644);temp.replace(root/'effort-android.json');return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--downloads-root',type=Path,required=True);a=p.parse_args();print(json.dumps(install(a.source,a.downloads_root)))

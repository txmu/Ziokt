#!/usr/bin/env python3
"""Publish only successful GUI CI installers, with source/run provenance and SHA-256."""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import quote
import zipfile

PLATFORMS={'ziokt-desktop-linux':'Linux','ziokt-desktop-windows':'Windows','ziokt-mobile-packages':'Android','ziokt-desktop-macos-aarch64-apple-darwin':'macOS Apple Silicon','ziokt-desktop-macos-x86_64-apple-darwin':'macOS Intel','ziokt-web-pwa':'Web PWA assets'}


def validate(path):
    suffix=path.suffix.lower();size=path.stat().st_size
    if not 1024<=size<=1024**3:raise ValueError('Installer size invalid: '+path.name)
    with path.open('rb') as f:
        magic=f.read(8)
        if suffix=='.dmg':f.seek(-512,2);magic=f.read(4)
    if suffix=='.apk':
        with zipfile.ZipFile(path) as z:
            if not {'AndroidManifest.xml','classes.dex'}<=set(z.namelist()):raise ValueError('Not an Android application')
    elif suffix=='.exe' and magic[:2]!=b'MZ':raise ValueError('Not a Windows PE executable')
    elif suffix=='.msi' and magic!=bytes.fromhex('d0cf11e0a1b11ae1'):raise ValueError('Not a Windows MSI')
    elif suffix=='.deb' and magic!=b'!<arch>\n':raise ValueError('Not a Debian package')
    elif suffix=='.appimage' and magic[:4]!=b'\x7fELF':raise ValueError('Not a Linux executable')
    elif suffix=='.dmg' and magic!=b'koly':raise ValueError('Not a DMG image')
    elif path.name.endswith('.tar.gz') and magic[:2]!=b'\x1f\x8b':raise ValueError('Not a compressed web archive')
    return hashlib.file_digest(path.open('rb'),'sha256').hexdigest()


def publish(run_id,root):
    run=json.loads(subprocess.check_output(['gh','run','view',str(run_id),'--json','conclusion,headSha,url,name'],text=True))
    if run['conclusion']!='success' or run['name']!='Ziokt Unified Graphical Client CI & Release Artifacts':raise ValueError('Successful GUI CI run required')
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True);version=run['headSha'][:12];records=[]
    with tempfile.TemporaryDirectory(prefix='ziokt-gui-release-') as temporary:
        stage=Path(temporary)/'artifacts';subprocess.run(['gh','run','download',str(run_id),'--dir',str(stage)],check=True)
        target=root/version;target.mkdir(exist_ok=True)
        for artifact,platform in PLATFORMS.items():
            area=stage/artifact
            for file in sorted(area.rglob('*')) if area.exists() else []:
                if not file.is_file() or file.is_symlink():continue
                if file.suffix.lower() not in {'.apk','.exe','.msi','.deb','.appimage','.dmg'} and not (artifact=='ziokt-web-pwa' and file.name.endswith('.tar.gz')):continue
                digest=validate(file);name=artifact+'-'+file.name;dest=target/name
                if dest.exists() and hashlib.file_digest(dest.open('rb'),'sha256').hexdigest()!=digest:raise ValueError('Immutable release collision')
                shutil.copyfile(file,dest);dest.chmod(0o644)
                records.append({'platform':platform,'file':version+'/'+name,'bytes':dest.stat().st_size,'sha256':digest,'source_revision':run['headSha'],'ci_run':run['url']})
        if not records:raise ValueError('No verified platform artifacts')
        platforms={r['platform'] for r in records}
        for required in ('Linux','Windows','Android','macOS Apple Silicon','macOS Intel'):
            if required not in platforms:raise ValueError('Required platform installer missing: '+required)
        manifest={'schema':'ziokt.gui-release.v1','revision':run['headSha'],'ci':run['url'],'artifacts':records,'harmonyos':'No signed HAP: SDK/signing/device verification required','macos_signing':'ad-hoc; not Apple notarized'}
        (root/'.releases.json.new').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');os.replace(root/'.releases.json.new',root/'releases.json')
        links=''.join('<li>'+html.escape(r['platform'])+' — <a href="'+quote(r['file'])+'">'+html.escape(Path(r['file']).name)+'</a> ('+str(r['bytes'])+' bytes)<br><code>SHA-256 '+r['sha256']+'</code></li>' for r in records)
        page='<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Ziokt GUI 下载</title><style>body{max-width:960px;margin:24px auto;padding:16px;font:16px sans-serif;overflow-wrap:anywhere}li{margin:18px 0}code{font-size:12px}</style><h1>Ziokt GUI 1.1.0</h1><p>CI 实际构建与验收产物，源修订 '+run['headSha']+'</p><p><a href="/">打开 Web 应用</a> · <a href="releases.json">机器可读清单</a> · <a href="'+run['url']+'">CI 验收</a></p><ul>'+links+'</ul><p>macOS 使用 ad-hoc 签名，尚未 Apple 公证。HarmonyOS 目前没有已签名并通过设备验收的 HAP，不把源码档案当作安装包。</p></html>'
        (root/'.index.html.new').write_text(page);os.replace(root/'.index.html.new',root/'index.html')
    return {'revision':run['headSha'],'published':len(records),'root':str(root)}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-id',type=int,required=True);p.add_argument('--root',type=Path,required=True);a=p.parse_args();print(json.dumps(publish(a.run_id,a.root)))

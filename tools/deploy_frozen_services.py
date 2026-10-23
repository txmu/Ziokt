#!/usr/bin/env python3
"""Freeze a committed release and switch reviewed Python services together.

Backs up SQLite/configuration, preserves native consensus/keys and restores unit
overrides if activation fails. Does not send messages or native transactions.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
SERVICES=('ziokt-gateway','ziokt-mcp','ziokt-telegram-bot','ziokt-content')


def run(*args,**kwargs):return subprocess.run(list(args),check=True,**kwargs)


def release_hashes(release):
    return {str(path.relative_to(release)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(release.rglob('*')) if path.is_file() and path.relative_to(release).as_posix()!='RELEASE_SHA256.json'}


def stage(root,revision):
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():raise ValueError('committed clean source required')
    exact=subprocess.check_output(['git','rev-parse',revision+'^{commit}'],cwd=ROOT,text=True).strip()
    release=root/'releases'/exact
    release.parent.mkdir(parents=True,exist_ok=True)
    if release.exists():
        if json.loads((release/'DEPLOYED_BUILD.json').read_text())['source_commit']!=exact:raise ValueError('release identity conflict')
        if json.loads((release/'RELEASE_SHA256.json').read_text())!=release_hashes(release):raise ValueError('frozen release file hashes changed')
        return release,exact
    with tempfile.TemporaryDirectory(prefix='.source-',dir=release.parent) as directory:
        archive=Path(directory)/'source.tar';tree=Path(directory)/'tree';tree.mkdir()
        run('git','archive','--format=tar','--output',str(archive),exact,cwd=ROOT)
        with tarfile.open(archive) as source:
            if any(not (item.isfile() or item.isdir()) for item in source.getmembers()):raise ValueError('release archive links are not allowed')
            source.extractall(tree,filter='data')
        (tree/'DEPLOYED_BUILD.json').write_text(json.dumps({'schema':'ziokt.frozen-source.v1','source_commit':exact},sort_keys=True)+'\n')
        gui=tree/'gateway/gui'
        if (gui/'app.js').is_file():
            (gui/'ziokt-build.json').write_text(json.dumps({'schema':'ziokt.gui-build.v1','source_commit':exact,'app_sha256':hashlib.sha256((gui/'app.js').read_bytes()).hexdigest()},sort_keys=True)+'\n')
        (tree/'RELEASE_SHA256.json').write_text(json.dumps(release_hashes(tree),sort_keys=True)+'\n')
        for path in tree.rglob('*'):
            if path.is_file():path.chmod(0o555 if path.stat().st_mode & 0o111 else 0o444)
        for path in sorted((p for p in tree.rglob('*') if p.is_dir()),reverse=True):path.chmod(0o555)
        os.rename(tree,release)
        release.chmod(0o555)
    return release,exact


def backup_database(source,destination):
    if not source.is_file() or source.is_symlink():raise ValueError('existing regular database required')
    deadline=time.monotonic()+30
    def progress(*args):
        if time.monotonic()>deadline:raise TimeoutError('SQLite backup deadline')
    with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as original,sqlite3.connect(destination) as backup:
        original.backup(backup,pages=128,progress=progress,sleep=.01)
    destination.chmod(0o600)


def reload_caddy(root,caddy):
    # Caddy >=2.11 supports a graceful file reload signal even with the admin API disabled.
    import re
    text=caddy.read_text()
    if re.search(r'^\s*admin\s+off\s*$',text,re.M):
        version=subprocess.check_output([str(root/'bin/caddy'),'version'],text=True)
        match=re.match(r'v?(\d+)\.(\d+)\.',version)
        if not match or tuple(map(int,match.groups()))<(2,11):raise ValueError('admin-off graceful reload requires Caddy >=2.11')
        command=subprocess.check_output(['systemctl','show','ziokt-https','--property=ExecStart','--value'],text=True)
        if '--resume' in command or str(caddy) not in command:raise ValueError('reviewed file-based Caddy run required')
        run('sudo','-n','systemctl','kill','--kill-whom=main','--signal=USR1','ziokt-https')
    else:run(str(root/'bin/caddy'),'reload','--config',str(caddy),'--adapter','caddyfile',capture_output=True)


def activate(root,release,revision):
    timestamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=root/'private-bootstrap-backup'/('frozen-'+revision[:12]+'-'+timestamp);backup.mkdir(mode=0o700,parents=True)
    mcp=json.loads((root/'mcp/mcp.json').read_text())
    content_root=Path(mcp['content_fabric']['root'])
    for name,path in [('mcp',Path(mcp['state'])/'mcp.db'),('content',content_root/'content.sqlite')]:backup_database(path,backup/(name+'.sqlite'))
    key_map={}
    keys=[content_root/'node.key',*content_root.glob('accounts/*/vault.key')]
    for index,path in enumerate(keys):
        if path.is_file():
            name='content-key-'+str(index);shutil.copyfile(path,backup/name);(backup/name).chmod(0o600);key_map[name]=str(path)
    (backup/'content-key-map.json').write_text(json.dumps(key_map,sort_keys=True)+'\n');(backup/'content-key-map.json').chmod(0o600)
    for name,path in [('mcp-config.json',root/'mcp/mcp.json'),('gateway-config.json',root/'config/gateway.json')]:
        shutil.copyfile(path,backup/name);(backup/name).chmod(0o600)
    caddy=root/'config/Caddyfile';old_caddy=caddy.read_bytes();(backup/'Caddyfile').write_bytes(old_caddy)
    old_root='root * /home/admin/Ziokt/gateway/gui'
    text=old_caddy.decode()
    if old_root in text:
        if text.count(old_root)!=1:raise ValueError('reviewed GUI root must appear exactly once')
        text=text.replace(old_root,'root * '+str(release/'gateway/gui'))
    else:
        import re
        text,count=re.subn(r'root \* '+re.escape(str(root))+r'/releases/[a-f0-9]{40}/gateway/gui','root * '+str(release/'gateway/gui'),text)
        if count!=1:raise ValueError('reviewed GUI root not found exactly once')
    candidate=backup/'Caddyfile.candidate';candidate.write_text(text)
    run(str(root/'bin/caddy'),'validate','--config',str(candidate),'--adapter','caddyfile',capture_output=True)
    units={}
    for service in SERVICES:
        path=Path('/etc/systemd/system')/(service+'.service.d')/'70-ziokt-release.conf'
        units[service]=(path,path.read_bytes() if path.exists() else None)
        if units[service][1] is not None:(backup/(service+'.override')).write_bytes(units[service][1])
    try:
        for service,(path,_) in units.items():
            dropin=backup/(service+'.new')
            content='[Service]\nWorkingDirectory='+str(release)+'\nEnvironment=PYTHONDONTWRITEBYTECODE=1\n'
            if service=='ziokt-content':content+='MemoryHigh=384M\nMemoryMax=512M\nCPUQuota=100%\n'
            dropin.write_text(content)
            run('sudo','-n','install','-d',str(path.parent))
            run('sudo','-n','install','-m','0644',str(dropin),str(path))
        caddy.write_text(text);caddy.chmod(0o600)
        run('sudo','-n','systemctl','daemon-reload')
        run('sudo','-n','systemctl','restart',*SERVICES)
        reload_caddy(root,caddy)
        deadline=time.monotonic()+30
        while True:
            try:
                with urllib.request.urlopen('http://127.0.0.1:8185/api/gateway/status',timeout=3) as response:status=json.load(response)
                if status.get('build',{}).get('source_commit')!=revision:raise ValueError('Gateway release mismatch')
                with urllib.request.urlopen('https://app.ziokt.com/ziokt-build.json',timeout=3) as response:gui_status=json.load(response)
                if gui_status.get('source_commit')!=revision:raise ValueError('public GUI release mismatch')
                break
            except (OSError,ValueError):
                if time.monotonic()>deadline:raise
                time.sleep(.5)
        run('sudo','-n','systemctl','is-active','--quiet',*SERVICES)
    except BaseException:
        caddy.write_bytes(old_caddy);caddy.chmod(0o600)
        for service,(path,previous) in units.items():
            if previous is None and path.exists():run('sudo','-n','rm','--',str(path))
            elif previous is None:continue
            else:
                restore=backup/(service+'.restore');restore.write_bytes(previous)
                run('sudo','-n','install','-m','0644',str(restore),str(path))
        run('sudo','-n','systemctl','daemon-reload')
        run('sudo','-n','systemctl','restart',*SERVICES)
        reload_caddy(root,caddy)
        raise
    receipt={'schema':'ziokt.frozen-deployment.v1','source_commit':revision,'at':timestamp,'services':list(SERVICES),
             'release':str(release),'backup':str(backup),'gateway_build':status['build'],
             'native_entrypoint_digest':status.get('native_entrypoint_digest'),
             'gui_app_sha256':hashlib.sha256((release/'gateway/gui/app.js').read_bytes()).hexdigest(),
             'consensus_changed':False,'native_compilation':False,'telegram_messages_explicitly_requested':False,'telegram_delivery_observation':'not_assessed'}
    receipt_path=root/'config/frozen-deployment-receipt.json';receipt_path.write_text(json.dumps(receipt,indent=2)+'\n');receipt_path.chmod(0o600)
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--revision',default='HEAD');parser.add_argument('--activate',action='store_true')
    args=parser.parse_args();release,revision=stage(args.root.resolve(),args.revision)
    print(json.dumps(activate(args.root.resolve(),release,revision) if args.activate else {'release':str(release),'source_commit':revision,'activated':False}))

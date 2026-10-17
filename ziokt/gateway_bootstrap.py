"""Render default gateway, publish native assets and install explicit services."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
from .gateway import ASSETS, read_token, serve
from .gateway_store import database, Store


def bootstrap(args):
    root=args.root.resolve(); root.mkdir(parents=True,exist_ok=True)
    config_dir=root/'config'; config_dir.mkdir(mode=0o700,exist_ok=True)
    token=config_dir/'admin_token.key'
    if not token.exists():
        fd=os.open(token,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as output: output.write(secrets.token_urlsafe(48)+'\n')
    read_token(token)
    state=args.state_root.resolve()
    network=args.network
    if not re.fullmatch('[a-zA-Z0-9_-]{1,64}',network): raise ValueError('invalid network')
    dht=state/'var/lib/corix/p2p/dht.db'
    forum=state/'var/lib/corix/networks'/network/'forum/forum.db'
    if not dht.is_file() or not forum.is_file(): raise ValueError('initialize native Corium network first')
    config={'schema':'ziokt.gateway.v1','network':network,'state_root':str(state),'corix':str(args.corix.resolve()),
            'objects':str(dht.parent/'objects'),'dht_db':str(dht),'forum_db':str(forum),
            'registry_db':str(config_dir/'registry.db'),'admin_token':str(token),'port':args.port,'peers':args.peer,'corix_digest':'sha256:'+hashlib.sha256(args.corix.read_bytes()).hexdigest()}
    dest=config_dir/'gateway.json'
    if dest.exists():config={**json.loads(dest.read_text()),**config}
    dest.write_text(json.dumps(config,indent=2)+'\n'); dest.chmod(0o600)
    if args.publish: publish(config)
    repo=Path(__file__).resolve().parents[1]
    values={'ROOT':str(root),'REPO':str(repo),'PYTHON':args.python,'USER':getpass.getuser(),'CONFIG':str(dest)}
    for key,value in values.items():
        if not re.fullmatch(r'[A-Za-z0-9_./-]+',value): raise ValueError('unsupported service path')
    template=(ASSETS/'systemd/ziokt-gateway.service.template').read_text()
    for key,value in values.items(): template=template.replace('@'+key+'@',value)
    unit=config_dir/'ziokt-gateway.service'; unit.write_text(template)
    if args.install:
        subprocess.run(['sudo','install','-m','644',str(unit),'/etc/systemd/system/ziokt-gateway.service'],check=True)
        subprocess.run(['sudo','systemctl','daemon-reload'],check=True)
        subprocess.run(['sudo','systemctl','enable','--now','ziokt-gateway.service'],check=True)
        subprocess.run(['sudo','systemctl','restart','ziokt-gateway.service'],check=True)
    return {'config':str(dest),'unit':str(unit),'published':args.publish,'installed':args.install}


def publish(config):
    store=Store(config['objects'],config['dht_db'])
    def file(path, data=None):
        # Existing NNS/DApp readers use v1 fixed manifest objects.
        data=path.read_bytes() if data is None else data; pieces=[store.put(data[i:i+262144]) for i in range(0,len(data),262144)]
        return store.put(json.dumps({'file':path.name,'size':len(data),'chunk_size':262144,'chunks':pieces}).encode())
    portal=file(ASSETS/'default_portal/index.html')
    directory=store.put(json.dumps({'type':'directory_manifest','index':'index.html','files':{'index.html':portal}}).encode())
    source=(ASSETS/'default_dapp/entrypoint.py').read_text().replace('MESSAGES = {}','MESSAGES = '+repr(json.loads((ASSETS/'i18n.json').read_text())))
    entry=file(ASSETS/'default_dapp/entrypoint.py',source.encode())
    dapp=store.put(json.dumps({'type':'dapp_manifest','gateway_app':{'engine':'built-in','entrypoint':entry}}).encode())
    mappings=[('corium',directory),('status',directory)]+[(name,dapp) for name in ('explorer','forum','fileshare','onion','zda','safefs','ufsdcpm','tc16','blockchain','ano','board','chain','chat','dcpm','ecosystem','effort','files','hub','ledger','mcp','nns','nomen','sim','tri','tunnel','ufs','watchat','ziokt')]
    from .gateway import Gateway
    native=Gateway(config)
    records=[]
    with database(config['forum_db'],timeout=10) as db:
        registered={name:target for name,target in db.execute('SELECT domain_name,target_hash FROM nns_records')}
    for name,target in mappings:
        if name not in registered:
            native.native('register',name,target)
        elif registered[name]!=target:records.append({'domain_name':name,'target_hash':target})
    if records:native.native('bind',json.dumps({'records':records},separators=(',',':')))
    # Optimistic local visibility follows successful signed submission. Chain replay
    # reproduces the same updates once consensus includes the pending transaction.
    with database(config['forum_db'],timeout=10) as db:
        for name,target in mappings:
            db.execute('UPDATE nns_records SET target_hash=? WHERE domain_name=?',(target,name))
    return {'portal':directory,'dapp':dapp}


def register(sub):
    gateway=sub.add_parser('gateway',help='native default portal and authenticated streaming gateway')
    actions=gateway.add_subparsers(dest='gateway_action',required=True)
    init=actions.add_parser('bootstrap')
    init.add_argument('--default',action='store_true',help='publish the versioned default assets when --publish is set')
    init.add_argument('--root',type=Path,required=True); init.add_argument('--state-root',type=Path,required=True)
    init.add_argument('--corix',type=Path,required=True);init.add_argument('--network',default='default')
    init.add_argument('--port',type=int,default=8185);init.add_argument('--python',default=__import__('sys').executable)
    init.add_argument('--peer',action='append',default=[]);init.add_argument('--publish',action='store_true');init.add_argument('--install',action='store_true')
    start=actions.add_parser('serve');start.add_argument('--config',type=Path,required=True)
    upload=actions.add_parser('publish-file');upload.add_argument('--config',type=Path,required=True);upload.add_argument('file',type=Path)


def execute(args):
    if args.gateway_action=='bootstrap': return bootstrap(args)
    config=json.loads(args.config.read_text())
    if args.gateway_action=='serve': serve(config); return {}
    with args.file.open('rb') as source:
        digest=Store(config['objects'],config.get('dht_db')).publish(source,args.file.name)
    return {'root':digest,'url':'/stream/'+digest}

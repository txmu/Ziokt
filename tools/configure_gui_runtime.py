#!/usr/bin/env python3
"""Enable the owner-authenticated GUI adapter and empty-by-default native signer trust."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


def write(path,value):
    path=Path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.gui-config-',delete=False) as f:
        temporary=Path(f.name);f.write((json.dumps(value,indent=2)+'\n').encode());f.flush();os.fsync(f.fileno())
    try:temporary.chmod(0o600);os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def configure(root,shadow6):
    root=Path(root);mcp=root/'mcp/mcp.json';gateway=root/'config/gateway.json'
    config=json.loads(mcp.read_text());g=json.loads(gateway.read_text())
    base=root/'mcp/native-admission';base.mkdir(mode=0o700,parents=True,exist_ok=True);base.chmod(0o700)
    for name in ('artifacts','packages'):(base/name).mkdir(mode=0o700,exist_ok=True)
    trust=base/'trusted-signers.json'
    if not trust.exists():write(trust,{'schema_version':1,'signers':{}})
    module=Path(shadow6).resolve()/'Package-Manager/shadow6_pkg.py'
    config['native_package_handoff']={'module':str(module),'module_digest':'sha256:'+hashlib.sha256(module.read_bytes()).hexdigest(),'trust_file':str(trust),'artifact_root':str(base/'artifacts'),'package_root':str(base/'packages'),'native_config':str(root/'config/shadow6-production.json')}
    g['mcp_config']=str(mcp)
    g['gui_origins']=sorted(set(g.get('gui_origins',[]))|{'https://app.ziokt.com','https://cor-web.ziokt.com','https://appassets.ziokt.local','http://tauri.localhost','https://tauri.localhost','tauri://localhost'})
    config['origins']=sorted(set(config.get('origins',[]))|{'https://app.ziokt.com'})
    config['hosts']=sorted(set(config.get('hosts',[]))|{'app.ziokt.com'})
    write(mcp,config);write(gateway,g)
    return {'gui_adapter_configured':True,'native_signers_trusted_by_default':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--shadow6',type=Path,required=True);a=p.parse_args();print(json.dumps(configure(a.root,a.shadow6)))

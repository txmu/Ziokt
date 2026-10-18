#!/usr/bin/env python3
"""Prepare private DNS node bindings; does not publish names or start listeners."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.protocol import secure_read,strict_json,encoded


def write(path,value):
    path=Path(path)
    if path.is_symlink():raise ValueError('configuration symlink denied')
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    import tempfile
    fd,temporary=tempfile.mkstemp(dir=path.parent,prefix='.dns-configuration-')
    try:
        with os.fdopen(fd,'wb') as output:output.write(encoded(value));output.flush();os.fsync(output.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def configure(mcp_path,gateway_path,output,namespace):
    from ziokt.protocol import identifier
    identifier(namespace,'DNS namespace')
    mcp=strict_json(secure_read(mcp_path));gateway=strict_json(secure_read(gateway_path));base=Path(mcp_path).resolve().parent
    if 'ziokt' not in mcp['bridges']:
        template=strict_json(secure_read(mcp['bridges']['corium']))
        keypath=base/'ziokt/application.key';keypath.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if keypath.exists():
            if len(secure_read(keypath,32))!=32:raise ValueError('incomplete Ziokt application key')
        else:
            fd=os.open(keypath,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as key:key.write(secrets.token_bytes(32))
        template={key:value for key,value in template.items() if key in {'schema','community_root','policy','owner','encryption_key','signing_key','application','application_key'}}
        template.update(application='ziokt',application_key=str(keypath),naming_namespaces=[namespace])
        path=base/'ziokt/bridge.json';write(path,template);mcp['bridges']['ziokt']=str(path)
    sources={}
    for app,path in mcp['bridges'].items():
        if app not in {'ziokt','shadow6','etp','safefs','sim-manager','sim','tri','ufs','dcpm','watchat','zda'}:continue
        bridge=strict_json(secure_read(path));community_id=strict_json(secure_read(bridge['policy']))['payload']['community_id']
        namespaces=bridge.get('naming_namespaces',[community_id])
        if namespace not in namespaces:bridge['naming_namespaces']=[*namespaces,namespace];write(path,bridge)
        component='sim' if app=='sim-manager' else app
        sources[component]={'component_bridge':str(Path(path).resolve())}
    forum=Path(gateway['forum_db']);chain=forum.parent.parent/'blockchain/chain.db'
    sources['corium']={'forum_db':str(forum),'chain_db':str(chain),'objects':gateway['objects'],'native_network_id':gateway['network']}
    config={'schema':'ziokt.dns.v2','listen':'127.0.0.1','port':5353,'doh_port':8188,'default_realm':'main',
            'realms':{'main':{'network_id':namespace,'sources':sources}}}
    write(output,config);mcp['dns_config']=str(Path(output).resolve());write(mcp_path,mcp)
    return {'config':str(Path(output).resolve()),'namespace':namespace,'sources':sorted(sources),'names_published':0,'listeners_started':False}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--mcp-config',required=True);parser.add_argument('--gateway-config',required=True);parser.add_argument('--output',required=True);parser.add_argument('--namespace',required=True);args=parser.parse_args()
    print(json.dumps(configure(args.mcp_config,args.gateway_config,args.output,args.namespace)))

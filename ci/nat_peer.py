"""Isolated CI peers for outbound-only double-NAT and address-change evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from test_community_network import certificates
from cryptography.hazmat.primitives import serialization
from ziokt.community import Community, RIGHTS, create_policy
from ziokt.protocol import make_private
from ziokt.remote import tls_context, remote_server
from ziokt.rendezvous import OpaqueRendezvous, RendezvousClient, RELAY_METHODS
from ziokt.peer_proxy import proxy_server
from ziokt.security import sign

p=argparse.ArgumentParser(); p.add_argument('mode',choices=['prepare','serve','send','receive']);p.add_argument('root',type=Path);a=p.parse_args();r=a.root
if a.mode=='prepare':
    r.mkdir(mode=0o700,parents=True,exist_ok=True)
    first,second,key=secrets.token_bytes(32),secrets.token_bytes(32),secrets.token_bytes(32)
    publics=[sign({},v,'test')['public_key'] for v in [first,second]]
    policy=create_policy(first,'nat-community',{v:sorted(RIGHTS) for v in publics},privacy='private')
    tls=[]
    for i in range(2):
        d=r/('tls'+str(i));d.mkdir(mode=0o700)
        ca,pairs=certificates(d,'198.18.241.1');tls.append((ca,pairs))
    ca=r/'server-cas.pem';ca.write_bytes(b''.join(v[0].read_bytes() for v in tls))
    trusted={hashlib.sha256(tls[i][1]['client'][2].public_bytes(serialization.Encoding.DER)).hexdigest():{'public_key':publics[i],'methods':sorted(RELAY_METHODS),'providers':['nat-community']} for i in range(2)}
    server={'root':str(r),'policy':policy,'owner':publics[0],'ca':str(ca),'certificate':str(tls[0][1]['server'][0]),'private_key':str(tls[0][1]['server'][1]),'trusted':trusted}
    (r/'server.json').write_text(json.dumps(server));make_private(r/'server.json')
    for i,private in enumerate([first,second]):
        data={'root':str(r), 'policy':policy,'owner':publics[0],'private':private.hex(),'content_key':key.hex(),'recipient':publics[1], 'ca':str(tls[0][0]),'certificate':str(tls[i][1]['client'][0]),'private_key':str(tls[i][1]['client'][1])}
        path=r/('client'+str(i)+'.json');path.write_text(json.dumps(data));make_private(path)
        for proxy_port in (24444,24445):
            proxy_config={'schema':'ziokt.remote.v1','host':'198.18.241.1','port':proxy_port,
                          'certificate':data['certificate'],'private_key':data['private_key'],'ca':data['ca']}
            proxy_path=r/f'proxy-client-{i}-{proxy_port}.json'
            proxy_path.write_text(json.dumps(proxy_config));make_private(proxy_path)
    raise SystemExit(0)
if a.mode=='serve':
    cfg=json.loads((r/'server.json').read_text()); backend=OpaqueRendezvous(r/'relay',cfg['policy'],cfg['owner'])
    server=remote_server({'enabled':True,'federation_id':'nat-community','providers':[]},tls_context(cfg['certificate'],cfg['private_key'],cfg['ca'],server=True),r/'replay.sqlite',cfg['trusted'],host='198.18.241.1',port=24443,allow_mutations=True,community=backend)
    proxies=[];threads=[]
    for proxy_port,next_port in ((24444,24445),(24445,24443)):
        proxy=proxy_server({'schema':'ziokt.peer-proxy.v1','enabled':True,'host':'198.18.241.1','port':proxy_port,
                           'trusted_clients':list(cfg['trusted']),'targets':[{'host':'198.18.241.1','port':next_port}],
                           'max_connections':8,'max_bytes':64*1024*1024,'max_seconds':60},
                          tls_context(cfg['certificate'],cfg['private_key'],cfg['ca'],server=True))
        thread=threading.Thread(target=proxy.serve_forever,daemon=True);thread.start()
        proxies.append(proxy);threads.append(thread)
    (r/'ready').write_text('ready')
    try:server.serve_forever()
    finally:
        server.server_close();backend.close()
        for proxy in proxies:proxy.shutdown();proxy.server_close()
        for thread in threads:thread.join(5)
else:
    index=0 if a.mode=='send' else 1;cfg=json.loads((r/('client'+str(index)+'.json')).read_text())
    endpoint={'host':'198.18.241.1','port':24443,'connection_policy':{'mode':'relay','allow_direct_fallback':False},'rendezvous':{'recipient':cfg['recipient']}}
    endpoint['carrier']={'kind':'peer-multihop','hops':[{'host':'198.18.241.1','port':port,'tls_config':str(r/f'proxy-client-{index}-{port}.json')} for port in (24444,24445)]}
    with Community(r/('node'+str(index)),cfg['policy'],cfg['owner'],bytes.fromhex(cfg['content_key'])) as node:
        client=RendezvousClient(node,endpoint,tls_context(cfg['certificate'],cfg['private_key'],cfg['ca']),bytes.fromhex(cfg['private']))
        if a.mode=='send':
            node.publish(bytes.fromhex(cfg['private']),'wiki','survival',{'title':'Double NAT','text':'opaque relay survives dynamic IP'})
            result=client.send(cfg['recipient']);assert result['queued'] and not result['delivered'];print('outbound submission confirmed')
        else:
            result=client.receive();assert result['received']==1
            assert node.view('wiki')['events'][0]['body']['text']=='opaque relay survives dynamic IP';print('outbound receive and content verification confirmed')

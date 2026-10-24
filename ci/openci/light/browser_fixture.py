"""Actual Controller, native encrypted objects, task leases and signing identities."""
import hashlib,json,os,secrets,sys,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from openci.controller import Controller,Server,handler
from openci.quorum import approve
from ziokt.security import sign

root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
compiler=Path('dist/light-compiler').resolve();raw=(compiler/'manifest.json').read_bytes();manifest=json.loads(raw)
principals={'owner':{'role':'admin','projects':[],'token_sha256':hashlib.sha256(b'ci-owner').hexdigest()}}
for name in ('nodeA','nodeB'):principals[name]={'role':'worker','worker':name,'projects':['demo'],'token_sha256':hashlib.sha256(('ci-'+name).encode()).hexdigest()}
config=root/'controller.json';config.write_text(json.dumps({'principals':principals,'light_compile':{'compiler_root':str(compiler),'manifest_sha256':hashlib.sha256(raw).hexdigest(),'cross_compile':False}}));config.chmod(0o600)
controller=Controller(root/'state',config);mount=os.environ.get('OPENCI_BROWSER_PREFIX','')
if mount not in {'','/openci'}:raise ValueError('fixed test mount required')
backend=None
server=Server(('127.0.0.1',0),handler(controller));origin='http://127.0.0.1:'+str(server.server_port)
if mount:
    import socket
    from types import SimpleNamespace
    from ziokt.effort_web import effort_server
    backend=server;threading.Thread(target=backend.serve_forever,daemon=True).start()
    with socket.socket() as free:
        free.bind(('127.0.0.1',0));proxy_port=free.getsockname()[1]
    upstream=origin;origin='http://127.0.0.1:'+str(proxy_port)
    server=effort_server(SimpleNamespace(expected_network='browser-fixture'),origin,port=proxy_port,openci_endpoint=upstream)
settings=json.loads(config.read_text());settings['public_origin']=origin;config.write_text(json.dumps(settings))
image=manifest['targets']['x86_64']['image'];seeds={}
for index,name in enumerate(('nodeA','nodeB')):
    pool='community' if index==0 else 'trusted';seed=secrets.token_bytes(32);seeds[name]=seed
    controller.state.approve_worker('owner',name,arch='x86_64',pool=pool,cpu=1,memory_mb=64,slots=1,projects=['demo'])
    approve(controller.state,'owner',name,'domain'+str(index),[image],'sha256:'+'e'*64)
    controller.state.approve_receipt_key('owner',name,sign({},seed,'key')['public_key'],'sha256:'+'f'*64)
    path=root/(name+'.json');path.write_text(json.dumps({'schema':'openci.light-credential.v1','controller':origin,'worker':name,'token':'ci-'+name,'seed_hex':seed.hex()}));path.chmod(0o600)
source=json.dumps({'schema':'openci.light-source.v1','name':'unit.i','source':'int square(int x) { return x*x; }\n'},sort_keys=True,separators=(',',':')).encode()
upload=controller.fabric.begin('openci-demo','input',len(source),'sha256:'+hashlib.sha256(source).hexdigest(),'application/json');controller.fabric.put('openci-demo','input',0,source);obj=controller.fabric.finish('openci-demo','input');ref={'object':obj['id'],'digest':obj['digest']}
tasks=[{'id':'build'+str(i),'needs':[],'executor':'light-c','image':image,'argv':['light-c','x86_64','unit.i','unit.o'],'arch':'x86_64','pool':'community' if i==0 else 'trusted','cpu':1,'memory_mb':64,'timeout':20,'attempts':2,'outputs':['unit.o'],'worker':name} for i,name in enumerate(('nodeA','nodeB'))]
pid=controller.state.submit('owner',{'schema':'openci.pipeline.v1','project':'demo','nonce':'browser-test','source':ref,'tasks':tasks})['pipeline']
(root/'ready.json').write_text(json.dumps({'origin':origin+mount,'pipeline':pid}));(root/'ready.json').chmod(0o600)
try:server.serve_forever()
finally:
    server.server_close()
    if backend:backend.shutdown();backend.server_close()
    controller.close()

"""Real loopback Gateway -> MCP -> authenticated component vault, for GUI CI."""
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.protocol import encoded
from ziokt.gateway import Gateway,Server,handler
from tools.configure_mcp_gateway import provision


def configuration(root):
    root=Path(root);admin=root/'admin';admin.write_text('gui-ci-owner-token');admin.chmod(0o600)
    gateway=root/'gateway.json';config={'network':'gui-ci','objects':str(root/'objects'),'forum_db':str(root/'forum.db'),'admin_token':str(admin)}
    gateway.write_bytes(encoded(config));gateway.chmod(0o600)
    federation=root/'federation.json'
    federation.write_bytes(encoded({'schema':'ziokt.federation.v1','enabled':False,'federation_id':'test','providers':[{'native_project':'corium','provider_id':'corium-test','root':str(root),'native_config':str(root/'etc/corix/networks/test/corix.conf'),'state_root':str(root),'network_id':'test','entrypoint_digest':'sha256:'+'a'*64}]}));federation.chmod(0o600)
    path,_=provision(root/'mcp','https://gui.test',federation,gateway)
    # Exercise the actual delegated Community service, not seeded browser posts.
    from ziokt.security import sign
    from ziokt.protocol import secure_read,strict_json
    from ziokt.mcp import Service
    settings=strict_json(secure_read(path));authority=root/'mcp/authority.key'
    owner=sign({},secure_read(authority,32),'gui-fixture')['public_key']
    settings['content_fabric']={'enabled':True,'root':str(root/'content'),'accounts':{'ziokt-operator':'owner'},'community':{'root':str(root/'mcp/community'),'owner':owner,'policy':str(root/'mcp/policy.json'),'encryption_key':str(root/'mcp/community.key'),'accounts':{'owner':{'public_key':owner,'signing_key':str(authority)}}}}
    settings['clients']['ziokt-operator']['scopes']=Service(settings).scopes
    path.write_bytes(encoded(settings));path.chmod(0o600)
    config['mcp_config']=str(path)
    return config

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='ziokt-gui-ci-') as directory:
        config=configuration(directory);gateway=Gateway(config);server=Server(('127.0.0.1',0),handler(gateway))
        print(json.dumps({'origin':'http://127.0.0.1:'+str(server.server_port),'token':'gui-ci-owner-token'}),flush=True)
        try:server.serve_forever()
        finally:server.server_close();gateway.close()

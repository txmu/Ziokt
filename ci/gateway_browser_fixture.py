"""Loopback real database, signature verifier, OAuth and MCP browser fixture."""
import json,sqlite3,sys,tempfile,threading,signal
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.gateway import Gateway,Server,handler,ASSETS
from ziokt.gateway_store import database
from ziokt.mcp import Service,http_handler

signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))

with tempfile.TemporaryDirectory(prefix='ziokt-browser-') as directory:
 root=Path(directory);forum=root/'forum.db';token=root/'token';token.write_text('browser-test-token');token.chmod(0o600)
 with database(forum) as db:db.executescript('CREATE TABLE topics(id TEXT PRIMARY KEY,title TEXT,author TEXT,timestamp INT,signature TEXT,content_hash TEXT,attachment_hash TEXT,attachment_name TEXT,associated_group_id TEXT); CREATE TABLE posts(id TEXT PRIMARY KEY,topic_id TEXT,author TEXT,timestamp INT,signature TEXT,content_hash TEXT,attachment_hash TEXT,attachment_name TEXT);')
 config={'network':'browser-test','objects':str(root/'objects'),'forum_db':str(forum),'admin_token':str(token),'registry_db':str(root/'registry.db')}
 path=root/'gateway.json';path.write_text(json.dumps(config));path.chmod(0o600)
 gateway=Gateway(config)
 settings={'state':str(root/'mcp'),'issuer':'http://127.0.0.1','origins':[],'admin_token':str(token),'gateway':str(path),'writes_enabled':True,'clients':{'ziokt-browser':{'redirect_uris':[],'scopes':['ziokt:read','ziokt:apply','gateway:read','gateway:write']}}}
 from ziokt.cli import write_exclusive,write_binary_exclusive
 from ziokt.community import create_policy,RIGHTS
 from ziokt.security import sign
 area=root/'ufs';area.mkdir(mode=0o700);(area/'vault').mkdir(mode=0o700)
 private=b'u'*32;public=sign({},private,'test')['public_key']
 for name,key in [('signing',private),('encryption',b'e'*32),('application',b'a'*32)]:write_binary_exclusive(area/(name+'.key'),key)
 write_exclusive(area/'policy.json',create_policy(private,'browser-objects',{public:sorted(RIGHTS)}))
 write_exclusive(area/'bridge.json',{'schema':'ziokt.companion-bridge.v1','community_root':str(area/'community'),'policy':str(area/'policy.json'),'owner':public,'encryption_key':str(area/'encryption.key'),'signing_key':str(area/'signing.key'),'application':'ufs','application_key':str(area/'application.key'),'vault_root':str(area/'vault')})
 settings['bridges']={'ufs':str(area/'bridge.json')}
 mcp=Service(settings);settings['clients']['ziokt-browser']['scopes']=mcp.scopes;GW=handler(gateway);MCP=http_handler(mcp)
 class API:
  def get_node_context(self):
   with database(forum) as db:rows=db.execute('SELECT id,title,author,timestamp,content_hash FROM topics').fetchall()
   return {'forum':{'topics':[{'id':r[0],'topic':r[1],'author':r[2],'timestamp':r[3],'content':(root/'objects'/r[4]).read_text(),'content_hash':r[4],'replies':[]} for r in rows]}}
 class Combined(GW,MCP):
  def do_GET(self):
   if self.path.startswith('/app/'):
    from urllib.parse import urlsplit,parse_qs
    parsed=urlsplit(self.path);parts=parsed.path.strip('/').split('/');locale='zh-CN' if 'zh' in parsed.query else 'en-US'
    namespace={'api':API(),'request':{'app_id':parts[1],'path':parts[2:],'query':parse_qs(parsed.query),'locale':locale}}
    source=(ASSETS/'default_dapp/entrypoint.py').read_text().replace('MESSAGES = {}','MESSAGES = '+repr(json.loads((ASSETS/'i18n.json').read_text())))
    exec(compile(source,'default_dapp','exec'),namespace)
    return self.send(200,namespace['response'].encode(),'text/html; charset=utf-8')
   if self.path.startswith(('/mcp','/oauth/','/.well-known/')):return MCP.do_GET(self)
   return GW.do_GET(self)
  def do_POST(self):
   if self.path.startswith(('/mcp','/oauth/')):return MCP.do_POST(self)
   return GW.do_POST(self)
 server=Server(('127.0.0.1',0),Combined);origin='http://127.0.0.1:'+str(server.server_port)
 mcp_server=Server(('127.0.0.1',0),MCP);mcp_origin='http://127.0.0.1:'+str(mcp_server.server_port)
 settings['issuer']=mcp_origin;settings['origins']=[origin,mcp_origin];settings['hosts']=[origin.split('//',1)[1],mcp_origin.split('//',1)[1]];settings['clients']['ziokt-browser']['redirect_uris']=[origin+'/gateway-assets/oauth-callback.html']
 threading.Thread(target=mcp_server.serve_forever,daemon=True).start()
 print(json.dumps({'origin':origin,'admin_token':'browser-test-token'}),flush=True)
 server.serve_forever()

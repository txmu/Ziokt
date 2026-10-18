import base64,hashlib,http.client,json,secrets,tempfile,threading,time,unittest
from pathlib import Path
from urllib.parse import urlencode,urlsplit,parse_qs
from ziokt.gateway import Server
from ziokt.gateway_store import database
from ziokt.mcp import Service,McpError,http_handler,LATEST
from ziokt.protocol import encoded
from tools.configure_mcp_gateway import provision

class McpTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  admin=self.root/'admin';admin.write_text('a'*64);admin.chmod(0o600)
  self.config={'schema':'ziokt.mcp.v1','issuer':'https://gateway.test','origins':['https://gateway.test'],'state':str(self.root/'state'),'admin_token':str(admin),'bridges':{},'clients':{'reader':{'redirect_uris':['http://127.0.0.1:8765/callback'],'scopes':['ziokt:read']},'operator':{'redirect_uris':['http://127.0.0.1:8765/callback'],'scopes':['ziokt:read','ziokt:apply']}},'writes_enabled':True}
  self.service=Service(self.config);self.tokens=self.service.issue('reader',{'ziokt:read'});self.principal=self.service.auth('Bearer '+self.tokens['access_token'])
  self.server=Server(('127.0.0.1',0),http_handler(self.service));threading.Thread(target=self.server.serve_forever,daemon=True).start();self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
 def request(self,method,path,data=None,headers=None):
  conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5);conn.request(method,path,data,headers or {});r=conn.getresponse();result=r.status,dict(r.getheaders()),r.read();conn.close();return result
 def rpc(self,method='tools/list',params=None,version=LATEST,extra=None):
  params=params or {};params['_meta']={'io.modelcontextprotocol/protocolVersion':version,'io.modelcontextprotocol/clientCapabilities':{},**params.get('_meta',{})}
  body={'jsonrpc':'2.0','id':1,'method':method,'params':params};headers={'Authorization':'Bearer '+self.tokens['access_token'],'Content-Type':'application/json','Accept':'application/json, text/event-stream','MCP-Protocol-Version':version,'Mcp-Method':method}
  if method in {'tools/call','resources/read','prompts/get'}:headers['Mcp-Name']=params.get('name',params.get('uri'))
  headers.update(extra or {});return self.request('POST','/mcp',json.dumps(body),headers)
 def test_modern_legacy_and_resources(self):
  status,_,data=self.rpc();self.assertEqual(status,200);names={t['name'] for t in json.loads(data)['result']['tools']};self.assertIn('ziokt_components',names);self.assertNotIn('ziokt_workflow_apply',names)
  self.assertEqual(self.rpc('initialize',{'protocolVersion':'2025-11-25'},version='2025-11-25')[0],200)
  self.assertEqual(self.rpc('initialize')[0],404)
  self.assertEqual(self.rpc('resources/read',{'uri':'ziokt://components'})[0],200)
  self.assertEqual(self.rpc('unknown')[0],404)
 def test_auth_origin_headers_and_audience(self):
  self.assertEqual(self.request('POST','/mcp','{}',{'Content-Type':'application/json'})[0],401)
  self.assertEqual(self.rpc(extra={'Origin':'https://evil.test'})[0],403)
  self.assertEqual(self.rpc(extra={'Host':'evil.test'})[0],403)
  status,_,body=self.rpc(extra={'Mcp-Method':'tools/call'});self.assertEqual(status,400);self.assertEqual(json.loads(body)['error']['code'],-32020)
  self.assertEqual(self.rpc(extra={'MCP-Protocol-Version':'1900-01-01'})[0],400)
  self.assertEqual(self.request('GET','/mcp')[0],405)
  self.assertEqual(self.request('GET','/.well-known/oauth-protected-resource')[0],200)
  self.config['issuer']='https://different.test'
  with self.assertRaises(McpError):self.service.auth('Bearer '+self.tokens['access_token'])
 def test_scope_write_and_idempotency(self):
  with self.assertRaises(McpError):self.service.call(self.principal,'ziokt_workflow_apply',{'workflow_id':'x','plan_digest':'x','confirm':True},'k'*16)
  op=self.service.auth('Bearer '+self.service.issue('operator',{'ziokt:read','ziokt:apply'})['access_token'])
  self.service.add('test_write','bounded test operation',{'type':'object','properties':{},'required':[],'additionalProperties':False},True,'ziokt:apply',('test',))
  executed=[];original=self.service.execute
  def execute(p,n,a):
   if n=='test_write':executed.append(1);return {'ok':True}
   return original(p,n,a)
  self.service.execute=execute
  first=self.service.call(op,'test_write',{},'x'*16);second=self.service.call(op,'test_write',{},'x'*16);self.assertEqual(first,second);self.assertEqual(len(executed),1)
  with self.assertRaises(ValueError):self.service.call(op,'test_write',{},None)
  self.config['writes_enabled']=False
  with self.assertRaises(McpError):self.service.call(op,'test_write',{},'z'*16)
  with database(self.service.db) as db:
   row=db.execute('SELECT client,tool,outcome FROM audit').fetchall();self.assertEqual(row,[('operator','test_write','complete')])
 def test_oauth_pkce_rotation_revocation(self):
  verifier=secrets.token_urlsafe(48);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
  auth={'client_id':'reader','redirect_uri':'http://127.0.0.1:8765/callback','response_type':'code','code_challenge':challenge,'code_challenge_method':'S256','scope':'ziokt:read','state':'random-state','resource':'https://gateway.test/mcp'}
  status,headers,body=self.request('GET','/oauth/authorize?'+urlencode(auth));self.assertEqual(status,200);self.assertIn(auth['redirect_uri'],headers['Content-Security-Policy']);self.assertIn(b'name="referrer" content="same-origin"',body)
  hint='header.payload.signature';extension_value='never-render-this'
  status,_,body=self.request('GET','/oauth/authorize?'+urlencode({**auth,'id_token_hint':hint,'prompt':'login','optional_extension':extension_value}));self.assertEqual(status,200);self.assertNotIn(hint.encode(),body);self.assertNotIn(extension_value.encode(),body)
  status,headers,_=self.request('POST','/oauth/authorize',urlencode({**auth,'admin_token':'a'*64}),{'Content-Type':'application/x-www-form-urlencoded'});self.assertEqual(status,303)
  code=parse_qs(urlsplit(headers['Location']).query)['code'][0]
  params={'grant_type':'authorization_code','code':code,'code_verifier':verifier,'client_id':'reader','redirect_uri':auth['redirect_uri'],'resource':auth['resource']}
  def token(p):return self.request('POST','/oauth/token',urlencode(p),{'Content-Type':'application/x-www-form-urlencoded'})
  self.assertEqual(token({**params,'code_verifier':'z'*64})[0],400)
  status,_,body=token(params);self.assertEqual(status,200);tokens=json.loads(body);self.assertEqual(token(params)[0],400)
  refresh={'grant_type':'refresh_token','refresh_token':tokens['refresh_token'],'client_id':'reader','resource':auth['resource']}
  self.assertEqual(token(refresh)[0],200);self.assertEqual(token(refresh)[0],400)
  self.assertEqual(self.request('POST','/oauth/revoke',urlencode({'token':tokens['access_token']}),{'Content-Type':'application/x-www-form-urlencoded','Authorization':'Bearer '+tokens['access_token']})[0],200)
  with self.assertRaises(McpError):self.service.auth('Bearer '+tokens['access_token'])
 def test_realtime_client_revocation(self):
  del self.config['clients']['reader']
  with self.assertRaises(McpError):self.service.auth('Bearer '+self.tokens['access_token'])

class ComponentMcpTests(unittest.TestCase):
 def test_real_vault_cross_component_exchange(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);admin=root/'admin';admin.write_text('a'*64);admin.chmod(0o600)
   gateway=root/'gateway.json';gateway.write_bytes(encoded({'admin_token':str(admin)}));gateway.chmod(0o600)
   # Provision the actual pairwise identities, then test real SafeFS + mail + recipient vault.
   federation=root/'federation.json';federation.write_bytes(encoded({'schema':'ziokt.federation.v1','enabled':False,'federation_id':'test','providers':[{'native_project':'corium','provider_id':'corium-test','root':str(root),'native_config':str(root/'etc/corix/networks/test/corix.conf'),'state_root':str(root),'network_id':'test','entrypoint_digest':'sha256:'+'a'*64}]}));federation.chmod(0o600)
   path,count=provision(root/'mcp','https://test.example',federation,gateway,portal_origin='https://portal.example');config=json.loads(path.read_bytes());self.assertIn('portal.example',config['hosts']);self.assertIn('https://portal.example',config['origins']);self.assertEqual(config['clients']['ziokt-browser']['redirect_uris'],['https://portal.example/gateway-assets/oauth-callback.html']);config.pop('gateway');service=Service(config)
   principal={'client':'ziokt-operator','scopes':set(service.scopes),'expires':int(time.time())+900}
   self.assertGreater(count,150)
   def call(name,args,key):
    value=service.call(principal,name,{'params':args},key);self.assertFalse(value['isError'],value);return value['structuredContent']
   payload=b'large-control-path'*3000;digest='sha256:'+hashlib.sha256(payload).hexdigest()
   call('dcpm_object_begin',{'upload':'mcp-object','size':len(payload),'digest':digest,'ttl':3600},'object-begin-0001')
   for i,start in enumerate(range(0,len(payload),16384)):
    chunk=payload[start:start+16384]
    call('dcpm_object_chunk_put',{'upload':'mcp-object','position':i,'digest':'sha256:'+hashlib.sha256(chunk).hexdigest(),'data_base64':base64.b64encode(chunk).decode()},('object-chunk-'+str(i)).ljust(16,'x'))
   ref=call('dcpm_object_finish',{'upload':'mcp-object'},'object-finish-01')
   self.assertEqual(ref['length'],len(payload));self.assertFalse(ref['execution_authorized'])
   from ziokt.security import verify
   verify(ref['attestation'],ref['attestation']['public_key'],'Ziokt/object-reference/v1')
   read=call('dcpm_object_chunk_get',{'object':ref['manifest_digest'],'position':0},None)
   self.assertEqual(base64.b64decode(read['data_base64']),payload[:16384])
   report=service.call(principal,'tri_object_reference',{'params':{'object':ref['manifest_digest']}},None)
   self.assertTrue(report['isError'])
   with self.assertRaises(ValueError):service.call(principal,'dcpm_package_build_references',{'params':{'name':'bad','version':'1','files':{'data':'not-a-digest'},'dependencies':[]}},'invalid-ref-0001')
   restricted={'client':'ziokt-operator','scopes':{'dcpm:read'},'expires':int(time.time())+60}
   with self.assertRaises(McpError):service.call(restricted,'dcpm_object_begin',{'params':{'upload':'forbidden','size':0,'digest':digest,'ttl':60}},'forbidden-000001')
   built=call('dcpm_package_build_references',{'name':'mcp-demo','version':'1.0.0','files':{'data':ref['manifest_digest']},'dependencies':[]},'package-ref-0001')
   verified=call('dcpm_package_verify_references',{'digest':built['digest'],'authority':ref['attestation']['public_key']},None)
   self.assertEqual(verified['content_bytes'],len(payload))
   saved=call('safefs_vault_put',{'name':'test.txt','data_base64':base64.b64encode(b'private payload').decode()},'a'*16)
   sent=call('safefs_component_send',{'target':'tri','kind':'file','digest':saved['digest'],'operation':'test-operation'},'b'*16)
   received=call('tri_component_receive',{'event':sent['event'],'source':'safefs'},'c'*16)
   opened=call('tri_vault_get',{'digest':received['digest']},None)
   self.assertEqual(base64.b64decode(opened['data_base64']),b'private payload')
   from ziokt.component_links import COMPONENTS
   apps=sorted(COMPONENTS)
   for index,app in enumerate(apps):
    status=call(app.replace('-','_')+'_component_status',{},None)
    self.assertEqual(status['application'],app)
    item=call(app.replace('-','_')+'_vault_put',{'name':'ring.txt','data_base64':base64.b64encode(app.encode()).decode()},('put-'+str(index)).ljust(16,'x'))
    target=apps[(index+1)%len(apps)]
    offer=call(app.replace('-','_')+'_component_send',{'target':target,'kind':'file','digest':item['digest'],'operation':'ring-'+str(index)},('send-'+str(index)).ljust(16,'x'))
    receipt=call(target.replace('-','_')+'_component_receive',{'event':offer['event'],'source':app},('receive-'+str(index)).ljust(16,'x'))
    value=call(target.replace('-','_')+'_vault_get',{'digest':receipt['digest']},None)
    self.assertEqual(base64.b64decode(value['data_base64']),app.encode())

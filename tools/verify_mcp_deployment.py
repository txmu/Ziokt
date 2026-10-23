#!/usr/bin/env python3
"""Exercise public TLS/CIMD/PKCE/native tools without visiting a ChatGPT account."""
import argparse,base64,hashlib,json,secrets,sys,urllib.error,urllib.parse,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.gateway import read_token
from ziokt.gateway_store import NoRedirect


def verify(issuer,admin_token,client_config=None,client_id=None):
 class RedirectToHeader(urllib.request.HTTPRedirectHandler):
  def redirect_request(self,*args,**kwargs):return None
 opener=urllib.request.build_opener(RedirectToHeader())
 def request(path,data=None,headers=None):
  if isinstance(data,dict):data=json.dumps(data).encode()
  req=urllib.request.Request(issuer+path,data=data,headers=headers or {})
  try:
   with opener.open(req,timeout=20) as response:return response.status,dict(response.headers),response.read()
  except urllib.error.HTTPError as response:return response.code,dict(response.headers),response.read()
 metadata=json.loads(request('/.well-known/oauth-authorization-server')[2]);assert metadata['issuer']==issuer and metadata['client_id_metadata_document_supported']
 client=client_id or 'https://chatgpt.com/oauth/client.json';redirect='https://chatgpt.com/connector_platform_oauth_redirect'
 registered=None
 if client_config is not None:
  config=json.loads(Path(client_config).read_text());registered=config['clients'][client]
  redirect=registered['redirect_uris'][0]
 verifier=secrets.token_urlsafe(48);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
 supported=json.loads(request('/.well-known/oauth-protected-resource/mcp')[2])['scopes_supported']
 scopes=registered['scopes'] if registered is not None else supported
 fields={'client_id':client,'redirect_uri':redirect,'response_type':'code','code_challenge':challenge,'code_challenge_method':'S256','scope':' '.join(scopes),'state':secrets.token_urlsafe(24),'resource':issuer+'/mcp'}
 assert request('/oauth/authorize?'+urllib.parse.urlencode(fields))[0]==200
 status,headers,_=request('/oauth/authorize',urllib.parse.urlencode({**fields,'admin_token':read_token(admin_token)}).encode(),{'Content-Type':'application/x-www-form-urlencoded'});assert status==303,status
 params=urllib.parse.parse_qs(urllib.parse.urlsplit(headers['Location']).query);assert params['state'][0]==fields['state'] and params['iss'][0]==issuer
 token_fields={'grant_type':'authorization_code','client_id':client,'code':params['code'][0],'code_verifier':verifier,'redirect_uri':redirect,'resource':issuer+'/mcp'}
 status,_,raw=request('/oauth/token',urllib.parse.urlencode(token_fields).encode(),{'Content-Type':'application/x-www-form-urlencoded'});assert status==200,raw
 token=json.loads(raw)['access_token']
 def rpc(method,params=None,version='2026-07-28',header=True):
  params=params or {};params['_meta']={'io.modelcontextprotocol/protocolVersion':version,'io.modelcontextprotocol/clientCapabilities':{}}
  headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json, text/event-stream','Mcp-Method':method}
  if header:headers['MCP-Protocol-Version']=version
  if method=='tools/call':headers['Mcp-Name']=params['name']
  status,_,raw=request('/mcp',{'jsonrpc':'2.0','id':1,'method':method,'params':params},headers);assert status==200,(status,raw)
  result=json.loads(raw)
  if 'error' in result:raise RuntimeError(result['error'])
  return result['result']
 try:
  assert '2026-07-28' in rpc('server/discover')['supportedVersions']
  for version in ['2025-11-25','2025-06-18','2025-03-26']:
   assert rpc('initialize',{'protocolVersion':version},version,header=False)['protocolVersion']==version
  tools=rpc('tools/list')['tools'];names={t['name'] for t in tools};checked=[]
  for name in sorted(names):
   if not any(set(scheme.get('scopes',[]))<=set(scopes) for scheme in next(t for t in tools if t['name']==name).get('securitySchemes',[])):continue
   if name.endswith('_component_status') or name in {'gateway_status','corium_production_status_get','shadow6_production_status_get','etp_etp_stats','etp_peer_etp_stats','corium_cbb_messages','corium_registration_list'}:
    args={'status':'approved'} if name=='corium_registration_list' else {} if name in {'gateway_status','corium_cbb_messages'} else {'params':{}}
    value=rpc('tools/call',{'name':name,'arguments':args});assert not value['isError'],(name,value);checked.append(name)
  write={'name':'tc16_tc16_run','arguments':{'params':{'source':'HALT','syntax':'assembly','cycles':16},'idempotency_key':secrets.token_hex(16)}}
  first=rpc('tools/call',write);assert not first['isError'],first
  assert rpc('tools/call',write)==first
  assert request('/mcp',b'{}',{'Content-Type':'application/json'})[0]==401
  return {'issuer':issuer,'tls_verified':True,'cimd_pkce':registered is None,'registered_client_pkce':registered is not None,'legacy_versions':True,'tools':len(tools),'native_read_checks':checked,'write_and_idempotency':True,'anonymous_mcp':401}
 finally:
  request('/oauth/revoke',urllib.parse.urlencode({'token':token}).encode(),{'Content-Type':'application/x-www-form-urlencoded','Authorization':'Bearer '+token})

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--issuer',required=True);p.add_argument('--admin-token',required=True,type=Path);p.add_argument('--receipt',required=True,type=Path);p.add_argument('--client');p.add_argument('--config',type=Path);a=p.parse_args();receipt=verify(a.issuer,a.admin_token,a.config,a.client);a.receipt.write_text(json.dumps(receipt,indent=2)+'\n');a.receipt.chmod(0o600);print(json.dumps(receipt))

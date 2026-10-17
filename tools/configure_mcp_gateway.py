#!/usr/bin/env python3
"""Provision explicit MCP grants and pairwise component identities, without builds."""
import argparse,json,os,secrets,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.component_links import COMPONENTS,KINDS
from ziokt.community import RIGHTS,create_policy
from ziokt.community_privacy import mailbox_public
from ziokt.security import sign
from ziokt.protocol import secure_read,strict_json,encoded
from ziokt.mcp import Service


def provision(root,issuer,federation,gateway,existing=None,portal_origin=None):
 from urllib.parse import urlsplit
 portal_origin=portal_origin or issuer
 for origin in (issuer,portal_origin):
  parsed=urlsplit(origin)
  if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:raise ValueError('exact HTTPS origin required')
 root=Path(root).resolve();root.mkdir(mode=0o700,parents=True,exist_ok=True);root.chmod(0o700)
 def write(path,value):
  path=Path(path)
  if path.exists():return
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as output:output.write(value)
 existing=existing or {};bridges={};identities={};exchanges={}
 for app in sorted(COMPONENTS):
  area=root/app;area.mkdir(mode=0o700,exist_ok=True)
  if app in existing:
   source=strict_json(secure_read(existing[app]));private=secure_read(source['signing_key'],32);bridges[app]=str(Path(existing[app]).resolve())
  else:
   for name in ['signing','application']:write(area/(name+'.key'),secrets.token_bytes(32))
   private=secure_read(area/'signing.key',32);source={'schema':'ziokt.companion-bridge.v1','application':app,'owner':sign({},private,'test')['public_key'],'signing_key':str(area/'signing.key'),'application_key':str(area/'application.key'),'vault_root':str(area/'vault')}
   (area/'vault').mkdir(mode=0o700,exist_ok=True)
  write(area/'exchange.key',secrets.token_bytes(32))
  identities[app]={'signing_public':sign({},private,'test')['public_key'],'mailbox_public':mailbox_public(secure_read(area/'exchange.key',32)),'kinds':sorted(KINDS)}
  exchanges[app]={**source,'community_root':str(root/'community'),'policy':str(root/'policy.json'),'encryption_key':str(root/'community.key'),'exchange_key':str(area/'exchange.key')}
 write(root/'authority.key',secrets.token_bytes(32));write(root/'community.key',secrets.token_bytes(32))
 authority=secure_read(root/'authority.key',32)
 write(root/'policy.json',encoded(create_policy(authority,'mcp-components',{**{v['signing_public']:sorted(RIGHTS) for v in identities.values()},sign({},authority,'test')['public_key']:sorted(RIGHTS)},privacy='private')))
 for app,source in exchanges.items():
  source['owner']=sign({},authority,'test')['public_key']
  source['component_peers']={name:value for name,value in identities.items() if name!=app}
  target=root/app/'exchange.json';write(target,encoded(source));exchanges[app]=str(target)
  if app not in bridges:bridges[app]=str(target)
 config={'schema':'ziokt.mcp.v1','cimd_enabled':True,'issuer':issuer,'origins':sorted({issuer,portal_origin}),'hosts':sorted({urlsplit(issuer).netloc,urlsplit(portal_origin).netloc,'127.0.0.1:8186'}),'state':str(root/'state'),'port':8186,'federation':str(Path(federation).resolve()),'gateway':str(Path(gateway).resolve()),'admin_token':strict_json(secure_read(gateway))['admin_token'],'bridges':bridges,'exchanges':exchanges,'telegram':{'enabled':False,'worker_enabled':False,'token_file':str(root/'telegram/bot.token'),'allowed_chat_ids':[],'allowed_user_ids':[]},'clients':{},'writes_enabled':True}
 service=Service(config)
 readonly=[s for s in service.scopes if s.endswith(':read')]
 config['clients']={'ziokt-reader':{'redirect_uris':['http://127.0.0.1:8765/callback'],'scopes':readonly},'ziokt-operator':{'redirect_uris':['http://127.0.0.1:8765/callback'],'scopes':service.scopes}}
 config['clients']['ziokt-browser']={'redirect_uris':[portal_origin+'/gateway-assets/oauth-callback.html'],'scopes':service.scopes}
 destination=root/'mcp.json';write(destination,encoded(config));return destination,len(service.tools)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--issuer',required=True);p.add_argument('--federation',type=Path,required=True);p.add_argument('--gateway',type=Path,required=True);p.add_argument('--bridge',action='append',default=[]);p.add_argument('--portal-origin',help='exact HTTPS portal origin when separate from the MCP issuer')
 a=p.parse_args();path,count=provision(a.root,a.issuer,a.federation,a.gateway,dict(item.split('=',1) for item in a.bridge),a.portal_origin);print(json.dumps({'config':str(path),'tools':count,'credentials_printed':False}))

#!/usr/bin/env python3
"""Export reviewed deployment inputs, never identity material or runtime databases."""
import argparse,configparser,hashlib,json,re,sys
from pathlib import Path

PATH_KEYS={'admin_token','application_key','encryption_key','exchange_key','signing_key','signing_key_path','private_key_path','token_file','password_file','credentials_file'}
SECRET=re.compile(r'password|secret|private|credential|authorization|api.?key|token|^key$',re.I)

def export(root,output):
 root=Path(root).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
 omitted=[];secret_values=[];files=[]
 def scrub(value,trail=()):
  if isinstance(value,dict):
   result={}
   for key,item in value.items():
    route=(*trail,key)
    if key=='identities' and isinstance(item,dict):
     result[key]={name:redact(secret,(*route,name)) for name,secret in item.items()}
    elif SECRET.search(key) and isinstance(item,str) and not (key in PATH_KEYS and item.startswith('/')):
     result[key]=redact(item,route)
    else:result[key]=scrub(item,route)
   return result
  if isinstance(value,list):return [scrub(item,(*trail,str(i))) for i,item in enumerate(value)]
  return value
 def redact(value,trail):
  omitted.append('.'.join(trail))
  if isinstance(value,str) and len(value)>=16:secret_values.append(value)
  return '<REGENERATE_OR_RESTORE_PRIVATE_VALUE>'
 def write(relative,value):
  target=output/relative;target.parent.mkdir(parents=True,exist_ok=True)
  raw=value.encode() if isinstance(value,str) else value
  if any(secret.encode() in raw for secret in secret_values):raise ValueError('secret material in output')
  target.write_bytes(raw);files.append(str(relative))
 def json_file(path,relative):
  value=scrub(json.loads(path.read_text()),(str(relative),));write(relative,json.dumps(value,ensure_ascii=False,indent=2)+'\n')
 for name in ['gateway.json','federation.json','shadow6-production.json','effort-web.json','runtime-digests.json']:
  json_file(root/'config'/name,Path('runtime/config')/name)
 json_file(root/'mcp/mcp.json',Path('runtime/mcp/mcp.json'))
 mcp=json.loads((root/'mcp/mcp.json').read_text())
 selected=set(mcp.get('bridges',{}).values())|set(mcp.get('exchanges',{}).values())
 selected.update(str(path) for path in (root/'config/etp-bulk').glob('*.json'))
 selected.update(item['config'] for item in mcp.get('etp',{}).values())
 for path in sorted(selected):
  source=Path(path).resolve();relative=source.relative_to(root)
  json_file(source,Path('runtime')/relative)
 for name in ['watchat','sim-manager']:
  source=root/name/'service.env';lines=[]
  for line in source.read_text().splitlines():
   if '=' not in line or line.lstrip().startswith('#'):lines.append(line);continue
   key,value=line.split('=',1)
   if SECRET.search(key):value=redact(value,(name,'service.env',key))
   lines.append(key+'='+value)
  write(Path('runtime')/name/'service.env','\n'.join(lines)+'\n')
  # Push config includes an inline private VAPID key on some deployments.
  for line in source.read_text().splitlines():
   if line.startswith('WATCHAT_PUSH_CONFIG='):
    path=Path(line.split('=',1)[1].strip('"\''))
    if path.is_file():json_file(path,Path('runtime')/path.resolve().relative_to(root))
 for source in sorted((root/'config').glob('*.service')):
  text=source.read_text()
  if re.search(r'(?:password|token|secret)=[^/\s]',text,re.I):raise ValueError('inline service credential requires explicit sanitization')
  write(Path('systemd')/source.name,text)
 caddy=(root/'config/Caddyfile').read_text()
 if re.search(r'(?im)^\s*(basic_auth|basicauth|tls\s+\S+\s+\S+)',caddy):raise ValueError('Caddy credential directive requires explicit sanitization')
 write(Path('runtime/config/Caddyfile'),caddy)
 write(Path('runtime/bin/corium-service'),(root/'bin/corium-service').read_bytes())
 corium=root/'corium/etc/corix/networks/ziokt-main/corix.conf'
 parser=configparser.ConfigParser(interpolation=None);parser.read(corium)
 for section in parser:
  for key,value in list(parser[section].items()):
   if SECRET.search(key) and not value.startswith('/') and key!='gpg_signing_key':parser[section][key]=redact(value,('corix.conf',section,key))
 import io
 text=io.StringIO();parser.write(text);write(Path('runtime/corium/etc/corix/networks/ziokt-main/corix.conf'),'\n'.join(line.rstrip() for line in text.getvalue().splitlines()).rstrip()+'\n')
 # UFS is configured outside the production root.
 ufs=Path.home()/'.config/dcpm-ufs/config.json'
 if ufs.is_file():json_file(ufs,Path('user-config/dcpm-ufs/config.json'))
 for path in output.rglob('*'):
  if path.is_file() and any(secret.encode() in path.read_bytes() for secret in secret_values):raise ValueError('secret material in final snapshot')
 manifest={'schema':'ziokt.deployment-config-snapshot.v1','kind':'SANITIZED_REFERENCE_NOT_PRIVATE_BACKUP','source_root':str(root),'files':{name:hashlib.sha256((output/name).read_bytes()).hexdigest() for name in files},'redacted_fields':omitted,'excluded':['admin_token.key','private identity/application/mailbox/transport keys','OAuth tokens and request databases','forum/chain/vault/business databases','TLS certificate storage','compiled binaries']}
 write(Path('SNAPSHOT.json'),json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 return {'files':len(files),'redacted_fields':len(omitted),'output':str(output),'contains_private_backup':False}

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();print(json.dumps(export(args.root,args.output)))

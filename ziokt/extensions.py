"""Ziokt metadata contracts through Shadow6's signed isolated Extensions pipeline."""
import hashlib
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .cli import write_exclusive, write_binary_exclusive
from .protocol import ProtocolError, encoded, identifier, secure_read, strict_json

FAMILIES = ('go','rust','gleam','ada','nim','idris')
SOURCES = ('Extension-System/shadow6_extensions.py','Crosed/crosedctl.py','Crosed/install_layout.py',
           'Crosed/feature_contract.py','Crosed/native_profiles.py','Deployment/service_storage.py',
           'Application-Layer/shadow_protocols.py','Plugin-System/shadow6_plugins.py','Slot-System/shadow6_slots.py')
PLUGIN = b'''import json,re,sys

def pairs(items):
    out={}
    for k,v in items:
        if k in out: raise ValueError('duplicate field')
        out[k]=v
    return out

def reject(_): raise ValueError('nonportable number')
r=json.loads(sys.stdin.buffer.readline(65537),object_pairs_hook=pairs,parse_float=reject,parse_constant=reject)
if set(r)-{'protocol','slot','level','payload','capabilities'} or r.get('protocol')!='shadow6.slot.v1' or r.get('slot')!='slot.security.policy': raise ValueError('slot rejected')
p=r['payload']
fields={'schema','kind','network_id','content_digest','hops','private','free_forwarding'}
if type(p) is not dict or set(p)!=fields or p['schema']!='ziokt.extension-event.v1' or p['kind'] not in ('zkn-gift','zkc-pack','peer-route'): raise ValueError('event rejected')
if type(p['network_id']) is not str or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,63}',p['network_id']): raise ValueError('network rejected')
if type(p['content_digest']) is not str or not re.fullmatch('sha256:[a-f0-9]{64}',p['content_digest']): raise ValueError('digest rejected')
if type(p['hops']) is not int or not 2<=p['hops']<=4 or p['private'] is not True or p['free_forwarding'] is not True: raise ValueError('privacy policy rejected')
print(json.dumps({'allow':True,'schema':'ziokt.extension-decision.v1','content_digest':p['content_digest']},sort_keys=True,separators=(',',':')))
'''


def sha(data): return 'sha256:'+hashlib.sha256(data).hexdigest()


def run_bounded(command, *, cwd=None, timeout=15, limit=65536):
    # Native scripts and subprocesses never inherit loader overrides or key data.
    env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','SYSTEMROOT'}}
    env['PYTHONDONTWRITEBYTECODE']='1'
    with tempfile.TemporaryFile() as output,tempfile.TemporaryFile() as errors:
        process=subprocess.Popen(command,stdout=output,stderr=errors,cwd=cwd,env=env,start_new_session=os.name=='posix')
        try: process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name=='posix':
                import signal
                os.killpg(process.pid,signal.SIGKILL)
            else: process.kill()
            process.wait();raise ProtocolError('EXTENSION_TIMEOUT','native extension exceeded deadline')
        output.seek(0);data=output.read(limit+1)
        if process.returncode or len(data)>limit: raise ProtocolError('EXTENSION_DENIED','native extension or installed feature probe denied')
    return strict_json(data,limit)


def artifact_digest(root,family):
    folder=Path(root)/('Core-'+family.capitalize())
    binary=folder/('shadow6-'+family+'-crosed')
    files=[binary]
    if family=='idris':
        files+=list(folder.glob('*.so'))+list(folder.glob('shadow6-idris*_app/*'))
    elif family=='nim':files+=list(folder.glob('*.so*'))
    files=sorted({p for p in files if p.is_file()},key=str)
    if len(files)>64:raise ProtocolError('INVALID_EXTENSION','bounded native runtime bundle required')
    return sha(encoded({str(p.relative_to(folder)):sha(secure_read(p,128*1024*1024,private=None)) for p in files}))


def feature_matrix(root):
    root=Path(root).absolute();rows=[]
    for family in FAMILIES:
        binary=root/('Core-'+family.capitalize())/('shadow6-'+family+'-crosed')
        row={'core':family,'binary':str(binary),'source_supported':True,'runtime_verified':False,'eligible':False}
        try:
            report=run_bounded([str(binary),'--feature-report'],timeout=5,limit=16384)
            row.update(runtime_verified=True,eligible=report.get('core')=='shadow6-'+family and report.get('crosed_max_level',0)>=3 and report.get('app_transport') is True and {'transport.application','policy.request'}<=set(report.get('crosed_capabilities',[])),feature_report=report,binary_digest=artifact_digest(root,family))
        except (OSError,ProtocolError): row['diagnostic']='matching enabled prebuilt Core required'
        rows.append(row)
    return rows


def install(root, output, private):
    """Create a separate operator-signed plugin bundle; no native tree mutations."""
    root=Path(root).absolute();output=Path(output).absolute()
    if output.exists(): raise ProtocolError('FILE_EXISTS','extension bundle requires a new directory')
    key=Ed25519PrivateKey.from_private_bytes(private)
    public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
    hashes={name:sha(secure_read(root/name,1024*1024,private=None)) for name in SOURCES}
    output.mkdir(mode=0o700,parents=True);plugin=output/'plugins/ziokt-policy';plugin.mkdir(mode=0o700,parents=True)
    write_binary_exclusive(plugin/'main.py',PLUGIN)
    manifest={'schema_version':1,'id':'ziokt-policy','name':'Ziokt private collectible policy','version':'1.0.0','runtime':'python3',
              'entrypoint':'main.py','capabilities':['slot.security.policy'],'hooks':['slot.security.policy'],
              'timeout_seconds':3,'max_output_bytes':4096,'sha256':hashlib.sha256(PLUGIN).hexdigest(),'signer':'ziokt-local'}
    import json
    canonical=json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
    write_exclusive(plugin/'plugin.json',{**manifest,'signature':key.sign(canonical).hex()})
    write_exclusive(output/'plugin-trust.json',{'signers':{'ziokt-local':public}})
    for family in FAMILIES:
        entry={'pubkey':public,'max_level':3,'capabilities':['transport.application','policy.request'],'allowed_domains':['ziokt']}
        trust={'mods':{'ziokt-policy':entry}}
        if family in {'gleam','ada','nim'}: entry['source_domain']='ziokt';trust['domain']='ziokt'
        if family=='idris': trust={'version':1,'mod_id':'ziokt-policy','pubkey':public,'max_level':3,'capabilities':entry['capabilities'],'allowed_domains':['green'],'source_domain':'green','target_domain':'green','domain_policies':[{'source':'green','target':'green','allowed':True}],'replay_path':str(output/'idris.replay')}
        write_exclusive(output/('crosed-trust-'+family+'.json'),trust)
    write_exclusive(output/'bindings.json',{'version':1,'bindings':[{'slot':'slot.security.policy','plugin':'ziokt-policy','priority':0,'required':True,'enabled':True}]})
    bundle_files={str(p.relative_to(output)):sha(secure_read(p,1024*1024)) for p in output.rglob('*') if p.is_file()}
    return {'schema':'ziokt.extension-bundle.v1','shadow6_root':str(root),'bundle':str(output),'sources':hashes,'files':bundle_files,'signer':public,'slot':'slot.security.policy'}


class Extensions:
    def __init__(self,binding,private,core,core_digest):
        fields={'schema','shadow6_root','bundle','sources','files','signer','slot'}
        if not isinstance(binding,dict) or set(binding)!=fields or binding['schema']!='ziokt.extension-bundle.v1' or binding['slot']!='slot.security.policy' or set(binding['sources'])!=set(SOURCES):
            raise ProtocolError('INVALID_EXTENSION','reviewed extension bundle required')
        if core not in FAMILIES or not re.fullmatch('sha256:[a-f0-9]{64}',core_digest): raise ProtocolError('INVALID_EXTENSION','supported pinned Core required')
        for name in ('shadow6_root','bundle'):
            if not isinstance(binding[name],str) or not Path(binding[name]).is_absolute() or '..' in Path(binding[name]).parts or Path(binding[name]).is_symlink(): raise ProtocolError('INVALID_EXTENSION','owned absolute extension roots required')
        self.binding=binding;self.private=private;self.core=core;self.core_digest=core_digest
        key=Ed25519PrivateKey.from_private_bytes(private)
        if key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()!=binding['signer']: raise ProtocolError('SIGNATURE_REJECTED','extension signer differs from bundle')

    def __call__(self,payload):
        strict_json(encoded(payload),8192)
        root=Path(self.binding['shadow6_root']);bundle=Path(self.binding['bundle'])
        core=root/('Core-'+self.core.capitalize())/('shadow6-'+self.core+'-crosed')
        files={'plugin-trust.json','bindings.json','plugins/ziokt-policy/main.py','plugins/ziokt-policy/plugin.json'}|{'crosed-trust-'+f+'.json' for f in FAMILIES}
        if not isinstance(self.binding['files'],dict) or set(self.binding['files'])!=files:raise ProtocolError('INVALID_EXTENSION','complete signed policy bundle pins required')
        for name in files:
            if sha(secure_read(bundle/name,1024*1024))!=self.binding['files'][name]:raise ProtocolError('STALE_PLAN','reviewed signed policy bundle changed')
        if artifact_digest(root,self.core)!=self.core_digest: raise ProtocolError('STALE_PLAN','extension Core binary changed')
        with tempfile.TemporaryDirectory(prefix='ziokt-extension-') as tmp:
            tree=Path(tmp);(tree/'Makefile').write_text('# pinned Python extension snapshot\n')
            for name in SOURCES:
                data=secure_read(root/name,1024*1024,private=None)
                if sha(data)!=self.binding['sources'][name]: raise ProtocolError('STALE_PLAN','extension source changed')
                target=tree/name;target.parent.mkdir(mode=0o700,parents=True,exist_ok=True);write_binary_exclusive(target,data)
            domain='green' if self.core=='idris' else 'ziokt'
            request={'version':1,'mod_id':'ziokt-policy','nonce':secrets.token_hex(16),'issued_at':int(time.time()),'requested_level':3,
                     'capabilities':['policy.request','transport.application'],'source_domain':domain,'target_domain':domain,
                     'payload':{'application':{'protocol':'shadow.extension','version':1,'slot':'slot.security.policy',
                              'source_domain':domain,'target_domain':domain,'payload':payload}}}
            signed='\n'.join([str(request['version']),request['mod_id'],request['nonce'],str(request['issued_at']),str(request['requested_level']),
                             ','.join(sorted(request['capabilities'])),hashlib.sha256(encoded(request['payload'])).hexdigest(),domain,domain]).encode()
            if self.core=='idris':
                signed=encoded({k:request[k] for k in ('version','mod_id','nonce','issued_at','requested_level','capabilities','source_domain','target_domain')} | {'payload_hash':hashlib.sha256(encoded(request['payload'])).hexdigest()})
            request['signature']=Ed25519PrivateKey.from_private_bytes(self.private).sign(signed).hex()
            write_exclusive(tree/'request.json',request)
            result=run_bounded([sys.executable,'-I',str(tree/SOURCES[0]),'--core',str(core),'--request',str(tree/'request.json'),
                '--crosed-trust',str(bundle/('crosed-trust-'+self.core+'.json')),'--bindings',str(bundle/'bindings.json'),
                '--plugin-root',str(bundle/'plugins'),'--plugin-trust',str(bundle/'plugin-trust.json')],timeout=15)
        if (result.get('protocol')!='shadow6.extension.v1' or result.get('core')!='shadow6-'+self.core or result.get('slot')!='slot.security.policy' or
                not isinstance(result.get('result'),dict) or not result['result'].get('results') or
                any(r.get('ok') is not True or r.get('result',{}).get('allow') is not True for r in result['result']['results'])):
            raise ProtocolError('EXTENSION_DENIED','complete signed extension grant required')
        return result


def load_extensions(path):
    value=strict_json(secure_read(path))
    if not isinstance(value,dict) or set(value)!={'schema','binding','signing_key','core','core_digest'} or value['schema']!='ziokt.extensions-use.v1':raise ProtocolError('INVALID_EXTENSION','exact explicit extension binding required')
    for name in ('binding','signing_key'):
        if not isinstance(value[name],str) or not Path(value[name]).is_absolute() or '..' in Path(value[name]).parts:raise ProtocolError('INVALID_EXTENSION','fixed private extension material paths required')
    return Extensions(strict_json(secure_read(value['binding'])),secure_read(value['signing_key'],32),value['core'],value['core_digest'])

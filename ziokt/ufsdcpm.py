"""Native UFS/DCPM coupling: signed packages stored in scoped encrypted UFS.

Network bytes never use pickle/eval. Installation is explicit file extraction,
without scripts, privilege changes or package-manager side effects.
"""
import base64
import hashlib
from pathlib import Path
import re
from .protocol import ProtocolError,encoded,strict_json
from .safefs import virtual_name,Vault
from .security import sign,verify

MAX_PACKAGE=4*1024*1024
DOMAIN='Ziokt/DCPM/package/v1'


def _label(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+\-]{0,127}',value):raise ProtocolError('INVALID_PACKAGE','bounded package label required')
    return value


def package_bytes(name,version,files,dependencies,private):
    _label(name);_label(version)
    if not isinstance(files,dict) or not 1<=len(files)<=128 or not isinstance(dependencies,list) or len(dependencies)>128:raise ProtocolError('PACKAGE_LIMIT','bounded files and dependencies required')
    dependencies=sorted({_label(item) for item in dependencies});entries=[];content={};total=0
    for path,data in sorted(files.items()):
        virtual_name(path)
        if not isinstance(data,bytes):raise ProtocolError('INVALID_PACKAGE','file bytes required')
        total+=len(data)
        if total>MAX_PACKAGE:raise ProtocolError('PACKAGE_LIMIT','package plaintext budget exceeded')
        digest=hashlib.sha256(data).hexdigest();entries.append({'path':path,'sha256':digest,'size':len(data)})
        content[path]=[base64.b64encode(data[i:i+3072]).decode() for i in range(0,len(data),3072)]
    paths=set(files)
    if any('/'.join(path.split('/')[:i]) in paths for path in paths for i in range(1,len(path.split('/')))):raise ProtocolError('INVALID_PACKAGE','file directory collision')
    manifest={'schema':'ziokt.dcpm-package.v1','name':name,'version':version,'dependencies':dependencies,'files':entries,'install_scripts':False}
    if len(encoded(manifest))>65536:raise ProtocolError('PACKAGE_LIMIT','signed manifest budget exceeded')
    return encoded({'manifest':sign(manifest,private,DOMAIN),'content':content})


def read_package(data,authority):
    if not isinstance(data,bytes) or len(data)>6*1024*1024:raise ProtocolError('PACKAGE_LIMIT','bounded package envelope required')
    envelope=strict_json(data,6*1024*1024)
    if not isinstance(envelope,dict) or set(envelope)!={'manifest','content'}:raise ProtocolError('INVALID_PACKAGE','exact package envelope required')
    manifest=verify(envelope['manifest'],authority,DOMAIN)
    if not isinstance(manifest,dict) or set(manifest)!={'schema','name','version','dependencies','files','install_scripts'} or manifest['schema']!='ziokt.dcpm-package.v1' or manifest['install_scripts'] is not False:raise ProtocolError('INVALID_PACKAGE','signed package schema required')
    _label(manifest['name']);_label(manifest['version'])
    deps=manifest['dependencies'];entries=manifest['files'];content=envelope['content']
    if not isinstance(deps,list) or len(deps)>128 or deps!=sorted({_label(v) for v in deps}) or not isinstance(entries,list) or not 1<=len(entries)<=128 or not isinstance(content,dict):raise ProtocolError('INVALID_PACKAGE','bounded canonical manifest required')
    files={};total=0
    for item in entries:
        if not isinstance(item,dict) or set(item)!={'path','sha256','size'}:raise ProtocolError('INVALID_PACKAGE','exact file descriptor required')
        path=virtual_name(item['path']);size=item['size'];chunks=content.get(path)
        if path in files or type(size) is not int or not 0<=size<=MAX_PACKAGE or not isinstance(chunks,list) or len(chunks)>1366 or any(not isinstance(c,str) or len(c)>4096 for c in chunks):raise ProtocolError('INVALID_PACKAGE','bounded file content required')
        try:blob=b''.join(base64.b64decode(c,validate=True) for c in chunks)
        except ValueError:raise ProtocolError('INVALID_PACKAGE','valid encoded content required')
        total+=len(blob)
        if total>MAX_PACKAGE or len(blob)!=size or hashlib.sha256(blob).hexdigest()!=item['sha256']:raise ProtocolError('PACKAGE_INTEGRITY','signed file integrity rejected')
        files[path]=blob
    if set(content)!=set(files) or any('/'.join(path.split('/')[:i]) in files for path in files for i in range(1,len(path.split('/')))):raise ProtocolError('INVALID_PACKAGE','exact noncolliding file set required')
    return manifest,files


class IntegratedStorage:
    def __init__(self,vault):
        if not isinstance(vault,Vault):raise ProtocolError('INVALID_PACKAGE','scoped UFS vault required')
        self.vault=vault
    def publish_package(self,name,version,files,dependencies,private,community=None):
        blob=package_bytes(name,version,files,dependencies,private)
        result=self.vault.put('packages/'+name+'/'+version+'.zpkg',blob)
        if community is not None:result={**result,'federation':self.vault.publish(community,private,result['digest'])}
        return {**result,'schema':'ziokt.ufs-dcpm-publication.v1','native_integration':True,'install_scripts':False}
    def download_package(self,digest,authority):
        _,blob=self.vault.get(digest);return read_package(blob,authority)

# V2 carries signed references, never Base64 file bodies. It uses the existing
# SafeFS chunk adapter and does not alter v1 admission or native trust policies.
REFERENCE_DOMAIN='Ziokt/DCPM/package-references/v2'
MAX_REFERENCE_PACKAGE=256*1024*1024
MAX_REFERENCE_FILE=64*1024*1024


def reference_package(store,name,version,files,dependencies,private):
    _label(name);_label(version)
    if not isinstance(files,dict) or not 1<=len(files)<=128 or not isinstance(dependencies,list) or len(dependencies)>128:
        raise ProtocolError('PACKAGE_LIMIT','bounded reference package required')
    paths=set(files)
    for path in paths:virtual_name(path)
    if any('/'.join(path.split('/')[:i]) in paths for path in paths for i in range(1,len(path.split('/')))):
        raise ProtocolError('INVALID_PACKAGE','file directory collision')
    entries=[];total=0
    for path,obj in sorted(files.items()):
        ref=store.reference(obj);total+=ref['length']
        if ref['length']>MAX_REFERENCE_FILE or total>MAX_REFERENCE_PACKAGE:
            raise ProtocolError('PACKAGE_LIMIT','reference package content quota exceeded')
        # Recheck the full object before binding it into a publisher signature.
        for _ in store.stream(obj):pass
        entries.append({'path':path,'object':obj,'sha256':ref['digest'],'size':ref['length'],'scope':ref['source']})
    manifest={'schema':'ziokt.dcpm-package.v2','name':name,'version':version,
              'dependencies':sorted({_label(dep) for dep in dependencies}),
              'files':entries,'install_scripts':False,'encoding':'identity'}
    data=encoded({'manifest':sign(manifest,private,REFERENCE_DOMAIN)})
    if len(data)>65536:raise ProtocolError('PACKAGE_LIMIT','signed reference manifest budget exceeded')
    return data


def reference_manifest(data,authority):
    """Verify a v2 publisher and metadata without requiring original payload storage.

    Installed, legally acquired files can be checked offline against this signed
    manifest. This is not an authorization to fetch or execute an object.
    """
    envelope=strict_json(data,65536)
    if not isinstance(envelope,dict) or set(envelope)!={'manifest'}:
        raise ProtocolError('INVALID_PACKAGE','exact reference package envelope required')
    manifest=verify(envelope['manifest'],authority,REFERENCE_DOMAIN)
    if (not isinstance(manifest,dict) or set(manifest)!={'schema','name','version','dependencies','files','install_scripts','encoding'} or
        manifest['schema']!='ziokt.dcpm-package.v2' or manifest['install_scripts'] is not False or manifest['encoding']!='identity'):
        raise ProtocolError('INVALID_PACKAGE','signed v2 reference package required')
    _label(manifest['name']);_label(manifest['version'])
    deps=manifest['dependencies'];entries=manifest['files']
    if not isinstance(deps,list) or len(deps)>128 or deps!=sorted({_label(dep) for dep in deps}) or not isinstance(entries,list) or not 1<=len(entries)<=128:
        raise ProtocolError('INVALID_PACKAGE','bounded canonical package entries required')
    paths=set();total=0
    for entry in entries:
        if not isinstance(entry,dict) or set(entry)!={'path','object','sha256','size','scope'}:
            raise ProtocolError('INVALID_PACKAGE','exact content reference entry required')
        path=virtual_name(entry['path'])
        if path in paths or any(path.startswith(p+'/') or p.startswith(path+'/') for p in paths):
            raise ProtocolError('INVALID_PACKAGE','duplicate or colliding content paths')
        paths.add(path)
        for field in ('object','sha256'):
            if not isinstance(entry[field],str) or not re.fullmatch('sha256:[a-f0-9]{64}',entry[field]):
                raise ProtocolError('PACKAGE_INTEGRITY','canonical digest required')
        _label(entry['scope'])
        if type(entry['size']) is not int or not 0<=entry['size']<=MAX_REFERENCE_FILE:
            raise ProtocolError('PACKAGE_LIMIT','reference file budget exceeded')
        total+=entry['size']
        if total>MAX_REFERENCE_PACKAGE:raise ProtocolError('PACKAGE_LIMIT','reference package content quota exceeded')
    return manifest


def verify_reference_package(store,data,authority,*,verify_content=True):
    manifest=reference_manifest(data,authority)
    total=0
    for entry in manifest['files']:
        ref=store.reference(entry['object'])
        if entry['size']!=ref['length'] or entry['sha256']!=ref['digest'] or entry['scope']!=ref['source']:
            raise ProtocolError('PACKAGE_INTEGRITY','signed object metadata differs from verified storage')
        total+=entry['size']
        if verify_content:
            for _ in store.stream(entry['object']):pass
    return {'schema':'ziokt.package-verification.v2','manifest':manifest,'publisher':authority,
            'files_verified':len(manifest['files']) if verify_content else 0,'content_verified':verify_content,'content_bytes':total,'installation_authorized':False,
            'execution_authorized':False,'native_signature_verified':False}

"""Trusted publication through the real native dCPM engine and existing objects."""
from contextlib import contextmanager, closing
import hashlib
import importlib
import json
from pathlib import Path
import secrets
import sys
import threading
from ziokt.protocol import secure_read,strict_json
from ziokt.security import sign
from ziokt.ufsdcpm import reference_package
from .state import Error,encoded

IMPORT_LOCK=threading.RLock()


def source_digest(root):
    h=hashlib.sha256();root=Path(root)
    paths=sorted(root.glob('*.py'))
    if not 1<=len(paths)<=256:raise Error('NATIVE_SOURCE','Native source tree is unavailable',503)
    for path in paths:
        if path.is_symlink() or not path.is_file():raise Error('NATIVE_SOURCE','Native source file is not regular',503)
        h.update(path.name.encode()+b'\0'+path.read_bytes()+b'\0')
    return 'sha256:'+h.hexdigest()


def configure(root,source):
    from .cli import private_write
    root=Path(root);source=Path(source).resolve()
    key=root/'release.key'
    if not key.exists():private_write(key,secrets.token_bytes(32))
    settings=strict_json(secure_read(root/'controller.json',65536),65536)
    settings['release']={'schema':'openci.native-dcpm.v1','source_root':str(source),'source_digest':source_digest(source),'signing_key':str(key),'root':str(root/'native-dcpm')}
    private_write(root/'controller.json',settings,replace=True)
    return {'state':'release_configured','publisher':sign({},secure_read(key,32),'OpenCI/publisher/v1')['public_key'],'source_digest':settings['release']['source_digest']}


def native_type(settings):
    root=Path(settings['source_root'])
    if source_digest(root)!=settings['source_digest']:raise Error('NATIVE_SOURCE_CHANGED','Operator must approve the changed native engine before publishing',503)
    with IMPORT_LOCK:
        for name in ('dcpm_core','dcpm_safe','dcpm_ufs_packages','dcpm_file_install','ufs_http_security'):
            module=sys.modules.get(name)
            if module is not None and Path(module.__file__).resolve().parent!=root:
                raise Error('NATIVE_MODULE_CONFLICT','Another native engine version is loaded',503)
        sys.path.insert(0,str(root))
        try:return importlib.import_module('dcpm_ufs_packages').PackageStore
        finally:sys.path.pop(0)


class ReleaseService:
    def __init__(self,controller):
        self.controller=controller
        self.state=controller.state;self.fabric=controller.fabric
        document=strict_json(secure_read(controller.config,65536),65536)
        settings=document.get('release')
        if not isinstance(settings,dict) or set(settings)!={'schema','source_root','source_digest','signing_key','root'} or settings['schema']!='openci.native-dcpm.v1':
            raise Error('RELEASE_NOT_CONFIGURED','Owner-controlled native signer must be configured explicitly',409)
        self.settings=settings;self.native=native_type(settings)
        self.private=secure_read(settings['signing_key'],32)
        if len(self.private)!=32:raise Error('RELEASE_KEY','Invalid native publisher key',503)
        self.public=sign({},self.private,'OpenCI/publisher/v1')['public_key']

    @contextmanager
    def store(self,project):
        from .state import identifier
        identifier(project)
        with self.fabric.store('openci-'+project) as objects:
            native=self.native(Path(self.settings['root'])/project,signing_key=self.settings['signing_key'],reference_store=objects)
            try:yield native,objects
            finally:native.close()

    def put(self,owner,value,mime):
        raw=value if isinstance(value,bytes) else encoded(value).encode()
        digest='sha256:'+hashlib.sha256(raw).hexdigest();upload='release-'+secrets.token_hex(16)
        self.fabric.begin(owner,upload,len(raw),digest,mime)
        for position,start in enumerate(range(0,len(raw),16384)):self.fabric.put(owner,upload,position,raw[start:start+16384])
        result=self.fabric.finish(owner,upload)
        return {'object':result['id'],'digest':digest}

    def publish(self,actor,pid,task_id,name,version):
        pipeline=self.state.inspect(pid)
        task=next((entry for entry in pipeline['tasks'] if entry['id']==task_id),None)
        if not task or not task['verification'] or task['verification'].get('status')!='matched':
            raise Error('RELEASE_NOT_VERIFIED','Independent output verification is required',409)
        files=self.controller.check_outputs(pipeline,task_id)
        if not files or len(files)>127:raise Error('RELEASE_ARTIFACT_SET','A native artifact set with at most 127 payload files is required',409)
        if any(entry['path']=='provenance.json' for entry in files):raise Error('RELEASE_PATH','provenance.json is reserved for native build evidence',409)
        verifier=next((entry for entry in pipeline['tasks'] if entry['id']==task['verification']['independent_task']),None)
        if not verifier or verifier['state']!='completed' or verifier['receipt']['artifact']['digest']!=task['receipt']['artifact']['digest']:
            raise Error('RELEASE_VERIFIER','Verified Trusted Worker output is no longer available',409)
        self.controller.check_outputs(pipeline,verifier['id'])
        spec=self.state.task_spec(pid,task_id)
        with closing(self.state.connect()) as db:source=json.loads(db.execute('SELECT body FROM pipelines WHERE id=?',(pid,)).fetchone()[0])['source']
        request={'schema':'openci.release-request.v1','pipeline':pid,'task':task_id,'project':pipeline['project'],
                 'name':name,'version':version,'publisher':self.public,'source':source,'image':spec['image'],
                 'argv':spec['argv'],'files':files,'trusted_worker':verifier['worker'],'verification_task':verifier['id'],
                 'artifact_set':verifier['receipt']['artifact']}
        attestations=[entry['attestation'] for entry in (task,verifier) if entry.get('attestation')]
        if attestations:request['worker_attestations']=attestations
        prepared=self.state.prepare_release(actor,pid,task_id,name,version,self.public,request)
        if prepared['state']!='prepared':return self.state.release(prepared['id'])
        owner='openci-'+pipeline['project']
        provenance={'_type':'https://in-toto.io/Statement/v1','subject':[{'name':entry['path'],'digest':{'sha256':entry['reference']['digest'][7:]}} for entry in files],
            'predicateType':'https://slsa.dev/provenance/v1','predicate':{'buildDefinition':{'buildType':'https://ziokt.org/openci/oci/v1','externalParameters':{'source':source,'image':spec['image'],'argv':spec['argv']},'resolvedDependencies':[{'uri':'native-content:'+source['object'],'digest':{'sha256':source['digest'][7:]}}]},
            'runDetails':{'builder':{'id':'openci-publisher:'+self.public},'metadata':{'invocationId':pid+'/'+task_id},'byproducts':[]}},
            'openciVerification':{'trusted_worker':verifier['worker'],'independent_task':verifier['id'],**({'worker_attestations':request['worker_attestations']} if 'worker_attestations' in request else {}),'software_security_verified':False,'reproducibility_across_hosts_verified':False}}
        provenance_ref=self.put(owner,provenance,'application/vnd.in-toto+json')
        entries={}
        for entry in files:
            if entry['path']=='provenance.json':raise Error('RELEASE_PATH','provenance.json is reserved for native build evidence',409)
            entries[entry['path']]=self.controller.content_reference(owner,entry['reference'])['reference']
        entries['provenance.json']=self.controller.content_reference(owner,provenance_ref)['reference']
        with self.store(pipeline['project']) as (native,objects):
            blob=reference_package(objects,name,version,entries,[],self.private)
            publication=native.admit(blob)
            if native.blob(publication['package_id'],publication['version_id'])!=blob:
                raise Error('NATIVE_PUBLICATION','Native registry did not return the signed package',503)
        package_ref=self.put(owner,blob,'application/vnd.ziokt.dcpm-package+json')
        try:
            package_event_body={
                'package_id':publication['package_id'],
                'version_id':publication['version_id'],
                'name':name,
                'version':version,
                'publisher':self.public,
                'package_reference':package_ref,
                'provenance_reference':provenance_ref,
                'files':files
            }
            self.fabric.publish_package(owner,name,version,package_event_body,visibility='public')
        except Exception:
            pass
        result={**publication,'package_reference':package_ref,'provenance_reference':provenance_ref,
                'visibility':'project-authorized','network_published':False,'release_signed':True,
                'installed':False,'activated':False,'execution_authorized':False,'corium_settled':False}
        return self.state.complete_release(actor,prepared['id'],result)

    def install(self,rid,root,*,activate=False):
        release=self.state.release(rid)
        if release['state']!='published':raise Error('RELEASE_STATE','Current published release required',409)
        publication=release['publication']
        with self.store(release['project']) as (native,_):
            installer=native.file_installer(root)
            result=installer.install(publication['package_id'],publication['version_id'],allow=True)
            if activate:result=installer.activate(publication['package_id'],publication['version_id'],allow=True)
        return result

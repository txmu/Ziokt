"""Architecture-bound, object-only C compilation for bounded browser Workers."""
import hashlib
import json
from pathlib import Path
import platform
import re
from contextlib import closing
from .state import Error
from ziokt.protocol import secure_read, strict_json


def architecture(value=None):
    value=(value or platform.machine()).lower()
    result={'amd64':'x86_64','x86_64':'x86_64','arm64':'aarch64','aarch64':'aarch64'}.get(value)
    if result is None:raise Error('LIGHT_ARCH_UNSUPPORTED','Light compilation requires a supported 64-bit architecture',409)
    return result


def validate_task(task):
    argv=task['argv']
    if (len(argv)!=4 or argv[0]!='light-c' or argv[1] not in {'x86_64','aarch64'}
            or argv[2]!='unit.i' or argv[3]!='unit.o' or task['outputs']!=['unit.o']
            or task['cpu']!=1 or task['memory_mb']!=64 or task['timeout']>20
            or not task['image'].startswith('openci/tcc-wasm-'+argv[1]+'@sha256:')):
        raise Error('LIGHT_TASK_PROFILE','Object-only, bounded C translation unit profile required')


def settings(controller):
    value=strict_json(secure_read(controller.config,65536),65536).get('light_compile')
    if (not isinstance(value,dict) or not {'compiler_root','manifest_sha256','cross_compile'}<=set(value) or set(value)-{'compiler_root','manifest_sha256','cross_compile','controller_origin'}
            or type(value['cross_compile']) is not bool
            or not re.fullmatch('[a-f0-9]{64}',value['manifest_sha256'])):
        raise Error('LIGHT_NOT_CONFIGURED','Operator-pinned lightweight compiler is not configured',503)
    root=Path(value['compiler_root'])
    if not root.is_absolute() or root.is_symlink():raise Error('LIGHT_COMPILER_PATH','Fixed compiler directory required',503)
    raw=secure_read(root/'manifest.json',65536,private=None)
    if hashlib.sha256(raw).hexdigest()!=value['manifest_sha256']:raise Error('LIGHT_COMPILER_INTEGRITY','Compiler manifest pin changed',503)
    manifest=strict_json(raw,65536)
    if manifest.get('schema')!='openci.light-compiler.v1':raise Error('LIGHT_COMPILER_SCHEMA','Compiler manifest schema rejected',503)
    node=architecture()
    targets={k:v for k,v in manifest['targets'].items() if k==node or value['cross_compile']}
    return root,{'schema':'openci.light-admission.v1','node_arch':node,'targets':targets,
                 'input_bytes':131072,'output_bytes':1048576,'memory_bytes':67108864,
                 'timeout_seconds':20,'cross_compile':value['cross_compile'],
                 'controller_origin':value.get('controller_origin'),
                 'architecture_hardware_attested':False,'execute_task_code':False,
                 'independent_verification_required':True}


def asset(controller,name):
    root,config=settings(controller)
    if name not in {arch+extension for arch in config['targets'] for extension in ('.js','.wasm')}:
        raise Error('LIGHT_ASSET_NOT_FOUND','Approved compiler target required',404)
    arch=name.rsplit('.',1)[0]
    data=secure_read(root/name,8*1024*1024,private=None)
    if hashlib.sha256(data).hexdigest()!=config['targets'][arch]['files'][name]:
        raise Error('LIGHT_COMPILER_INTEGRITY','Compiler asset differs from its approved manifest',503)
    return data,'application/wasm' if name.endswith('.wasm') else 'text/javascript; charset=utf-8'


def claim(controller,principal,body):
    if principal['role']!='worker':raise Error('WORKER_REQUIRED','Dedicated worker identity required',403)
    if type(body) is not dict or set(body)!={'architecture'}:raise Error('LIGHT_FIELDS','Detected client architecture required')
    _,config=settings(controller)
    actual=architecture(body['architecture'])
    if actual!=config['node_arch']:raise Error('LIGHT_ARCH_MISMATCH','Client and connected node architecture must match',409)
    worker=principal['worker']
    with closing(controller.state.connect()) as db:
        row=db.execute('SELECT arch FROM workers WHERE id=? AND enabled=1',(worker,)).fetchone()
        profile=db.execute('SELECT images FROM worker_build_profiles WHERE worker=?',(worker,)).fetchone()
        key=db.execute('SELECT public FROM worker_receipt_keys WHERE worker=?',(worker,)).fetchone()
    if not row or row['arch']!=actual or not profile or not key:
        raise Error('LIGHT_ADMISSION_REQUIRED','Matching approved worker, compiler profile and signing identity required',403)
    approved=set(json.loads(profile['images']))
    images={item['image'] for item in config['targets'].values()}&approved
    if not images:raise Error('LIGHT_COMPILER_UNAPPROVED','Operator must approve this worker for the pinned compiler',403)
    from .quorum import presence
    presence(controller.state,worker,sorted(images))
    result=controller.state.claim(worker,executor='light-c',images=images)
    return {'assignment':result,'node_arch':actual,'architecture_hardware_attested':False}


def check_result(controller,pipeline,task_id,artifact):
    """Check declared native object shape before admitting a signed completion."""
    from .artifacts import validate_set
    spec=controller.state.task_spec(pipeline['pipeline'],task_id)
    if spec.get('executor')!='light-c':return
    validate_task(spec)
    owner='openci-'+pipeline['project']
    row=controller.content_reference(owner,artifact)
    if json.loads(row['metadata'])['size']>65536:raise Error('LIGHT_ARTIFACT_LIMIT','Small artifact set required',413)
    with controller.fabric.store(owner) as store:raw=b''.join(store.stream(row['reference']))
    with closing(controller.state.connect()) as db:
        source=json.loads(db.execute('SELECT body FROM pipelines WHERE id=?',(pipeline['pipeline'],)).fetchone()['body'])['source']
    doc=validate_set(strict_json(raw,65536),source=source,image=spec['image'],required=['unit.o'])
    entry=doc['files'][0]
    if not 64<=entry['size']<=1048576:raise Error('LIGHT_OBJECT_LIMIT','Bounded ELF object required')
    obj=controller.content_reference(owner,entry['reference'])
    if json.loads(obj['metadata'])['size']!=entry['size']:raise Error('LIGHT_OBJECT_SIZE','Declared object size differs')
    controller.fabric.verify_object(owner,entry['reference']['object'])
    with controller.fabric.store(owner) as store:
        head=next(iter(store.stream(obj['reference'])))[:64]
    if (head[:6]!=b'\x7fELF\x02\x01' or int.from_bytes(head[16:18],'little')!=1
            or int.from_bytes(head[18:20],'little')!=({'x86_64':62,'aarch64':183}[spec['argv'][1]])):
        raise Error('LIGHT_OBJECT_ARCH','Native object architecture or format differs from assignment',409)


def check_source(controller,owner,reference):
    row=controller.content_reference(owner,reference)
    if json.loads(row['metadata'])['size']>262144:raise Error('LIGHT_SOURCE_LIMIT','Bounded translation unit required',413)
    with controller.fabric.store(owner) as store:raw=b''.join(store.stream(row['reference']))
    doc=strict_json(raw,262144,string_limit=131072)
    if (type(doc) is not dict or set(doc)!={'schema','name','source'}
            or doc['schema']!='openci.light-source.v1' or doc['name']!='unit.i'
            or type(doc['source']) is not str or '\0' in doc['source']
            or len(doc['source'].encode())>131072):
        raise Error('LIGHT_SOURCE_PROFILE','Exact bounded preprocessed C source required')

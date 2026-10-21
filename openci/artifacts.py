"""Versioned artifact sets reference native objects, never duplicate payloads in a tar."""
import hashlib
import json
from pathlib import Path,PurePosixPath
import tarfile
from .state import Error,IMAGE,reference

SCHEMA='openci.artifact-set.v1'
MIME='application/vnd.openci.artifact-set+json'


def output_path(value):
    if not isinstance(value,str) or not value or len(value)>1024 or '\\' in value or value.startswith('/') or '..' in value.split('/') or str(PurePosixPath(value))!=value or value=='.':
        raise Error('ARTIFACT_PATH','Canonical relative output file path required',409)
    return value


def validate_set(value,*,source=None,image=None,required=None):
    if not isinstance(value,dict) or set(value)!={'schema','source','image','files'} or value['schema']!=SCHEMA:
        raise Error('ARTIFACT_SCHEMA','Versioned native artifact set required',409)
    reference(value['source'])
    if not isinstance(value['image'],str) or not IMAGE.fullmatch(value['image']):raise Error('ARTIFACT_IMAGE','Immutable toolchain image required',409)
    if source is not None and source!=value['source'] or image is not None and image!=value['image']:
        raise Error('ARTIFACT_INPUTS','Artifact source or image differs from assigned task',409)
    if not isinstance(value['files'],list) or len(value['files'])>128:raise Error('ARTIFACT_LIMIT','Bounded artifact set required',409)
    paths=set();total=0
    for entry in value['files']:
        if not isinstance(entry,dict) or set(entry)!={'path','reference','size'}:raise Error('ARTIFACT_SCHEMA','Exact artifact file fields required',409)
        path=output_path(entry['path']);reference(entry['reference'])
        if path in paths or any(path.startswith(other+'/') or other.startswith(path+'/') for other in paths):raise Error('ARTIFACT_PATH','Duplicate or colliding paths',409)
        paths.add(path)
        if type(entry['size']) is not int or not 0<=entry['size']<=64*1024*1024:raise Error('ARTIFACT_LIMIT','File size outside native profile',409)
        total+=entry['size']
    if total>64*1024*1024:raise Error('ARTIFACT_LIMIT','Artifact set exceeds Runner output budget',409)
    if required is not None and set(required)!=paths:raise Error('OUTPUT_MISSING','Artifact set differs from declared outputs',409)
    return value


def publish_outputs(client,project,archive,required,source,image):
    """The temporary archive transports live tmpfs bytes only on the Worker.

    Payload files are uploaded exactly once into Content Fabric. The retained
    set is a small manifest of those existing objects, not another payload copy.
    """
    selected={output_path(name) for name in required};files=[]
    with tarfile.open(archive,'r:') as members:
        for member in members:
            path=str(PurePosixPath(member.name))
            if not member.isfile() or path not in selected:continue
            with members.extractfile(member) as content:
                digest='sha256:'+hashlib.file_digest(content,'sha256').hexdigest()
                content.seek(0)
                ref=client.upload_stream(project,content,member.size,digest)
            files.append({'path':path,'reference':ref,'size':member.size})
    value=validate_set({'schema':SCHEMA,'source':source,'image':image,'files':sorted(files,key=lambda item:item['path'])},source=source,image=image,required=required)
    payload=json.dumps(value,sort_keys=True,separators=(',',':')).encode()
    import io
    return client.upload_stream(project,io.BytesIO(payload),len(payload),'sha256:'+hashlib.sha256(payload).hexdigest(),mime=MIME)

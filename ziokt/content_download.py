"""Bounded HTTP Range download with private crash checkpoints and final SHA-256."""
import hashlib,json,os,re,secrets,shutil,ssl
from pathlib import Path
from urllib.request import Request,build_opener,HTTPSHandler
from .content_server import remote,NoRedirect
from .protocol import secure_read


def _sync_directory(path):
 fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
 try:os.fsync(fd)
 finally:os.close(fd)


def _checkpoint(path,value):
 temporary=path.with_name(path.name+'.'+secrets.token_hex(8))
 try:
  fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'w') as stream:json.dump(value,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
  os.replace(temporary,path);_sync_directory(path.parent)
 finally:
  if temporary.exists():temporary.unlink()


def download_file(peer,oid,output,*,max_bytes=512*1024*1024,max_segments=None,segment_bytes=1024*1024):
 if not isinstance(oid,str) or not re.fullmatch(r'cf1-[a-f0-9]{64}',oid):raise ValueError('object ID')
 if type(segment_bytes) is not int or not 16384<=segment_bytes<=1024*1024:raise ValueError('segment bound')
 if max_segments is not None and (type(max_segments) is not int or max_segments<1):raise ValueError('segment budget')
 metadata=remote(peer,{'operation':'content.object.info','arguments':{'id':oid}})
 size=metadata['size'];digest=metadata['digest']
 if type(size) is not int or not 0<=size<=max_bytes or not isinstance(digest,str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',digest):raise ValueError('download metadata/budget')
 output=Path(output).absolute();part=output.with_name(output.name+'.ziokt-part');checkpoint=output.with_name(output.name+'.ziokt-checkpoint.json')
 for path in (output,part,checkpoint):
  if path.is_symlink():raise ValueError('download symlink')
  if path.exists() and (path.stat().st_uid!=os.getuid() or path.stat().st_mode&0o077):raise ValueError('download file must be private and owner-controlled')
 if output.exists():
  with output.open('rb') as stream:actual='sha256:'+hashlib.file_digest(stream,'sha256').hexdigest()
  if output.stat().st_size!=size or actual!=digest:raise ValueError('destination already exists with different bytes')
  return {'complete':True,'duplicate':True,'output':str(output),'size':size,'digest':digest}
 state={'schema':'ziokt.http-range-checkpoint.v1','url':peer['url'],'id':oid,'size':size,'digest':digest,'offset':0,'prefix_sha256':hashlib.sha256().hexdigest()}
 if checkpoint.exists():
  previous=json.loads(secure_read(checkpoint,8192))
  if set(previous)!=set(state) or any(previous[k]!=state[k] for k in ('schema','url','id','size','digest')):raise ValueError('checkpoint object mismatch')
  if type(previous['offset']) is not int or not 0<=previous['offset']<=size:raise ValueError('checkpoint offset')
  state=previous
 elif part.exists() and part.stat().st_size:raise ValueError('partial file has no checkpoint')
 if not part.exists() and state['offset']:raise ValueError('checkpoint bytes missing')
 flags=os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW
 fd=os.open(part,flags,0o600)
 with os.fdopen(fd,'r+b') as stream:
  if os.fstat(stream.fileno()).st_size<state['offset']:raise ValueError('checkpoint bytes truncated')
  prefix=hashlib.sha256();remaining=state['offset']
  while remaining:
   block=stream.read(min(65536,remaining));prefix.update(block);remaining-=len(block)
  if prefix.hexdigest()!=state['prefix_sha256']:raise ValueError('partial file integrity mismatch')
  stream.truncate(state['offset']);stream.flush();os.fsync(stream.fileno());_checkpoint(checkpoint,state)
  if shutil.disk_usage(output.parent).free<size-state['offset']+16*1024*1024:raise ValueError('download disk headroom')
  opener=build_opener(NoRedirect(),HTTPSHandler(context=ssl.create_default_context(cafile=peer.get('ca'))));segments=0
  while state['offset']<size and (max_segments is None or segments<max_segments):
   start=state['offset'];end=min(size-1,start+segment_bytes-1);headers={'Range':f'bytes={start}-{end}'}
   if peer.get('token'):headers['Authorization']='Bearer '+peer['token']
   with opener.open(Request(peer['url'].rstrip('/')+'/objects/'+oid,headers=headers),timeout=20) as response:
    if response.status!=206 or response.headers.get('Content-Range')!=f'bytes {start}-{end}/{size}' or response.headers.get('Content-Length')!=str(end-start+1):raise ValueError('invalid Range response')
    remaining=end-start+1;segment_hash=prefix.copy()
    while remaining:
     block=response.read(min(65536,remaining))
     if not block:raise ValueError('incomplete Range response; resume using the checkpoint')
     stream.write(block);segment_hash.update(block);remaining-=len(block)
    if response.read(1):raise ValueError('oversized Range response')
   stream.flush();os.fsync(stream.fileno());prefix=segment_hash;state.update(offset=end+1,prefix_sha256=prefix.hexdigest());_checkpoint(checkpoint,state);segments+=1
  if state['offset']!=size:return {'complete':False,'received_bytes':state['offset'],'size':size,'checkpoint':str(checkpoint)}
  if 'sha256:'+prefix.hexdigest()!=digest:raise ValueError('final object digest mismatch; partial bytes retained for investigation')
 os.link(part,output);_sync_directory(output.parent);part.unlink();checkpoint.unlink();_sync_directory(output.parent)
 return {'complete':True,'output':str(output),'size':size,'digest':digest,'verified':True}

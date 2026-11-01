"""Crash-safe checkpoint generations; never mutates running native chain databases."""
import contextlib,fcntl,json,os,re,shutil,stat,tempfile,zipfile
from pathlib import Path
from .checkpoint_format import canonical,verify,hexid,require,CheckpointError,CHUNK,MAX_BYTES
MAX_TOTAL=4*MAX_BYTES

def read_private(path,limit):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  info=os.fstat(fd);require(stat.S_ISREG(info.st_mode)and info.st_uid==os.getuid()and not info.st_mode&0o077 and info.st_nlink==1 and info.st_size<=limit,'private regular checkpoint file required');data=os.read(fd,limit+1);require(len(data)==info.st_size,'checkpoint file changed during read');return data
 finally:os.close(fd)

def sync_directory(path):
 fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
 try:os.fsync(fd)
 finally:os.close(fd)

def write_new(path,data):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 try:
  with os.fdopen(fd,'wb',closefd=False)as stream:stream.write(data);stream.flush();os.fsync(fd)
 finally:os.close(fd)

def decode_manifest(raw):
 def unique(pairs):
  out={}
  for key,value in pairs:
   require(key not in out,'duplicate checkpoint manifest field');out[key]=value
  return out
 return json.loads(raw.decode('utf-8'),object_pairs_hook=unique)

class CheckpointStore:
 def __init__(self,root,expected,signers):
  self.root=Path(root).absolute();require(not self.root.is_symlink(),'checkpoint store symlink rejected');self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
  info=self.root.stat();require(info.st_uid==os.getuid()and not info.st_mode&0o077,'private owner checkpoint store required');self.expected=expected;self.signers=signers
  self.generations=self.root/'generations';self.generations.mkdir(exist_ok=True,mode=0o700);self.private_directory(self.generations)
 def private_directory(self,path):
  info=path.lstat();require(stat.S_ISDIR(info.st_mode)and info.st_uid==os.getuid()and not info.st_mode&0o077,'private owner checkpoint directory required')
 @contextlib.contextmanager
 def writer(self):
  fd=os.open(self.root/'writer.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
  try:
   info=os.fstat(fd);require(stat.S_ISREG(info.st_mode)and info.st_uid==os.getuid()and info.st_nlink==1 and not info.st_mode&0o077,'private regular checkpoint writer required');fcntl.flock(fd,fcntl.LOCK_EX);yield
  finally:os.close(fd)
 def verify_generation(self,directory,allow_bootstrap=False):
  self.private_directory(directory);self.private_directory(directory/'objects')
  manifest=decode_manifest(read_private(directory/'manifest.json',2*1024*1024))
  def read(identity):return read_private(directory/'objects'/(hexid(identity)+'.chunk'),CHUNK)
  return verify(manifest,self.expected,self.signers,read,allow_bootstrap=allow_bootstrap)
 def current(self,allow_bootstrap=False):
  # Resolve the pointer exactly once: concurrent publication cannot mix role states.
  target=os.readlink(self.root/'current');require(re.fullmatch(r'generations/[a-f0-9]{64}',target),'invalid checkpoint generation pointer');directory=self.root/target
  return self.verify_generation(directory,allow_bootstrap)
 def publish(self,manifest,objects,*,allow_bootstrap=False):
  require(type(objects)is dict and len(objects)<=MAX_TOTAL//CHUNK+128,'checkpoint object count budget');require(sum(len(value)for value in objects.values())<=MAX_TOTAL,'checkpoint aggregate byte budget')
  with self.writer(),tempfile.TemporaryDirectory(prefix='.pending-',dir=self.root)as temporary:
   stage=Path(temporary);(stage/'objects').mkdir(mode=0o700)
   write_new(stage/'manifest.json',canonical(manifest))
   for identity,data in objects.items():require(type(data)is bytes and len(data)<=CHUNK,'checkpoint chunk budget');write_new(stage/'objects'/(hexid(identity)+'.chunk'),data)
   value=self.verify_generation(stage,allow_bootstrap);identity=value.manifest['snapshot_hash'];destination=self.generations/identity
   sync_directory(stage/'objects');sync_directory(stage)
   if destination.exists():self.verify_generation(destination,allow_bootstrap)
   else:
    os.replace(stage,destination);sync_directory(self.generations)
    # TemporaryDirectory cleanup is harmless after moving its private staging path.
   self._activate(identity)
   return value
 def _activate(self,identity):
  pointer=self.root/('.current-'+hexid(identity))
  require(not pointer.exists()and not pointer.is_symlink(),'unfinished checkpoint pointer retained for inspection')
  os.symlink('generations/'+identity,pointer)
  try:os.replace(pointer,self.root/'current');sync_directory(self.root)
  finally:pointer.unlink(missing_ok=True)
 def activate(self,identity,*,allow_bootstrap=False):
  with self.writer():
   value=self.verify_generation(self.generations/hexid(identity),allow_bootstrap);self._activate(identity);return value
 def import_bundle(self,path,*,allow_bootstrap=False):
  # Archive paths are names in a fixed object namespace, never extraction targets.
  with zipfile.ZipFile(path)as archive:
   entries=archive.infolist();require(len(entries)<=MAX_TOTAL//CHUNK+129 and len({e.filename for e in entries})==len(entries),'bounded unique checkpoint archive required');require(sum(e.file_size for e in entries)<=MAX_TOTAL+2*1024*1024,'checkpoint expansion budget')
   names=[]
   for entry in entries:
    require(entry.filename=='manifest.json'or re.fullmatch(r'objects/[a-f0-9]{64}\.chunk',entry.filename),'checkpoint archive path rejected');require(not entry.is_dir()and stat.S_IFMT(entry.external_attr>>16)in {0,stat.S_IFREG},'regular checkpoint members required');require(entry.file_size<=(2*1024*1024 if entry.filename=='manifest.json'else CHUNK),'checkpoint member budget');names.append(entry.filename)
   require('manifest.json'in names,'checkpoint manifest missing');manifest=decode_manifest(archive.read('manifest.json'));objects={name.split('/')[1][:-6]:archive.read(name)for name in names if name!='manifest.json'}
   return self.publish(manifest,objects,allow_bootstrap=allow_bootstrap)

def export_bundle(path,manifest,objects):
 path=Path(path);require(not path.exists()and not path.is_symlink(),'new checkpoint bundle path required')
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb')as output:
  with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6)as archive:
   archive.writestr('manifest.json',canonical(manifest))
   for identity,data in sorted(objects.items()):archive.writestr('objects/'+hexid(identity)+'.chunk',data)
  output.flush();os.fsync(output.fileno())
 sync_directory(path.parent)

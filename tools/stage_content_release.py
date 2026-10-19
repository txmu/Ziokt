#!/usr/bin/env python3
"""Stage committed Content runtime sources, verify hashes, optionally switch current.

This command never copies local credentials or state and never restarts services.
"""
import argparse,hashlib,json,os,re,secrets,shutil,subprocess,tarfile,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def verify(directory,revision):
 if any(path.is_symlink() for path in directory.rglob('*')):raise ValueError('release symlink')
 manifest=json.loads((directory/'RELEASE.json').read_text())
 if manifest.get('revision')!=revision:raise ValueError('release revision mismatch')
 actual={str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file() and p!=directory/'RELEASE.json'}
 if actual!=set(manifest['files']):raise ValueError('release file set mismatch')
 for name,expected in manifest['files'].items():
  path=directory/name
  if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent!=directory.parent):raise ValueError('release symlink')
  with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
  if actual!=expected:raise ValueError('release digest mismatch')
 return manifest

def stage(root,revision='HEAD',activate=False):
 if revision!='HEAD' and not re.fullmatch(r'[a-f0-9]{40}',revision):raise ValueError('full commit revision required')
 revision=subprocess.check_output(['git','rev-parse','--verify',revision+'^{commit}'],cwd=ROOT,text=True).strip()
 root=Path(root).absolute();root.mkdir(mode=0o700,parents=True,exist_ok=True)
 if root.is_symlink():raise ValueError('release root symlink')
 releases=root/'releases';releases.mkdir(mode=0o700,exist_ok=True);destination=releases/revision
 if not destination.exists():
  if shutil.disk_usage(root).free<128*1024*1024:raise ValueError('release disk headroom')
  temporary=Path(tempfile.mkdtemp(prefix='.stage-',dir=releases));hashes={};total=0
  try:
   process=subprocess.Popen(['git','archive',revision,'ziokt','spec'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
   try:
    with tarfile.open(fileobj=process.stdout,mode='r|') as archive:
     for member in archive:
      relative=Path(member.name)
      if relative.is_absolute() or '..' in relative.parts or relative.parts[0] not in {'ziokt','spec'}:raise ValueError('release archive path')
      target=temporary/relative
      if member.isdir():target.mkdir(mode=0o755,parents=True,exist_ok=True);continue
      if not member.isfile() or member.size>16*1024*1024:raise ValueError('release archive member')
      total+=member.size
      if total>128*1024*1024 or len(hashes)>=4096:raise ValueError('release archive budget')
      target.parent.mkdir(mode=0o755,parents=True,exist_ok=True);digest=hashlib.sha256()
      with archive.extractfile(member) as source,target.open('xb') as output:
       while chunk:=source.read(65536):output.write(chunk);digest.update(chunk)
       output.flush();os.fsync(output.fileno())
      target.chmod(0o644);hashes[str(relative)]=digest.hexdigest()
    if process.wait()!=0:raise ValueError('git archive failed')
   finally:
    if process.poll() is None:process.kill();process.wait()
    process.stdout.close();process.stderr.close()
   (temporary/'RELEASE.json').write_text(json.dumps({'schema':'ziokt.content-release.v1','revision':revision,'files':hashes},sort_keys=True,indent=2)+'\n')
   with (temporary/'RELEASE.json').open('rb') as stream:os.fsync(stream.fileno())
   verify(temporary,revision);os.rename(temporary,destination)
   fd=os.open(releases,os.O_RDONLY|os.O_DIRECTORY)
   try:os.fsync(fd)
   finally:os.close(fd)
  except BaseException:shutil.rmtree(temporary,ignore_errors=True);raise
 verify(destination,revision)
 previous=None;current=root/'current'
 if activate:
  if current.is_symlink():previous=str(current.resolve())
  elif current.exists():raise ValueError('current must be a managed symlink')
  link=root/('.current-'+secrets.token_hex(8));link.symlink_to(destination,target_is_directory=True);os.replace(link,current)
  fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
  try:os.fsync(fd)
  finally:os.close(fd)
 return {'revision':revision,'release':str(destination),'activated':activate,'previous':previous,'verified':True}

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',required=True);parser.add_argument('--revision',default='HEAD');parser.add_argument('--activate',action='store_true');args=parser.parse_args();print(json.dumps(stage(args.root,args.revision,args.activate)))
if __name__=='__main__':main()

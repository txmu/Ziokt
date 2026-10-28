"""Run-scoped ALFS package checkpoints, never accepted as finished images."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile

BUILD_ROOT=Path('/mnt/openci-lfs')
BOUNDARIES={'base':'829-gawk','gcc':'830-gcc'}
MAX_ARCHIVE=8*1024**3

def file_digest(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()

def validate_receipt(folder,phase,revision,run_id):
    folder=Path(folder);receipt=json.loads((folder/'checkpoint.json').read_text())
    if receipt.get('schema')!='openci.alfs-checkpoint.v1' or receipt.get('phase')!=phase or receipt.get('source_revision')!=revision or receipt.get('run_id')!=str(run_id):raise ValueError('ALFS checkpoint identity mismatch')
    expected={'root.tar.zst','kernel.config','jhalfs-configuration'}
    if set(receipt.get('files',{}))!=expected:raise ValueError('ALFS checkpoint inventory mismatch')
    for name in expected:
        path=folder/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_ARCHIVE or file_digest(path)!=receipt['files'][name]:raise ValueError('ALFS checkpoint digest mismatch: '+name)
    return receipt

def validate_members(members):
    total=0;count=0
    for member in members:
        p=PurePosixPath(member.name);count+=1;total+=member.size
        if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0]!='openci-lfs':raise ValueError('ALFS checkpoint archive path')
        if member.isdev() or member.isfifo() or not(member.isdir() or member.isfile() or member.issym() or member.islnk()):raise ValueError('ALFS checkpoint special file')
        if member.islnk():
            target=PurePosixPath(member.linkname)
            if target.is_absolute() or '..' in target.parts or not target.parts or target.parts[0]!='openci-lfs':raise ValueError('ALFS checkpoint hard link')
        if total>24*1024**3 or count>300000:raise ValueError('ALFS checkpoint expansion limit')

def ci_guard():
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.geteuid()==0:raise RuntimeError('disposable non-root CI runner required')

def save(work,phase):
    ci_guard();work=Path(work);folder=work/'checkpoint';folder.mkdir(exist_ok=True)
    boundary=BUILD_ROOT/'jhalfs'/BOUNDARIES[phase]
    if not boundary.is_file() or phase=='base' and (BUILD_ROOT/'jhalfs/830-gcc').exists():raise ValueError('ALFS checkpoint did not stop at the requested package')
    for name in ('dev','proc','sys','run'):
        if os.path.ismount(BUILD_ROOT/name):raise ValueError('unmount ALFS kernel filesystems before checkpointing')
    subprocess.run(['sudo','tar','--numeric-owner','--acls','--xattrs','--one-file-system','--exclude=openci-lfs/dev','--exclude=openci-lfs/proc','--exclude=openci-lfs/sys','--exclude=openci-lfs/run','-I','zstd -T2 -3','-cpf',str(folder/'root.tar.zst'),'-C','/mnt','openci-lfs'],check=True)
    subprocess.run(['sudo','chown',str(os.getuid())+':'+str(os.getgid()),str(folder/'root.tar.zst')],check=True)
    for name in ('kernel.config','jhalfs-configuration'):shutil.copy2(work/'evidence'/name,folder/name)
    receipt={'schema':'openci.alfs-checkpoint.v1','phase':phase,'source_revision':os.environ['GITHUB_SHA'],'run_id':os.environ['GITHUB_RUN_ID'],'completed_package':BOUNDARIES[phase],'full_build_complete':False,'files':{name:file_digest(folder/name) for name in ('root.tar.zst','kernel.config','jhalfs-configuration')}}
    (folder/'checkpoint.json').write_text(json.dumps(receipt,indent=2)+'\n')
    validate_receipt(folder,phase,os.environ['GITHUB_SHA'],os.environ['GITHUB_RUN_ID'])

def restore(work,previous):
    ci_guard();work=Path(work);folder=work/'checkpoint'
    validate_receipt(folder,previous,os.environ['GITHUB_SHA'],os.environ['GITHUB_RUN_ID'])
    if BUILD_ROOT.exists() and any(BUILD_ROOT.iterdir()):raise ValueError('ALFS restore requires a fresh build root')
    # Validate the compressed stream before privileged extraction. The artifact is
    # from this run and exact revision, not a shared mutable build cache.
    process=subprocess.Popen(['zstd','-dc',str(folder/'root.tar.zst')],stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdout,mode='r|') as archive:validate_members(archive)
        if process.wait()!=0:raise ValueError('ALFS checkpoint decompression failed')
    finally:
        if process.stdout:process.stdout.close()
        if process.poll() is None:process.kill();process.wait()
    subprocess.run(['sudo','tar','--numeric-owner','--acls','--xattrs','-I','zstd','-xpf',str(folder/'root.tar.zst'),'-C','/mnt'],check=True)
    for name in ('dev','proc','sys','run'):subprocess.run(['sudo','mkdir','-p',str(BUILD_ROOT/name)],check=True)
    if not (BUILD_ROOT/'jhalfs'/BOUNDARIES[previous]).is_file():raise ValueError('ALFS package checkpoint stamp missing')
    for name in ('kernel.config','jhalfs-configuration'):shutil.copy2(folder/name,work/'evidence'/name)
    shutil.copy2(folder/'kernel.config',work/'kernel.config')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['save','restore']);parser.add_argument('work',type=Path);parser.add_argument('phase',choices=BOUNDARIES);args=parser.parse_args()
    (save if args.operation=='save' else restore)(args.work,args.phase)

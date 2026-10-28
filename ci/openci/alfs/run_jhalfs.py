"""Drive upstream jhalfs/make with its own package breakpoints and a bounded PTY."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BOUNDARIES={'base':'829-gawk','gcc':'830-gcc'}
STAGE_SECONDS=19800  # Leave time for provisioning, evidence and checkpoint upload.

def command(directory,phase,build_root):
    if phase in {'full','base'}:
        args=[str(Path(directory).resolve()/'jhalfs'),'run'];cwd=Path(directory)
    else:
        args=['make','-j1'];cwd=Path(build_root)/'jhalfs'
    if phase=='gcc':args+=['BREAKPOINT='+BOUNDARIES[phase]]
    env=dict(os.environ);env.pop('MAKEFLAGS',None)
    if phase=='base':env['MAKEFLAGS']='BREAKPOINT='+BOUNDARIES[phase]
    return args,cwd,env

def check_exit(phase,status,build_root):
    active=Path(build_root)/'jhalfs'
    if phase in BOUNDARIES:
        if status==0 or not (active/BOUNDARIES[phase]).is_file():raise RuntimeError('ALFS did not reach its package breakpoint: '+phase)
        if phase=='base' and (active/BOUNDARIES['gcc']).exists():raise RuntimeError('ALFS base checkpoint advanced past GCC')
        return 'checkpointed'
    if status!=0:raise RuntimeError('Official jhalfs build failed: '+str(status))
    return 'completed'

def heartbeat(build_root,evidence,phase,started):
    root=Path(build_root)/'jhalfs';logs=[]
    for kind in ('logs','test-logs'):
        directory=root/kind
        if not directory.is_dir():continue
        recent=sorted((p for p in directory.iterdir() if p.is_file()),key=lambda p:p.stat().st_mtime,reverse=True)[:3]
        logs.extend({'kind':kind,'name':p.name,'bytes':p.stat().st_size} for p in recent)
    report={'phase':phase,'elapsed_seconds':int(time.monotonic()-started),'recent_logs':logs,'full_build_complete':False}
    Path(evidence).mkdir(parents=True,exist_ok=True)
    (Path(evidence)/('progress-'+phase+'.json')).write_text(json.dumps(report,indent=2)+'\n')
    # Process names, not command arguments or environment (which may hold secrets).
    result=subprocess.run(['ps','-eo','pid,ppid,etime,pcpu,pmem,stat,comm'],capture_output=True,text=True,timeout=5)
    (Path(evidence)/('processes-'+phase+'.txt')).write_text(result.stdout[-32768:])
    print('ALFS progress '+json.dumps(report),flush=True)

def main(directory,phase='full',build_root='/mnt/openci-lfs',evidence=None):
    if os.environ.get('GITHUB_ACTIONS')!='true':raise RuntimeError('ALFS runs in CI only')
    import pexpect
    args,cwd,env=command(directory,phase,build_root);evidence=Path(evidence or Path(directory).parent/'evidence')
    child=pexpect.spawn(args[0],args[1:],cwd=str(cwd),env=env,encoding='utf-8',dimensions=(40,120),timeout=60)
    child.logfile_read=sys.stdout;started=time.monotonic();confirmations=0
    report={'schema':'openci.alfs-phase.v1','phase':phase,'source_revision':os.environ['GITHUB_SHA'],'full_build_complete':False,'state':'running'}
    try:
        while True:
            remaining=STAGE_SECONDS-(time.monotonic()-started)
            if remaining<=0:raise TimeoutError('ALFS phase time budget exhausted: '+phase)
            choice=child.expect([r'Do you want to run jhalfs\? yes/no \(yes\):',r'Are you happy with these settings\? yes/no \(no\):',pexpect.EOF,pexpect.TIMEOUT],timeout=min(60,remaining),searchwindowsize=4096)
            if choice==2:break
            if choice==3:heartbeat(build_root,evidence,phase,started);continue
            if phase not in {'full','base'} or confirmations>=2:raise RuntimeError('Unexpected interactive ALFS prompt')
            child.sendline('yes');confirmations+=1
        child.close(force=False)
        report['state']=check_exit(phase,child.exitstatus,build_root)
        report['build_completed']=report['state']=='completed'
    except BaseException as error:
        report.update(state='failed',error=type(error).__name__)
        raise
    finally:
        child.close(force=True);evidence.mkdir(parents=True,exist_ok=True)
        heartbeat(build_root,evidence,phase,started)
        (evidence/('phase-'+phase+'.json')).write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');parser.add_argument('--phase',choices=['full','base','gcc','finish'],default='full');parser.add_argument('--build-root',default='/mnt/openci-lfs');parser.add_argument('--evidence');args=parser.parse_args()
    main(args.directory,args.phase,args.build_root,args.evidence)

"""Give unmodified jhalfs the terminal geometry its Makefile requires."""
import os
from pathlib import Path
import sys


def main(directory):
    if os.environ.get('GITHUB_ACTIONS')!='true':raise RuntimeError('ALFS runs in CI only')
    import pexpect
    child=pexpect.spawn(str(Path(directory).resolve()/'jhalfs'),['run'],cwd=directory,encoding='utf-8',dimensions=(40,120),timeout=1800)
    child.logfile_read=sys.stdout
    try:
        confirmations=0
        while confirmations<2:
            choice=child.expect([r'Do you want to run jhalfs\? yes/no \(yes\):',r'Are you happy with these settings\? yes/no \(no\):',pexpect.EOF])
            if choice==2:break
            child.sendline('yes');confirmations+=1
        if confirmations==2:child.expect(pexpect.EOF,timeout=21000,searchwindowsize=4096)
        child.close(force=False)
        if child.exitstatus!=0:raise RuntimeError('Official jhalfs build failed: '+str(child.exitstatus))
    finally:child.close(force=True)


if __name__=='__main__':main(sys.argv[1])

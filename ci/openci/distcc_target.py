#!/usr/bin/env python3
"""ccache prefix policy: only the pinned Buildroot cross compiler is distributed.

Host tools keep their native preprocessing/warning semantics on the coordinator.
This is not a generic host executor or a network authentication boundary.
"""
import json
import os
from pathlib import Path
import re
import sys


def remote_compiler(compiler,approved):
    path=Path(compiler)
    return path.is_absolute() and path.parent.resolve()==Path(approved).resolve() and re.fullmatch(r'[A-Za-z0-9_+.-]+-buildroot-[A-Za-z0-9_+.-]+-(?:gcc|g\+\+)(?:\.br_real)?',path.name) is not None


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise RuntimeError('Dedicated CI compiler policy required')
    if len(sys.argv)<2:raise RuntimeError('Compiler argument required')
    compiler=sys.argv[1];approved=os.environ['OPenci_DISTCC_TARGET_BIN']
    remote=remote_compiler(compiler,approved)
    record=os.environ.get('OPenci_DISTCC_ROUTING_LOG')
    if record:
        fd=os.open(record,os.O_CREAT|os.O_WRONLY|os.O_APPEND|getattr(os,'O_NOFOLLOW',0),0o600)
        try:os.write(fd,(json.dumps({'compiler':compiler,'remote':remote})+'\n').encode())
        finally:os.close(fd)
    argv=['distcc',*sys.argv[1:]] if remote else sys.argv[1:]
    os.execvp(argv[0],argv)

if __name__=='__main__':main()

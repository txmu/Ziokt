#!/usr/bin/env python3
"""Package an already exported blog; never executes a generator or its plugins."""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys
import zipfile

GENERATORS={'hugo','hexo','jekyll','astro','eleventy','zola','mkdocs','pelican',
            'docusaurus','vitepress','vuepress','next-export','gatsby','generic'}


def prepare(directory,output,*,generator='generic',spa=False,wasm=False):
    if generator not in GENERATORS or type(spa) is not bool or type(wasm) is not bool:raise ValueError('explicit static export options required')
    root=Path(directory).resolve(strict=True);output=Path(output).absolute()
    if not root.is_dir() or root==output or root in output.parents:raise ValueError('output must be outside exported tree')
    files={};total=0
    for item in sorted(root.rglob('*')):
        if len(files)>=100000:raise ValueError('static file count limit')
        info=item.lstat()
        if stat.S_ISLNK(info.st_mode):raise ValueError('static export symlinks rejected')
        if item.is_dir():continue
        if not stat.S_ISREG(info.st_mode):raise ValueError('static regular files required')
        name=item.relative_to(root).as_posix()
        if any(part.startswith('.') for part in item.relative_to(root).parts):continue
        if item.suffix.lower() in {'.php','.py','.rb','.sh','.pem','.key','.sqlite','.db'}:raise ValueError('server code, keys and databases are not static blog assets')
        if info.st_size>64*1024*1024 or total+info.st_size>256*1024*1024:raise ValueError('bounded static export required')
        if name=='ziokt-export.json':raise ValueError('reserved export receipt filename')
        import os
        fd=os.open(item,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        try:
            opened=os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev,opened.st_ino)!=(info.st_dev,info.st_ino):raise ValueError('export file changed while opening')
            with os.fdopen(fd,'rb',closefd=False) as source:data=source.read(64*1024*1024+1)
            after=os.fstat(fd)
            if len(data)>64*1024*1024 or (after.st_size,after.st_mtime_ns)!=(opened.st_size,opened.st_mtime_ns):raise ValueError('export file changed while reading')
        finally:os.close(fd)
        total+=len(data)
        if total>256*1024*1024:raise ValueError('static export byte budget')
        files[name]=data
    if 'index.html' not in files:raise ValueError('generator output needs index.html')
    # This is a portable source/export receipt, not an NNS registration.
    receipt={'schema':'ziokt.static-blog-export.v1','generator':generator,'index':'index.html',
             'static_routing':'spa' if spa else 'clean','static_wasm':wasm,
             'files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()},
             'server_execution':False,'published':False,'external_dependencies':'vendor locally; external scripts not enabled implicitly'}
    output.parent.mkdir(parents=True,exist_ok=True)
    import tempfile,os
    fd,temporary=tempfile.mkstemp(prefix='.blog-export-',dir=output.parent);os.close(fd)
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as z:
            for name,data in files.items():z.writestr(name,data)
            z.writestr('ziokt-export.json',json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
        os.replace(temporary,output)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    return {'archive':str(output),'files':len(files),'bytes':total,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'published':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--generator',choices=sorted(GENERATORS),default='generic');parser.add_argument('--spa',action='store_true');parser.add_argument('--wasm',action='store_true');args=parser.parse_args()
    print(json.dumps(prepare(args.directory,args.output,generator=args.generator,spa=args.spa,wasm=args.wasm)))

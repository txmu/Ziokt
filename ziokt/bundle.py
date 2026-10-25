"""Signed Ziokt bundles carrying independently verifiable native packages."""
import argparse
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import tempfile
import zipfile

from .protocol import ProtocolError,encoded,secure_read,strict_json
from .security import sign,verify
from ._verified_guards import package_member_admitted,target_matches

DOMAIN='Ziokt/package-bundle/v1'
TARGETS={'corium','dcpm','shadow6-extension'}
NAME=re.compile('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}(?:/[A-Za-z0-9][A-Za-z0-9_.-]{0,63})?\\Z')
VERSION=re.compile('[0-9]+\\.[0-9]+\\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?\\Z')
MAX_FILE=256*1024*1024
MAX_TOTAL=512*1024*1024


def safe_name(value):
    if (not isinstance(value,str) or not 1<=len(value)<=240 or '\\' in value or ':' in value
            or PurePosixPath(value).is_absolute() or any(p in {'','.', '..'} for p in value.split('/'))):
        raise ProtocolError('PACKAGE_PATH','portable relative package path required')
    return value


def identity(value):
    if (not isinstance(value,dict) or not isinstance(value.get('name'),str) or not NAME.fullmatch(value['name'])
            or not isinstance(value.get('version'),str) or len(value['version'])>80 or not VERSION.fullmatch(value['version'])
            or not isinstance(value.get('dependencies',[]),list) or len(value.get('dependencies',[]))>32
            or any(not isinstance(v,str) or len(v)>160 for v in value.get('dependencies',[]))):
        raise ProtocolError('PACKAGE_IDENTITY','package name, semantic version and bounded dependencies required')


def build(spec,root,key,output):
    if (not isinstance(spec,dict) or set(spec)-{'schema','name','version','dependencies','artifacts'}
            or spec.get('schema')!='ziokt.package-spec.v1' or not isinstance(spec.get('artifacts'),list)
            or not 1<=len(spec['artifacts'])<=16):raise ProtocolError('PACKAGE_SPEC','exact Ziokt package specification required')
    identity(spec);root=Path(root).resolve();output=Path(output).absolute();files=[];seen=set();total=0
    for entry in spec['artifacts']:
        if not isinstance(entry,dict) or set(entry)!={'target','file'} or not isinstance(entry['target'],str) or entry['target'] not in TARGETS:
            raise ProtocolError('PACKAGE_TARGET','Corium, dCPM or Shadow6 Extension target required')
        name=safe_name(entry['file']);path=root/name
        if path.resolve()!=path or not path.is_relative_to(root) or not path.is_file():raise ProtocolError('PACKAGE_PATH','regular artifact inside the source root required')
        archive='artifacts/'+entry['target']+'/'+Path(name).name
        if archive in seen:raise ProtocolError('PACKAGE_PATH','unique native artifact names required')
        seen.add(archive);size=path.stat().st_size;total+=size
        if not 0<size<=MAX_FILE or total>MAX_TOTAL:raise ProtocolError('PACKAGE_LIMIT','native artifact byte budget exceeded')
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        files.append({'target':entry['target'],'path':archive,'bytes':size,'sha256':digest,'source':path})
    manifest={'schema':'ziokt.package.v1','name':spec['name'],'version':spec['version'],
              'dependencies':spec.get('dependencies',[]),'artifacts':[{k:v for k,v in f.items() if k!='source'} for f in files],
              'native_admission':'target-native-signature-policy'}
    envelope=sign(manifest,key,DOMAIN)
    output.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.ziokt-package-',dir=output.parent);os.close(descriptor)
    try:
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('manifest.json',encoded(envelope))
            for item in files:archive.write(item['source'],item['path'])
        inspect(temporary,envelope['public_key'])
        if output.exists():raise ProtocolError('PACKAGE_EXISTS','choose a new output path')
        os.link(temporary,output)
    finally:Path(temporary).unlink(missing_ok=True)
    with output.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'schema':'ziokt.package-built.v1','path':str(output),'publisher':envelope['public_key'],
            'sha256':digest,'artifacts':len(files)}


def inspect(path,publisher):
    with zipfile.ZipFile(path) as archive:
        entries=archive.infolist()
        if not 2<=len(entries)<=17 or len({item.filename for item in entries})!=len(entries):
            raise ProtocolError('PACKAGE_LAYOUT','bounded unique bundle members required')
        for entry in entries:
            safe_name(entry.filename)
            if entry.is_dir() or entry.flag_bits&1 or (entry.external_attr>>16)&0o170000==0o120000:
                raise ProtocolError('PACKAGE_LAYOUT','regular unencrypted bundle members required')
        metadata=archive.getinfo('manifest.json')
        if metadata.file_size>65536:raise ProtocolError('PACKAGE_LIMIT','signed manifest byte budget exceeded')
        envelope=strict_json(archive.read(metadata));manifest=verify(envelope,publisher,DOMAIN)
        if (not isinstance(manifest,dict) or set(manifest)!={'schema','name','version','dependencies','artifacts','native_admission'}
                or manifest['schema']!='ziokt.package.v1' or manifest['native_admission']!='target-native-signature-policy'
                or not isinstance(manifest['artifacts'],list) or not 1<=len(manifest['artifacts'])<=16):
            raise ProtocolError('PACKAGE_LAYOUT','exact signed package manifest required')
        identity(manifest);wanted={'manifest.json'};total=0
        for artifact in manifest['artifacts']:
            if (not isinstance(artifact,dict) or set(artifact)!={'target','path','bytes','sha256'} or not isinstance(artifact['target'],str) or artifact['target'] not in TARGETS
                    or type(artifact['bytes']) is not int or not 0<artifact['bytes']<=MAX_FILE
                    or not isinstance(artifact['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',artifact['sha256'])):
                raise ProtocolError('PACKAGE_LAYOUT','bounded signed native artifact required')
            name=safe_name(artifact['path'])
            if name in wanted or len(name.split('/'))!=3 or not name.startswith('artifacts/'+artifact['target']+'/'):raise ProtocolError('PACKAGE_LAYOUT','target-bound unique artifact path required')
            wanted.add(name);entry=archive.getinfo(name);total+=entry.file_size
            if entry.file_size!=artifact['bytes'] or total>MAX_TOTAL:raise ProtocolError('PACKAGE_LIMIT','artifact byte declaration differs')
            digest=hashlib.sha256()
            with archive.open(entry) as stream:
                while chunk:=stream.read(1024*1024):digest.update(chunk)
            if not package_member_admitted(artifact['bytes'],entry.file_size,digest.hexdigest()==artifact['sha256']):raise ProtocolError('PACKAGE_DIGEST','native artifact digest differs')
        if wanted!={entry.filename for entry in entries}:raise ProtocolError('PACKAGE_LAYOUT','undeclared bundle members rejected')
    return manifest


def extract(path,publisher,target,destination):
    if target not in TARGETS:raise ProtocolError('PACKAGE_TARGET','known native package target required')
    manifest=inspect(path,publisher);destination=Path(destination).absolute()
    if destination.exists() or destination.is_symlink():raise ProtocolError('PACKAGE_EXISTS','fresh native staging directory required')
    artifacts=[a for a in manifest['artifacts'] if target_matches(target,a['target'])]
    if not artifacts:raise ProtocolError('PACKAGE_TARGET','bundle does not contain this target')
    destination.mkdir(mode=0o700,parents=True)
    with zipfile.ZipFile(path) as archive:
        for artifact in artifacts:
            output=destination/Path(artifact['path']).name
            with archive.open(artifact['path']) as source,output.open('xb') as stream:
                while chunk:=source.read(1024*1024):stream.write(chunk)
            output.chmod(0o600)
    return {'schema':'ziokt.package-stage.v1','target':target,'files':len(artifacts),
            'directory':str(destination),'next_step':'native signature verification and installation'}


def main(argv=None):
    parser=argparse.ArgumentParser(prog='ziokt bundle');sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('build');p.add_argument('spec',type=Path);p.add_argument('--root',type=Path,required=True);p.add_argument('--key-file',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    for name in ('inspect','extract'):
        p=sub.add_parser(name);p.add_argument('bundle',type=Path);p.add_argument('--publisher',required=True)
        if name=='extract':p.add_argument('--target',choices=sorted(TARGETS),required=True);p.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.action=='build':result=build(strict_json(secure_read(args.spec,65536,private=None)),args.root,secure_read(args.key_file,32),args.output)
    elif args.action=='inspect':result=inspect(args.bundle,args.publisher)
    else:result=extract(args.bundle,args.publisher,args.target,args.destination)
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())

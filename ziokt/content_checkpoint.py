"""Owner-only local cold checkpoints, including vault keys. Never exposed as uploads.

Run with the source application stopped for an application-consistent snapshot.
SQLite backup captures WAL; restore verifies every byte before copying.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from .protocol import encoded,secure_read
from .security import sign,verify
from .safefs import _private_dir

DOMAIN='Ziokt/ContentFabric/checkpoint/v1'


def checkpoint(source,destination):
    source=Path(source).resolve();destination=Path(destination).absolute()
    if destination.exists() or source==destination or source in destination.parents:raise ValueError('new checkpoint outside source required')
    temporary=Path(tempfile.mkdtemp(prefix='ziokt-checkpoint-',dir=destination.parent));os.chmod(temporary,0o700)
    try:
        hashes={}
        for path in sorted(source.rglob('*')):
            if path.is_symlink():raise ValueError('symlink in checkpoint')
            rel=path.relative_to(source)
            if path.is_dir():(temporary/rel).mkdir(mode=0o700,parents=True,exist_ok=True);continue
            if path.name.endswith(('-wal','-shm')):continue
            target=temporary/rel;target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            if path.suffix in {'.sqlite','.db'}:
                original=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
                copy=sqlite3.connect(target)
                try:original.backup(copy)
                finally:original.close();copy.close()
            else:shutil.copyfile(path,target)
            os.chmod(target,0o600)
            with target.open('rb') as stream:
                digest=hashlib.file_digest(stream,'sha256').hexdigest()
                os.fsync(stream.fileno())
            hashes[str(rel)]=digest
        manifest=sign({'v':1,'files':hashes},secure_read(source/'node.key',32),DOMAIN)
        path=temporary/'checkpoint.json';path.write_bytes(encoded(manifest));os.chmod(path,0o600)
        os.rename(temporary,destination)
        return {'files':len(hashes),'node':manifest['public_key'],'contains_private_keys':True}
    except BaseException:shutil.rmtree(temporary);raise


def restore(source,destination,authority):
    source=Path(source);destination=Path(destination)
    if destination.exists():raise ValueError('restore requires a new directory')
    envelope=json.loads(secure_read(source/'checkpoint.json',1024*1024))
    value=verify(envelope,authority,DOMAIN,maximum=1024*1024)
    if value.get('v')!=1 or not isinstance(value.get('files'),dict):raise ValueError('checkpoint version')
    actual={str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() and p.name!='checkpoint.json'}
    if actual!=set(value['files']):raise ValueError('checkpoint file set')
    for name,expected in value['files'].items():
        rel=Path(name)
        if rel.is_absolute() or '..' in rel.parts:raise ValueError('checkpoint traversal')
        path=source/rel
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):raise ValueError('checkpoint symlink')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=expected:raise ValueError('checkpoint hash mismatch')
    _private_dir(destination)
    try:
        for name in value['files']:
            target=destination/name;_private_dir(target.parent);shutil.copyfile(source/name,target);os.chmod(target,0o600)
        db=sqlite3.connect(destination/'content.sqlite')
        try:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('checkpoint database')
        finally:db.close()
    except BaseException:shutil.rmtree(destination);raise
    return {'restored':len(value['files']),'node':authority}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['create','restore']);parser.add_argument('source');parser.add_argument('destination');parser.add_argument('--authority')
    args=parser.parse_args()
    if args.action=='create':result=checkpoint(args.source,args.destination)
    else:
        if not args.authority:parser.error('--authority required for restore')
        result=restore(args.source,args.destination,args.authority)
    print(json.dumps(result))


if __name__=='__main__':main()

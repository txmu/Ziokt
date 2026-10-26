"""Encrypted, signed cold recovery with independent mounted replicas.

Live SQLite databases use the backup API, including committed WAL data. Recovery
always targets a new directory; identity activation and chain replay stay explicit.
"""
import argparse
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .package_storage import atomic_write, relative_path, safe_path
from .protocol import ProtocolError, encoded, secure_read, strict_json
from .security import sign, verify

DOMAIN='Ziokt/doomsday/v1'
MAGIC=b'ZIOKT-DOOMSDAY-1\n'
MAX_BYTES=64*1024*1024


def configuration(path):
    config=strict_json(secure_read(Path(path),65536),65536)
    if (not isinstance(config,dict) or set(config)!={'schema','signing_key_file','encryption_key_file','artifacts','replicas'} or
            config['schema']!='ziokt.doomsday.v1' or not isinstance(config['artifacts'],list) or not 1<=len(config['artifacts'])<=256 or
            not isinstance(config['replicas'],list) or len(config['replicas'])>16):
        raise ProtocolError('INVALID_CONFIG','bounded explicit survival configuration required')
    ids=set()
    for artifact in config['artifacts']:
        if not isinstance(artifact,dict) or set(artifact)!={'id','path','kind'} or artifact['kind'] not in {'file','sqlite'}:
            raise ProtocolError('INVALID_CONFIG','explicit file or SQLite artifact required')
        relative_path(artifact['id'])
        if artifact['id'] in ids or not Path(artifact['path']).is_absolute():raise ProtocolError('INVALID_CONFIG','unique artifact and absolute path required')
        ids.add(artifact['id'])
    for replica in config['replicas']:
        if not isinstance(replica,str) or not Path(replica).is_absolute():raise ProtocolError('INVALID_CONFIG','absolute replica directories required')
    return config


def snapshot(config, output):
    private=secure_read(Path(config['signing_key_file']),32)
    encryption=secure_read(Path(config['encryption_key_file']),32)
    if len(private)!=32 or len(encryption)!=32:raise ProtocolError('INVALID_KEY','32-byte signing and encryption keys required')
    files={};total=0
    with tempfile.TemporaryDirectory(prefix='ziokt-cold-backup-') as temporary:
        for artifact in config['artifacts']:
            source=Path(artifact['path'])
            if source.is_symlink() or not source.is_file() or source.stat().st_size>MAX_BYTES:
                raise ProtocolError('UNSAFE_FILE','bounded regular backup source required')
            if artifact['kind']=='sqlite':
                target=Path(temporary)/'consistent.sqlite'
                from urllib.parse import quote
                with closing(sqlite3.connect('file:'+quote(str(source))+'?mode=ro',uri=True,timeout=5)) as original, closing(sqlite3.connect(target)) as copy:
                    deadline=time.monotonic()+15
                    def progress(status,remaining,pages):
                        if pages*4096>MAX_BYTES or time.monotonic()>deadline:raise ProtocolError('BACKUP_LIMIT','SQLite snapshot exceeds budget')
                    original.backup(copy,pages=256,progress=progress)
                    if copy.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ProtocolError('BACKUP_INTEGRITY','SQLite consistency check failed')
                if target.stat().st_size>MAX_BYTES:raise ProtocolError('BACKUP_LIMIT','SQLite snapshot too large')
                data=target.read_bytes();target.unlink()
            else:
                data=secure_read(source,MAX_BYTES,private=None)
            total+=len(data)
            if total>MAX_BYTES:raise ProtocolError('BACKUP_LIMIT','snapshot exceeds 64 MiB')
            files[artifact['id']]=data
    manifest={'schema':'ziokt.doomsday-snapshot.v1','created_at':int(time.time()),'files':{
        name:{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)} for name,data in files.items()},
        'restore_policy':'new-directory-only; native identities and chain replay require explicit activation'}
    envelope=sign(manifest,private,DOMAIN)
    memory=io.BytesIO()
    with zipfile.ZipFile(memory,'w',compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('MANIFEST.json',encoded(envelope))
        for name,data in files.items():archive.writestr('artifacts/'+name,data)
    nonce=secrets.token_bytes(12)
    body=MAGIC+nonce+AESGCM(encryption).encrypt(nonce,memory.getvalue(),MAGIC)
    output=Path(output);output.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    if output.exists() or output.is_symlink():raise ProtocolError('BACKUP_EXISTS','snapshot output must be new')
    atomic_write(output,body)
    digest=hashlib.sha256(body).hexdigest();replicas=[]
    for destination in config['replicas']:
        try:
            directory=Path(destination)
            if directory.is_symlink():raise ProtocolError('UNSAFE_FILE','replica symlink rejected')
            directory.mkdir(parents=True,mode=0o700,exist_ok=True)
            target=safe_path(directory,'snapshot-'+digest+'.zds')
            atomic_write(target,body)
            if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ProtocolError('BACKUP_INTEGRITY','replica readback mismatch')
            replicas.append({'path':str(directory),'state':'verified','sha256':digest})
        except (OSError,ProtocolError) as exc:replicas.append({'path':destination,'state':'unavailable','error':type(exc).__name__})
    return {'archive':str(output),'sha256':digest,'bytes':len(body),'artifacts':len(files),
            'publisher':envelope['public_key'],'replicas':replicas,'independent_failure_domains':'operator_verification_required'}


def inspect(archive, key, publisher):
    body=secure_read(Path(archive),MAX_BYTES+1024*1024,private=None)
    if not body.startswith(MAGIC) or len(body)<len(MAGIC)+28:raise ProtocolError('INVALID_BACKUP','encrypted Ziokt snapshot required')
    nonce=body[len(MAGIC):len(MAGIC)+12]
    from cryptography.exceptions import InvalidTag
    try:plain=AESGCM(key).decrypt(nonce,body[len(MAGIC)+12:],MAGIC)
    except (InvalidTag,ValueError):raise ProtocolError('BACKUP_INTEGRITY','decryption authentication failed')
    files={}
    with zipfile.ZipFile(io.BytesIO(plain)) as zipped:
        entries=zipped.infolist()
        if len(entries)>257 or len({item.filename for item in entries})!=len(entries) or sum(item.file_size for item in entries)>MAX_BYTES+262144:
            raise ProtocolError('BACKUP_LIMIT','bounded unique backup entries required')
        envelope=strict_json(zipped.read('MANIFEST.json'),262144)
        manifest=verify(envelope,publisher,DOMAIN,maximum=262144)
        if not isinstance(manifest,dict) or manifest.get('schema')!='ziokt.doomsday-snapshot.v1' or not isinstance(manifest.get('files'),dict):raise ProtocolError('INVALID_BACKUP','signed survival manifest required')
        if set(zipped.namelist())!={'MANIFEST.json'}|{'artifacts/'+name for name in manifest['files']}:
            raise ProtocolError('BACKUP_INTEGRITY','archive inventory mismatch')
        for name,expected in manifest['files'].items():
            relative_path(name);data=zipped.read('artifacts/'+name)
            if len(data)!=expected['bytes'] or hashlib.sha256(data).hexdigest()!=expected['sha256']:raise ProtocolError('BACKUP_INTEGRITY','artifact digest mismatch')
            files[name]=data
    return manifest,files


def restore(archive, key, publisher, destination):
    manifest,files=inspect(archive,key,publisher)
    destination=Path(destination).absolute()
    if destination.exists() or destination.is_symlink():raise ProtocolError('RESTORE_CONFLICT','restore requires a new directory')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ziokt-restore-',dir=destination.parent) as temporary:
        stage=Path(temporary)/'state';stage.mkdir(mode=0o700)
        for name,data in files.items():
            target=safe_path(stage,name);target.parent.mkdir(parents=True,mode=0o700,exist_ok=True);atomic_write(target,data)
        os.rename(stage,destination)
    return {'destination':str(destination),'artifacts':len(files),'signature_verified':True,
            'chain_replay_required':True,'services_activated':False,'created_at':manifest['created_at']}


def status(config):
    return {'schema':'ziokt.doomsday-status.v1','artifacts':[{'id':item['id'],'available':Path(item['path']).is_file() and not Path(item['path']).is_symlink(),'kind':item['kind']} for item in config['artifacts']],
            'replicas':[{'path':path,'available':Path(path).is_dir() and not Path(path).is_symlink()} for path in config['replicas']],
            'network_required_for_snapshot_or_restore':False,'chain_replay_required':True}


def main(argv=None):
    parser=argparse.ArgumentParser(prog='ziokt doomsday');sub=parser.add_subparsers(dest='action',required=True)
    for name in ('status','snapshot'):
        command=sub.add_parser(name);command.add_argument('--config',type=Path,required=True)
        if name=='snapshot':command.add_argument('--output',type=Path,required=True)
    command=sub.add_parser('restore');command.add_argument('--archive',type=Path,required=True);command.add_argument('--encryption-key-file',type=Path,required=True);command.add_argument('--publisher',required=True);command.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.action=='restore':result=restore(args.archive,secure_read(args.encryption_key_file,32),args.publisher,args.destination)
    else:
        config=configuration(args.config);result=status(config) if args.action=='status' else snapshot(config,args.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))

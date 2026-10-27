#!/usr/bin/env python3
"""Deploy a distinct DNA chain from an explicit operator legacy checkpoint."""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time


def write(path,data,mode=0o600):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.is_symlink():raise ValueError('regular deployment file required')
    with path.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    path.chmod(mode)


def deploy(root,primary,archive,corium,entrypoint,activate=False,port=7235,recovery_file=None):
    from cryptography.hazmat.primitives import serialization,hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    sys.path.insert(0,str(corium))
    import recovery_consensus as recovery
    import work_consensus as work
    import dna_protocol as dna
    root=root.absolute();network='ziokt-dna-side-20261024'
    if root.resolve()!=root or primary.resolve()!=primary or root==primary:raise ValueError('independent regular chain root required')
    if hashlib.sha256(entrypoint.read_bytes()).digest()!=hashlib.sha256((corium/'corix_v108.sh').read_bytes()).digest():raise ValueError('deployed native entrypoint must match audited source')
    etc=root/'etc/corix/networks'/network;chain=root/'var/lib/corix/networks'/network/'blockchain/chain.db'
    receipt=root/'dna-deployment.json'
    if receipt.exists():
        value=json.loads(receipt.read_text())
        if value['network']!=network:raise ValueError('existing DNA identity mismatch')
        return value
    if root.exists():raise ValueError('new DNA root required; existing partial staging must be reviewed')
    root.mkdir(mode=0o700,parents=True)
    with sqlite3.connect((archive/'chain.db').as_uri()+'?mode=ro',uri=True) as source:
        tip=source.execute('SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
        genesis=source.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
        if not tip or tip[0]!=784:raise ValueError('explicit original H784 legacy checkpoint required')
    for source,target in ((archive/'chain.db',chain),(archive/'forum.db',root/'var/lib/corix/networks'/network/'forum/forum.db')):
        target.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
        with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as old,sqlite3.connect(target) as new:old.backup(new)
        target.chmod(0o600)
    primary_etc=primary/'etc/corix/networks/ziokt-main'
    genesis_raw=(primary_etc/'genesis.json').read_bytes();definition=json.loads(genesis_raw)
    authority=None;pem=None
    if recovery_file is None:
        authority=serialization.load_pem_private_key((primary_etc/'identity.key').read_bytes(),None)
        pem=dna.public_key(authority)
        if pem not in {v['public_key'].rstrip('\n') for v in definition['genesis_validators']}:raise ValueError('an original authority signature or public recovery declaration is required')
    write(etc/'genesis.json',genesis_raw)
    private=ec.generate_private_key(ec.SECP256K1())
    write(etc/'identity.key',private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    write(etc/'identity.key.pub',(dna.public_key(private)+'\n').encode())
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    import datetime
    tls=ec.generate_private_key(ec.SECP256R1());now=datetime.datetime.now(datetime.timezone.utc)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,network)])
    cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(tls.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
          .not_valid_after(now+datetime.timedelta(days=365)).add_extension(x509.SubjectAlternativeName([x509.DNSName(network)]),False).sign(tls,hashes.SHA256()))
    write(etc/'tls.key',tls.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    write(etc/'tls.crt',cert.public_bytes(serialization.Encoding.PEM))
    config=configparser.ConfigParser(interpolation=None,strict=False);config.read(primary_etc/'corix.conf')
    for section in ('network','p2p','gateway','ziokt'):
        if not config.has_section(section):config.add_section(section)
    config['network']['id']=network;config['p2p']['port']=str(port);config['p2p']['seed_peers']=''
    config['gateway']['port']='8186';config['ziokt'].update({'enabled':'TRUE','provider_id':'corium-dna','federation_id':network,'allow_mutations':'FALSE','allowed_operations':'','zkn_enabled':'FALSE'})
    import io
    buffer=io.StringIO();config.write(buffer);write(etc/'corix.conf',buffer.getvalue().encode())
    hold=root/'config/consensus-safety-hold.json'
    write(hold,encoded_json({'schema':'ziokt.consensus-safety-hold.v1','active':False}))
    env=dict(os.environ,CORIUM_ROOT=str(root),CORIUM_NETWORK_ID_OVERRIDE=network,CORIUM_CONSENSUS_HOLD_FILE=str(hold),PYTHON_CMD=sys.executable)
    command=['bash','-c','source "$1"\nload_config\nmkdir -p "$BUILD_TMP_DIR_BASE" "$INSTALLED_DB" "$P2P_DIR/objects"\n_init_dht_db\n_internal_semantic_state','dna-state',str(entrypoint)]
    result=subprocess.run(command,env=env,capture_output=True,timeout=30,check=True)
    state=json.loads(result.stdout.decode().splitlines()[-1]);initial=hashlib.sha256(dna.encoded(state)).hexdigest()
    archive_root=hashlib.sha256(b'Corium/LegacyCheckpoint/v1\0'+dna.encoded({'genesis':genesis,'height':tip[0],'hash':tip[1],
        'files':{name:hashlib.sha256((archive/name).read_bytes()).hexdigest() for name in ('chain.db','forum.db','dht.db')}})).hexdigest()
    declaration={'schema':recovery.SCHEMA,'network':network,'protocol':recovery.SIDE,'checkpoint':{'height':tip[0],'hash':tip[1]},
                 'initial_state_root':initial,'legacy_archive_root':archive_root,'genesis_sha256':hashlib.sha256(genesis_raw).hexdigest(),
                 'verifier_source_sha256':work.source_digest(),'work_policy':{'schema':'corium.work-weight-policy.v1','network':network,
                 'genesis':genesis,'activation_height':785,'difficulty_bits':8,'weights':[{'from_height':785,'weight':1000}]},
                 'authority_public_key':pem}
    if recovery_file is None:
        declaration['signature']=authority.sign(recovery.signing_bytes(declaration),ec.ECDSA(hashes.SHA256())).hex()
    else:
        provided=dna.loads(recovery_file.read_text())
        for name in ('schema','network','protocol','checkpoint','initial_state_root','legacy_archive_root','genesis_sha256'):
            if provided.get(name)!=declaration[name]:raise ValueError('public recovery declaration does not match supplied checkpoint: '+name)
        if provided.get('verifier_source_sha256') not in work.LEGACY_SOURCE_DIGESTS|{work.source_digest()}:raise ValueError('unsupported recovery verifier revision')
        declaration=provided
    write(etc/'recovery.json',dna.encoded(declaration))
    prior_root=os.environ.get('CORIUM_ROOT');os.environ['CORIUM_ROOT']=str(root)
    try:recovery.declaration(network)
    finally:
        if prior_root is None:os.environ.pop('CORIUM_ROOT',None)
        else:os.environ['CORIUM_ROOT']=prior_root
    wrapper=root/'bin/dna-service';script='#!/bin/bash\nset -e\numask 077\nexport CORIUM_ROOT='+shlex.quote(str(root))+'\nexport CORIUM_CONSENSUS_HOLD_FILE='+shlex.quote(str(hold))+'\nexport CORIUM_NETWORK_ID_OVERRIDE='+network+'\nsource '+shlex.quote(str(entrypoint))+'''\nload_config
mkdir -p "$BUILD_TMP_DIR_BASE" "$INSTALLED_DB" "$P2P_DIR/objects"
case "$1" in
 p2p) dht_server_daemon; wait ;;
 consensus) while true; do blockchain_mine_block; sleep 60; done ;;
 *) exit 2 ;;
esac
'''
    write(wrapper,script.encode(),0o700)
    observation={'schema':'ziokt.dna-deployment.v1','network':network,'root':str(root),'checkpoint':declaration['checkpoint'],
                 'genesis_hash':genesis,'recovery_identity':recovery.identity(declaration),'verifier_source_sha256':work.source_digest(),
                 'legacy_history_fully_verified':False,'legacy_checkpoint_explicitly_trusted':True,'activated':False}
    if activate:
        log=root/'first-dna-block.log'
        with log.open('xb') as stream:
            log.chmod(0o600)
            subprocess.run(['bash','-c','source "$1"\nload_config\nmkdir -p "$BUILD_TMP_DIR_BASE" "$INSTALLED_DB" "$P2P_DIR/objects"\nblockchain_mine_block','dna-activate',str(entrypoint)],env=env,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=60)
        previous=os.environ.get('CORIUM_ROOT');os.environ['CORIUM_ROOT']=str(root)
        try:
            with sqlite3.connect(chain) as db:
                db.row_factory=sqlite3.Row
                nextblock=db.execute('SELECT hash FROM blocks WHERE height=785').fetchone()
                if not nextblock:raise ValueError('actual first DNA block required')
                verified=work.verify(db,network,work.stored(db,nextblock[0]),nextblock[0])
                if db.execute('SELECT hash FROM blocks WHERE height=784').fetchone()[0]!=tip[1]:raise ValueError('legacy checkpoint changed')
        finally:
            if previous is None:os.environ.pop('CORIUM_ROOT',None)
            else:os.environ['CORIUM_ROOT']=previous
        units=[]
        for role in ('p2p','consensus'):
            name='ziokt-corium-dna-'+role;unit=root/(name+'.service')
            text='[Unit]\nAfter=network-online.target\n[Service]\nUser='+str(__import__('pwd').getpwuid(os.getuid()).pw_name)+'\nWorkingDirectory='+str(root)+'\nExecStart='+str(wrapper)+' '+role+'\nRestart=on-failure\nRestartSec=5\nCPUQuota=25%\nMemoryMax=512M\n[Install]\nWantedBy=multi-user.target\n'
            write(unit,text.encode());subprocess.run(['sudo','-n','install','-m','0644',str(unit),'/etc/systemd/system/'+name+'.service'],check=True);units.append(name)
        subprocess.run(['sudo','-n','systemctl','daemon-reload'],check=True)
        subprocess.run(['sudo','-n','systemctl','enable','--now',*units],check=True)
        observation.update(activated=True,first_dna_block=verified['hash'],services=units)
    write(receipt,encoded_json(observation))
    return observation


def encoded_json(value):return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','primary','archive','corium','entrypoint'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--activate',action='store_true');p.add_argument('--port',type=int,default=7235);p.add_argument('--recovery-file',type=Path)
    a=p.parse_args();print(json.dumps(deploy(a.root,a.primary,a.archive.resolve(),a.corium.resolve(),a.entrypoint.resolve(),a.activate,a.port,a.recovery_file)))

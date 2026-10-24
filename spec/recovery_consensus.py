"""Explicit signed recovery boundary. Never manufactures historical governance."""
import hashlib
import os
from pathlib import Path
import stat
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
import dna_protocol as DNA

SCHEMA='corium.recovery-declaration.v1'
MAIN='corium.recovery-work.v3'
SIDE='corium.dna-work.v1'
NETWORKS={'ziokt-main-recovery-20261024','ziokt-dna-side-20261024'}
FIELDS={'schema','network','protocol','checkpoint','initial_state_root','legacy_archive_root',
        'genesis_sha256','verifier_source_sha256','work_policy','authority_public_key','signature'}


def unsigned(value):return {k:v for k,v in value.items() if k!='signature'}
def signing_bytes(value):return b'Corium/Recovery/declaration/v1\0'+DNA.encoded(unsigned(value))
def identity(value):return hashlib.sha256(signing_bytes(value)).hexdigest()


def read_public(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        DNA.require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and not info.st_mode&0o022
                    and info.st_size<=65536,'bounded owner-controlled public recovery document')
        raw=os.read(fd,65537);DNA.require(len(raw)<=65536,'recovery document budget')
        return raw
    finally:os.close(fd)


def declaration(network):
    if network not in NETWORKS:return None
    root=os.environ.get('CORIUM_ROOT')
    DNA.require(root,'recovery root required')
    directory=Path(root)/'etc/corix/networks'/network
    value=DNA.loads(read_public(directory/'recovery.json').decode())
    DNA.require(type(value)is dict and set(value)==FIELDS and value['schema']==SCHEMA
                and value['network']==network,'exact recovery declaration')
    DNA.require(value['protocol']==(MAIN if network.startswith('ziokt-main-')else SIDE),'distinct chain protocol')
    genesis_raw=read_public(directory/'genesis.json');genesis=DNA.loads(genesis_raw.decode())
    DNA.require(hashlib.sha256(genesis_raw).hexdigest()==value['genesis_sha256'],'complete genesis configuration binding')
    for name in ('initial_state_root','legacy_archive_root','verifier_source_sha256'):
        DNA.require(type(value[name])is str and len(value[name])==64 and all(c in '0123456789abcdef'for c in value[name]),'recovery commitment')
    cp=value['checkpoint'];DNA.require(type(cp)is dict and set(cp)=={'height','hash'},'recovery checkpoint fields')
    DNA.integer(cp['height'],0);DNA.require(type(cp['hash'])is str and len(cp['hash'])==64,'checkpoint digest')
    DNA.require(cp['height']==50 if value['protocol']==MAIN else cp['height']>=784,'operator recovery boundary')
    pem=value['authority_public_key'];keys={v['public_key'].rstrip('\n')for v in genesis['genesis_validators']}
    DNA.require(pem in keys,'recovery authority must be supplied genesis authority')
    key=serialization.load_pem_public_key(pem.encode())
    DNA.require(isinstance(key,ec.EllipticCurvePublicKey) and isinstance(key.curve,ec.SECP256K1),'native recovery authority')
    DNA.require(type(value['signature'])is str and 16<=len(value['signature'])<=144,'recovery signature budget')
    key.verify(bytes.fromhex(value['signature']),signing_bytes(value),ec.ECDSA(hashes.SHA256()))
    return value


def active(db,network,height,source_hash,check_policy,legacy):
    value=declaration(network)
    if value is None or height<=value['checkpoint']['height']:return None
    cp=value['checkpoint'];known=db.execute('SELECT hash FROM blocks WHERE height=?',(cp['height'],)).fetchone()
    DNA.require(known is not None and known[0]==cp['hash'],'recovery checkpoint differs from accepted history')
    DNA.require(value['verifier_source_sha256']==source_hash,'recovery verifier source commitment')
    policy={'schema':'corium.native-work-policy.v2','previous_policy':legacy,'checkpoint':cp,'work_policy':value['work_policy']}
    genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()
    check_policy(policy,network,genesis[0])
    DNA.require(policy['work_policy']['activation_height']==cp['height']+1,'recovery activation is prospective')
    return policy


def body(block,value):
    return DNA.encoded({'chain':identity(value),'protocol':value['protocol'],
         'height':block['height'],'parent':block['previous_hash'],'timestamp':block['timestamp'],
         'miner':block['validator'],'transactions':block['transactions'],
         'initial_state_root':value['initial_state_root'],'policy':block['work']['policy']})


def transaction_bytes(value,network,kind,payload,timestamp,pem,height):
    # Prefix signatures retain their historical bytes; new signatures bind both
    # network identity, including the actor, rather than only tx data.
    if value is None or height<=value['checkpoint']['height']:
        import json
        return '{"type":'+json.dumps(kind)+',"data":'+payload+',"timestamp":'+str(timestamp)+'}'
    return DNA.encoded({'schema':'corium.chain-transaction.v3','network':network,
        'public_key':pem,'type':kind,'data':DNA.loads(payload),'timestamp':timestamp}).decode()

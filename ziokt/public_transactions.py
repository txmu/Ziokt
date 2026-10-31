"""Permissionless owner-signed naming admission through the native validator."""
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from .protocol import encoded,strict_json

DOMAIN=b'Ziokt/PublicTransaction/v1\0'
TYPES={'nns_register','nns_update','nns_transfer','nns_renew','set_nickname'}

def signing_bytes(network,transaction):
    return DOMAIN+encoded({'network':network,'transaction':transaction})

def transaction_bytes(network,tx):
    if network in {'ziokt-dna-side-20261024','ziokt-main-recovery-20261024'}:
        return encoded({'schema':'corium.chain-transaction.v3','network':network,
                        **{k:tx[k] for k in ('public_key','type','data','timestamp')}})
    return ('{"type":'+json.dumps(tx['type'])+',"data":'+encoded(tx['data']).decode()+',"timestamp":'+str(tx['timestamp'])+'}').encode()

def validate(value,network):
    if type(value)is not dict or set(value)!={'schema','network','transaction','authorization'} or value['schema']!='ziokt.public-transaction.v1' or value['network']!=network:
        raise ValueError('exact chain-bound public transaction required')
    tx=value['transaction']
    if type(tx)is not dict or set(tx)!={'type','data','timestamp','public_key','signature'} or tx['type'] not in TYPES or type(tx['data'])is not dict or type(tx['timestamp'])is not int or abs(time.time()-tx['timestamp'])>300:
        raise ValueError('fresh owner-signed naming transaction required')
    if type(tx['public_key'])is not str or len(tx['public_key'])>1024 or tx['public_key']!=tx['public_key'].rstrip('\n'):
        raise ValueError('canonical public key required')
    key=serialization.load_pem_public_key(tx['public_key'].encode())
    if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256K1):raise ValueError('native owner key required')
    raw=transaction_bytes(network,tx)
    if len(raw)>16384:raise ValueError('transaction budget')
    for signature,body in [(tx['signature'],raw),(value['authorization'],signing_bytes(network,tx))]:
        if type(signature)is not str or not 16<=len(signature)<=144:raise ValueError('bounded signature required')
        key.verify(bytes.fromhex(signature),body,ec.ECDSA(hashes.SHA256()))
    return tx,hashlib.sha256(raw).hexdigest()

def stage(database,network,value):
    tx,digest=validate(value,network)
    with sqlite3.connect(Path(database).absolute().as_uri()+'?mode=rw',uri=True,timeout=5) as db:
        db.execute('BEGIN IMMEDIATE')
        existing=db.execute('SELECT type,data,signature,public_key,timestamp,block_height FROM transactions WHERE hash=?',(digest,)).fetchone()
        record=(tx['type'],encoded(tx['data']).decode(),tx['signature'],tx['public_key'],tx['timestamp'])
        if existing:
            if existing[:5]!=record:raise ValueError('transaction hash conflict')
            return {'transaction':digest,'phase':'confirmed' if existing[5] is not None else 'pending','duplicate':True}
        if db.execute('SELECT count(*) FROM transactions WHERE block_height IS NULL').fetchone()[0]>=4096 or db.execute('SELECT count(*) FROM transactions WHERE block_height IS NULL AND public_key=?',(tx['public_key'],)).fetchone()[0]>=64:
            raise ValueError('pending transaction budget')
        if tx['type']=='nns_register':
            name=tx['data'].get('domain_name')
            if type(name)is not str:raise ValueError('domain name required')
            if db.execute("SELECT 1 FROM transactions WHERE block_height IS NULL AND type='nns_register' AND json_extract(data,'$.domain_name')=? LIMIT 1",(name,)).fetchone():
                raise ValueError('name registration already pending')
        db.execute('INSERT INTO transactions(hash,type,data,signature,public_key,timestamp,block_height) VALUES(?,?,?,?,?,?,NULL)',(digest,*record))
    return {'transaction':digest,'phase':'pending','duplicate':False}

def publish(root,network,value):
    from ._runtime import asset_publish_transaction
    tx,digest=validate(value,network)
    asset_publish_transaction(Path(root),network,tx,digest)
    return {'transaction':digest,'phase':'pending'}

def main():
    action,path,network,raw=sys.argv[1:]
    value=strict_json(raw.encode(),65536)
    result=stage(path,network,value) if action=='stage' else publish(path,network,value) if action=='publish' else None
    if result is None:raise ValueError('fixed public transaction action required')
    print(json.dumps(result))

if __name__=='__main__':main()

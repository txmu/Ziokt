"""Governed native testnet PoW block bytes and cumulative work policy.

Native callers must still validate transactions and commit/rebuild atomically.
This module never changes production consensus merely by being present.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import dna_protocol as DNA
import recovery_consensus as Recovery
import cooperative_protocol as Cooperative
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature
from work_weight_policy import validate,commitment,verify_work,work_digest,integer,encoded,MAX_WEIGHT

PACKAGE='consensus/work-weight:2'
SCHEMA='corium.native-work-policy.v2'
PROOF='corium.native-block-work.v2'
LEGACY=hashlib.sha256(b'Corium/native-pos/v108').hexdigest()
# Recovery/work policies deployed with the prior audited verifier pin remain
# valid across this additive state-index integration. New proposals still pin
# the current source digest. This grandfathered digest is immutable.
LEGACY_SOURCE_DIGESTS={'5282e14c07d4c9adad1ccc3a8eb2e9a8ee4ca7ad566c416b3f4890148b28309b'}
EMBEDDED_SOURCE_DIGEST = None


def require(test,message):
    if not test:raise ValueError(message)


def source_digest():
    return EMBEDDED_SOURCE_DIGEST or hashlib.sha256(b'Corium/NativeWorkVerifier/v3\0'+b'\0'.join(Path(__file__).with_name(name).read_bytes() for name in ('work_consensus.py','work_weight_policy.py','dna_protocol.py','recovery_consensus.py','cooperative_protocol.py'))).hexdigest()
def policy_hash(value):return hashlib.sha256(b'Corium/NativeConsensusPolicy/v2\0'+encoded(value)).hexdigest()

def loads(raw):
    require(type(raw) is str and len(raw.encode())<=65536,'native work message budget')
    def unique(pairs):
        value={}
        for key,item in pairs:
            require(key not in value,'duplicate consensus field');value[key]=item
        return value
    return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite consensus number')))


def eligible_network(network):require(type(network) is str and (network.startswith('test-') or network.startswith('ziokt-test-') or network in {'ziokt-main','mainnet'} or network in Recovery.NETWORKS),'eligible network required')

def check_policy(value,network,genesis):
    eligible_network(network)
    require(type(value) is dict and set(value)=={'schema','previous_policy','work_policy','checkpoint'} and value['schema']==SCHEMA,'exact native consensus policy')
    policy=validate(value['work_policy']);require(policy['network']==network and policy['genesis']==genesis,'native network/genesis binding')
    require(type(value['previous_policy']) is str and re.fullmatch('[a-f0-9]{64}',value['previous_policy']),'prior consensus commitment')
    checkpoint=value['checkpoint'];require(type(checkpoint) is dict and set(checkpoint)=={'height','hash'},'governed checkpoint')
    integer(checkpoint['height'],0,policy['activation_height']-1);require(type(checkpoint['hash']) is str and re.fullmatch('[a-f0-9]{64}',checkpoint['hash']),'checkpoint digest')
    return value


def proposal(db,network,payload,height):
    require(payload.get('pkg_id')==PACKAGE,'native consensus package')
    genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone();require(genesis is not None,'native genesis required')
    value=check_policy(payload.get('work_consensus'),network,genesis[0])
    require(value['work_policy']['activation_height']>=(height+110 if height>1 else 0),'full governance window and enactment delay required')
    require(payload.get('compute_program_hash')==policy_hash(value) and payload.get('verifier_script_hash')==source_digest(),'native consensus source/policy commitments')
    checkpoint=value['checkpoint'];known=db.execute('SELECT hash FROM blocks WHERE height=? AND height<?',(checkpoint['height'],height)).fetchone();require(known is not None and known[0]==checkpoint['hash'],'checkpoint must precede governance proposal')
    pending=db.execute("SELECT 1 FROM transactions t LEFT JOIN compute_engines e ON e.engine_id=t.hash WHERE t.type='propose_new_compute_engine' AND json_extract(t.data,'$.pkg_id')=? AND t.block_height<? AND (t.block_height+110>=? OR (e.is_active=1 AND json_extract(t.data,'$.work_consensus.work_policy.activation_height')>?)) LIMIT 1",(PACKAGE,height,height,height)).fetchone();require(pending is None,'prior work transition must resolve before another proposal')
    previous=active(db,network,height,validate_previous=False)
    require(value['previous_policy']==(policy_hash(previous) if previous else LEGACY),'consensus predecessor changed')
    return value


def active(db,network,height,validate_previous=True):
    if not (network.startswith('test-') or network.startswith('ziokt-test-') or network in {'ziokt-main','mainnet'} or network in Recovery.NETWORKS):return None
    recovery=Recovery.declaration(network)
    accepted_sources=LEGACY_SOURCE_DIGESTS|{source_digest()}
    recovery_source=recovery['verifier_source_sha256'] if recovery and recovery['verifier_source_sha256'] in accepted_sources else source_digest()
    baseline=Recovery.active(db,network,height,recovery_source,check_policy,LEGACY)
    rows=db.execute("SELECT e.compute_program_hash,e.verifier_script_hash,t.data,t.block_height,t.hash,b.transactions FROM compute_engines e JOIN transactions t ON t.hash=e.engine_id LEFT JOIN blocks b ON b.height=t.block_height WHERE e.pkg_id=? AND e.is_active=1 AND t.type='propose_new_compute_engine' AND t.block_height IS NOT NULL ORDER BY t.block_height,t.hash",(PACKAGE,)).fetchall()
    genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone();require(genesis is not None,'native genesis required')
    accepted=[];previous=policy_hash(baseline) if baseline else LEGACY
    for row in rows:
        if recovery is not None and row['block_height']<=recovery['checkpoint']['height']:continue
        try:payload=json.loads(row['data']);value=check_policy(payload.get('work_consensus'),network,genesis[0])
        except (ValueError, KeyError, TypeError):continue
        activation=value['work_policy']['activation_height']
        if activation>height:continue
        # A database confirmation flag is not evidence of canonical inclusion.
        # The enclosing prefix must already have passed header/transaction replay.
        try:included=loads(row[5]) if row[5] is not None else None
        except (ValueError,TypeError):included=None
        require(type(included) is list and included.count(row[4])==1,
                'WORK_GOVERNANCE_NOT_COMMITTED: active proposal absent from canonical block')
        require(row['block_height']<height,'work proposal must precede candidate block')
        require(row['compute_program_hash']==policy_hash(value) and row['verifier_script_hash'] in accepted_sources and activation>=(row['block_height']+110 if row['block_height']>1 else 0),'active native governance commitment')
        if validate_previous:require(value['previous_policy']==previous and (not accepted or activation>accepted[-1]['work_policy']['activation_height']),'native activation sequence')
        checkpoint=value['checkpoint'];known=db.execute('SELECT hash FROM blocks WHERE height=?',(checkpoint['height'],)).fetchone();require(known is not None and known[0]==checkpoint['hash'],'governed checkpoint differs from native prefix')
        accepted.append(value);previous=policy_hash(value)
    return accepted[-1] if accepted else baseline


def parent(db,hash_value):
    row=db.execute('SELECT height,hash,timestamp,total_weight FROM blocks WHERE hash=?',(hash_value,)).fetchone();require(row is not None,'accepted native parent required')
    return dict(row)


def miner_key(value):
    require(type(value) is str and len(value)<=1024,'bounded native public key')
    key=serialization.load_pem_public_key(value.encode('ascii'))
    require(isinstance(key,ec.EllipticCurvePublicKey) and isinstance(key.curve,ec.SECP256K1),'native secp256k1 required')
    require(key.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')==value,'canonical public key')
    return key


def signing_bytes(block):
    schema=block.get('work',{}).get('schema')
    domain=b'Corium/DNA/block/v1\0' if schema==Recovery.SIDE else b'Corium/Recovery/block/v3\0' if schema==Recovery.MAIN else b'Corium/NativeWorkBlock/v2\0'
    return domain+encoded({k:v for k,v in block.items() if k!='signature'})


def context(block):
    proof=block['work'];body={k:v for k,v in block.items() if k not in {'signature','work'}}
    body['work']={k:v for k,v in proof.items() if k!='nonce'}
    return {'height':block['height'],'parent':block['previous_hash'],'body':hashlib.sha256(b'Corium/NativeWorkBody/v2\0'+encoded(body)).hexdigest(),'miner':block['validator']}


def verify(db,network,block,expected):
    require(type(block) is dict and set(block)=={'height','previous_hash','timestamp','validator','signature','transactions','work'},'exact native work block')
    p=parent(db,block['previous_hash']);require(type(block['height']) is int and block['height']==p['height']+1,'native parent/height')
    value=active(db,network,block['height']);require(value is not None,'work consensus is not active')
    proof=block['work'];recovery=Recovery.declaration(network)
    fields={'schema','activation','policy','miner_public_key','nonce'}
    if recovery is not None:
        fields.add('recovery')
        if recovery['protocol']==Recovery.SIDE:fields.add('dna')
    require(type(proof)is dict and set(proof)==fields and proof['schema']==(recovery['protocol'] if recovery else PROOF),'versioned native work proof')
    if recovery:
        require(proof['recovery']==Recovery.identity(recovery),'exact recovery chain binding')
        if recovery['protocol']==Recovery.SIDE:
            raw=Recovery.body(block,recovery)
            require(DNA.restore(proof['dna'],DNA.digest(raw))==raw,'DNA duplex binds actual block and rules')
    require(proof['activation']==policy_hash(value) and proof['policy']==commitment(value['work_policy']),'exact governed activation')
    key=miner_key(proof['miner_public_key']);require(block['validator']==hashlib.sha256(proof['miner_public_key'].encode()).hexdigest(),'native miner identity')
    integer(block['timestamp'],p['timestamp'],2**63-1)
    txs=block['transactions'];require(type(txs) is list and len(txs)<=200 and all(type(tx) is str and re.fullmatch('[a-f0-9]{64}',tx) for tx in txs) and len(set(txs))==len(txs),'bounded unique transaction hashes')
    result=verify_work(value['work_policy'],context(block),{'schema':'corium.sha256-work.v1','policy':proof['policy'],'nonce':proof['nonce']},network=network,genesis=value['work_policy']['genesis'],parent_weight=p['total_weight'])
    raw=signing_bytes(block);require(type(expected) is str and hashlib.sha256(raw).hexdigest()==expected,'native work block identity')
    signature=block['signature'];require(type(signature) is str and re.fullmatch('[a-f0-9]{16,144}',signature) and len(signature)%2==0,'bounded native DER signature')
    key.verify(bytes.fromhex(signature),raw,ec.ECDSA(hashes.SHA256()))
    return {'hash':expected,'height':block['height'],'validator':block['validator'],'total_weight':result['total_weight'],'work_weight':result['weight'],'consensus_policy':policy_hash(value),'work_verified':True,'transactions_validated_by_native_caller':False}


def mine(db,network,key_file,previous,timestamp,transactions,attempts=100000,start_nonce=0):
    p=parent(db,previous);value=active(db,network,p['height']+1);require(value is not None,'work consensus is not active')
    integer(attempts,1,1000000);integer(start_nonce,0,2**64-attempts)
    key=serialization.load_pem_private_key(Path(key_file).read_bytes(),password=None)
    require(isinstance(key,ec.EllipticCurvePrivateKey) and isinstance(key.curve,ec.SECP256K1),'native private key required')
    public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
    block={'height':p['height']+1,'previous_hash':previous,'timestamp':timestamp,'validator':hashlib.sha256(public.encode()).hexdigest(),'signature':'','transactions':transactions,'work':{'schema':PROOF,'activation':policy_hash(value),'policy':commitment(value['work_policy']),'miner_public_key':public,'nonce':0}}
    recovery=Recovery.declaration(network)
    if recovery:
        block['work']['schema']=recovery['protocol'];block['work']['recovery']=Recovery.identity(recovery)
        if recovery['protocol']==Recovery.SIDE:block['work']['dna']=DNA.duplex(Recovery.body(block,recovery))
    ctx=context(block)
    for nonce in range(start_nonce,start_nonce+attempts):
        if int(work_digest(value['work_policy'],ctx,nonce),16)>=2**(256-value['work_policy']['difficulty_bits']):continue
        block['work']['nonce']=nonce;raw=signing_bytes(block);identity=hashlib.sha256(raw).hexdigest();block['signature']=key.sign(raw,ec.ECDSA(hashes.SHA256())).hex()
        return {'block':block,**verify(db,network,block,identity)}
    raise ValueError('bounded mining work exhausted')


def record(db,network,block,identity):
    result=verify(db,network,block,identity)
    row=db.execute('SELECT height,previous_hash,timestamp,validator,signature,transactions,total_weight FROM blocks WHERE hash=?',(identity,)).fetchone();require(row is not None,'native block must already be committed in the enclosing transaction')
    require(dict(row)=={'height':block['height'],'previous_hash':block['previous_hash'],'timestamp':block['timestamp'],'validator':block['validator'],'signature':block['signature'],'transactions':json.dumps(block['transactions'],separators=(',',':')),'total_weight':result['total_weight']},'stored native block fields differ')
    old=db.execute('SELECT proof FROM block_work WHERE hash=?',(identity,)).fetchone();require(old is None or json.loads(old[0])==block['work'],'native proof identity conflict')
    db.execute('INSERT OR IGNORE INTO block_work VALUES(?,?)',(identity,encoded(block['work']).decode()));return result


def stored(db,identity):
    row=db.execute('SELECT height,previous_hash,timestamp,validator,signature,transactions FROM blocks WHERE hash=?',(identity,)).fetchone();require(row is not None,'stored native block required')
    value=dict(row);value['transactions']=json.loads(value['transactions']);proof=db.execute('SELECT proof FROM block_work WHERE hash=?',(identity,)).fetchone()
    if proof:value['work']=json.loads(proof[0])
    return value


def cooperative_state_at(db,network,height):
    """Rebuild cooperative state from the canonical prefix before height.

    The materialized cooperative_registry table is only a cache: fork rollback
    can leave it stale. Every admission/replay therefore derives authority from
    canonical block order and runs the same pure transition function.
    """
    declaration=Recovery.declaration(network)
    require(declaration is not None and height>declaration['checkpoint']['height'],
            'cooperative protocol not active')
    chain=Recovery.identity(declaration);state=Cooperative.empty(chain);start=declaration['checkpoint']['height']
    # Use a materialized checkpoint only when its recorded block remains in the
    # canonical chain and its deterministic root matches. Legacy/unanchored rows
    # and orphaned checkpoints are ignored and reconstructed from history.
    table=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cooperative_registry'").fetchone()
    if table:
        columns={row[1] for row in db.execute('PRAGMA table_info(cooperative_registry)').fetchall()}
        if {'state','height','block_hash','state_root'}<=columns:
            cached=db.execute('SELECT state,height,block_hash,state_root FROM cooperative_registry WHERE id=1').fetchone()
            if cached:
                try:
                    candidate=json.loads(cached[0]);anchor=db.execute('SELECT hash FROM blocks WHERE height=?',(cached[1],)).fetchone()
                    if (type(cached[1])is int and start<=cached[1]<height and anchor and anchor[0]==cached[2]
                        and type(candidate)is dict and candidate.get('chain')==chain
                        and Cooperative.state_root(candidate)==cached[3]):
                        state=candidate;start=cached[1]
                except (ValueError,TypeError,KeyError):
                    pass
    commands=db.execute("SELECT hash,data,block_height FROM transactions WHERE type='cooperative_command' AND block_height>? AND block_height<? ORDER BY block_height,hash",
                        (start,height)).fetchall()
    require(len(commands)<=1_000_000,'cooperative history budget')
    for txhash,raw,block_height in commands:
        block=db.execute('SELECT transactions FROM blocks WHERE height=?',(block_height,)).fetchone()
        require(block is not None,'cooperative transaction block missing')
        hashes=json.loads(block[0]);require(type(hashes)is list and len(hashes)<=200,'canonical transaction list')
        require(hashes.count(txhash)==1,'cooperative transaction absent from canonical block')
        envelope=loads(raw)
        require(type(envelope)is dict and set(envelope)=={'command','endorsements'},'cooperative envelope')
        state=Cooperative.apply(state,envelope['command'],envelope['endorsements'])
    return state


def main(args):
    action,path,network=args[:3]
    with sqlite3.connect(path) as db:
        db.row_factory=sqlite3.Row
        if action=='transaction-bytes':
            value=Recovery.declaration(network)
            print(Recovery.transaction_bytes(value,network,args[3],args[4],int(args[5]),args[6],int(args[7])))
            return
        elif action in {'cooperative-validate','cooperative-apply','cooperative-state'}:
            height=int(args[3]);state=cooperative_state_at(db,network,height)
            if action=='cooperative-state':
                result={'state':state,'state_root':Cooperative.state_root(state),'height':height}
                print(json.dumps(result,separators=(',',':')));return
            payload=DNA.loads(args[4]);require(type(payload)is dict and set(payload)=={'command','endorsements'},'cooperative envelope')
            changed=Cooperative.apply(state,payload['command'],payload['endorsements'])
            if action=='cooperative-apply':
                db.execute('CREATE TABLE IF NOT EXISTS cooperative_registry(id INTEGER PRIMARY KEY CHECK(id=1),state TEXT NOT NULL,height INTEGER,block_hash TEXT,state_root TEXT)')
                columns={row[1] for row in db.execute('PRAGMA table_info(cooperative_registry)').fetchall()}
                for name in ('height INTEGER','block_hash TEXT','state_root TEXT'):
                    if name.split()[0] not in columns:db.execute('ALTER TABLE cooperative_registry ADD COLUMN '+name)
                block=db.execute('SELECT hash FROM blocks WHERE height=?',(height,)).fetchone()
                require(block is not None,'cooperative application requires committed block')
                db.execute('INSERT OR REPLACE INTO cooperative_registry(id,state,height,block_hash,state_root) VALUES(1,?,?,?,?)',
                           (DNA.encoded(changed).decode(),height,block[0],Cooperative.state_root(changed)))
            result={'state_root':Cooperative.state_root(changed),'native_application':True}
        elif action=='proposal':result=proposal(db,network,loads(args[3]),int(args[4]))
        elif action=='preactivate':
            enabled=network.startswith('test-') or network.startswith('ziokt-test-') or network in {'ziokt-main','mainnet'} or network in Recovery.NETWORKS
            due=db.execute("SELECT 1 FROM scheduled_state_changes WHERE enactment_height=? AND type='propose_new_compute_engine' AND json_extract(data,'$.pkg_id')=? LIMIT 1",(int(args[3]),PACKAGE)).fetchone() if enabled else None
            result={'required':bool(due)}
        elif action=='mode':
            value=active(db,network,int(args[3]));result={'mode':'pow-v2' if value else 'legacy-pos','policy':policy_hash(value) if value else LEGACY}
        elif action=='mine':result=mine(db,network,args[3],args[4],int(args[5]),json.loads(args[6]))
        elif action=='verify':result=verify(db,network,loads(args[3]),args[4])
        elif action=='verify-file':
            path=Path(args[3]);require(path.is_file() and path.stat().st_size<=65536,'native block file budget');result=verify(db,network,loads(path.read_text()),args[4])
        elif action=='record':result=record(db,network,loads(args[3]),args[4])
        elif action=='stored':result=stored(db,args[3])
        elif action=='fork-guard':
            tip=db.execute('SELECT max(height) FROM blocks').fetchone()[0];value=active(db,network,tip);ancestor=db.execute('SELECT height FROM blocks WHERE hash=?',(args[3],)).fetchone();require(ancestor is not None,'known native ancestor')
            require(value is None or ancestor[0]>=value['checkpoint']['height'],'governed native checkpoint boundary');result={'allowed':True}
        else:raise ValueError('unknown native work action')
    print(json.dumps(result,separators=(',',':')))


if __name__=='__main__':main(__import__('sys').argv[1:])

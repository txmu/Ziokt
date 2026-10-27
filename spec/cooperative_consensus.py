"""Shared canonical cooperative state and native asset authorizations."""
import hashlib
import json
import re
import cooperative_protocol as Cooperative
import recovery_consensus as Recovery
import dna_protocol as DNA
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec

require=DNA.require
loads=DNA.loads

def chain_context(db,network):
    require(type(network)is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',network),'cooperative network')
    recovery=Recovery.declaration(network)
    if recovery:return Recovery.identity(recovery),recovery['checkpoint']['height']
    genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()
    require(genesis is not None and re.fullmatch('[a-f0-9]{64}',genesis[0]),'cooperative genesis')
    return hashlib.sha256(b'Corium/Cooperative/chain/v1\0'+DNA.encoded({'network':network,'genesis':genesis[0]})).hexdigest(),0

def state_at(db,network,height):
    """Rebuild cooperative state from the canonical prefix before height.

    The materialized cooperative_registry table is only a cache: fork rollback
    can leave it stale. Every admission/replay therefore derives authority from
    canonical block order and runs the same pure transition function.
    """
    chain,start=chain_context(db,network)
    require(type(height)is int and height>start,'cooperative candidate height')
    state=Cooperative.empty(chain)
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
                    candidate=DNA.loads(cached[0],4*1024*1024);anchor=db.execute('SELECT hash FROM blocks WHERE height=?',(cached[1],)).fetchone()
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


def tables(db):
    db.execute('CREATE TABLE IF NOT EXISTS cooperative_registry(id INTEGER PRIMARY KEY CHECK(id=1),state TEXT NOT NULL,height INTEGER,block_hash TEXT,state_root TEXT)')
    columns={r[1] for r in db.execute('PRAGMA table_info(cooperative_registry)')}
    for name in ('height INTEGER','block_hash TEXT','state_root TEXT'):
        if name.split()[0] not in columns:db.execute('ALTER TABLE cooperative_registry ADD COLUMN '+name)
    db.execute('CREATE TABLE IF NOT EXISTS cooperative_asset_nonces(cooperative TEXT PRIMARY KEY,nonce INTEGER NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS cooperative_note_controls(note_id TEXT PRIMARY KEY,cooperative TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS zkc_owners(edition_id TEXT PRIMARY KEY,owner TEXT NOT NULL,nonce INTEGER NOT NULL)')


def apply_command(db,network,payload,height,commit=False):
    require(type(payload)is dict and set(payload)=={'command','endorsements'},'cooperative envelope')
    state=state_at(db,network,height)
    changed=Cooperative.apply(state,payload['command'],payload['endorsements'])
    if commit:
        tables(db)
        block=db.execute('SELECT hash FROM blocks WHERE height=?',(height,)).fetchone()
        require(block is not None,'cooperative application requires committed block')
        db.execute('INSERT OR REPLACE INTO cooperative_registry(id,state,height,block_hash,state_root) VALUES(1,?,?,?,?)',
                   (DNA.encoded(changed).decode(),height,block[0],Cooperative.state_root(changed)))
    return changed


def account(chain,cooperative):
    return hashlib.sha256(b'Corium/Cooperative/custody/v1\0'+DNA.encoded({'chain':chain,'cooperative':cooperative})).hexdigest()


def has_registry(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='transactions'").fetchone():return False
    return db.execute("SELECT 1 FROM transactions WHERE type='cooperative_command' AND block_height IS NOT NULL LIMIT 1").fetchone() is not None


def owner_cooperative(db,network,owner,height):
    if not has_registry(db):return None
    state=state_at(db,network,height)
    return next((cid for cid in state['cooperatives'] if account(state['chain'],cid)==owner),None)


def asset_operation(network,kind,payload):
    return hashlib.sha256(b'Corium/Cooperative/asset-operation/v1\0'+DNA.encoded({'network':network,'type':kind,'payload':payload})).hexdigest()


def asset_bytes(command):
    return b'Corium/Cooperative/asset-authorization/v1\0'+DNA.encoded(command)


def asset_endorse(command,key):
    return {'public_key':DNA.public_key(key),'signature':key.sign(asset_bytes(command),ec.ECDSA(hashes.SHA256())).hex()}


def next_nonce(db,cid):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cooperative_asset_nonces'").fetchone():return 1
    row=db.execute('SELECT nonce FROM cooperative_asset_nonces WHERE cooperative=?',(cid,)).fetchone()
    return (row[0] if row else 0)+1


def asset_command(db,network,kind,payload,cid,height):
    state=state_at(db,network,height)
    require(cid in state['cooperatives'],'known cooperative')
    return {'schema':'corium.cooperative-asset-authorization.v1','chain':state['chain'],
            'cooperative':cid,'registry_root':Cooperative.state_root(state),'nonce':next_nonce(db,cid),
            'operation':asset_operation(network,kind,payload)}


def authorize(db,network,kind,payload,authorization,height):
    require(type(authorization)is dict and set(authorization)=={'command','endorsements'},'cooperative asset authorization envelope')
    command=authorization['command']
    require(type(command)is dict and set(command)=={'schema','chain','cooperative','registry_root','nonce','operation'},'cooperative asset authorization fields')
    cid=command['cooperative'];require(type(cid)is str,'cooperative identity')
    state=state_at(db,network,height)
    require(cid in state['cooperatives'] and state['cooperatives'][cid]['charter']==Cooperative.CHARTER,'cooperative asset charter')
    DNA.integer(command['nonce'],1,2**53-1)
    require(command==asset_command(db,network,kind,payload,cid,height),'cooperative asset chain, state, operation or nonce mismatch')
    voters=Cooperative.verify_endorsements(asset_bytes(command),authorization['endorsements'])
    Cooperative.quorum(state['cooperatives'][cid]['members'],voters)
    require(set(voters)<=set(state['cooperatives'][cid]['members']),'asset endorsements require current members')
    return {'cooperative':cid,'account':account(state['chain'],cid),'nonce':command['nonce']}


def asset_state_root(db):
    state={}
    for name in ('cooperative_asset_nonces','cooperative_note_controls','zkc_owners'):
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone()
        state[name]=[list(r) for r in db.execute('SELECT * FROM '+name+' ORDER BY 1')] if exists else []
    return hashlib.sha256(b'Corium/Cooperative/assets/v1\0'+DNA.encoded(state)).hexdigest()


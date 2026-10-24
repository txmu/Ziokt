"""Public chain identity evidence from fixed operator configuration.

A database snapshot establishes what this node serves. It does not prove remote
consensus, full replay, or that a new source protocol has been activated.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
from .dna_protocol import canonical, loads
from .protocol import secure_read


def snapshot(config):
    network = config['network']
    root = Path(config['state_root'])
    directory = root/'var/lib/corix/networks'/network
    path = directory/'blockchain/chain.db'
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=3)
    try:
        db.execute('BEGIN')
        genesis = db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()
        tip = db.execute('SELECT height,hash,previous_hash,timestamp,validator,signature,total_weight FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
        checkpoint = db.execute('SELECT height,hash FROM blocks WHERE height=50').fetchone()
        proof = db.execute('SELECT proof FROM block_work WHERE hash=?', (tip[1],)).fetchone()
        result = {'schema':'ziokt.chain-provenance.v1','network':network,
                  'genesis_hash':genesis[0],
                  'tip':dict(zip(('height','hash','previous_hash','timestamp','validator','signature','total_weight'),tip)),
                  'checkpoint':dict(zip(('height','hash'),checkpoint)) if checkpoint else None,
                  'work_proof':loads(proof[0]) if proof else None,
                  'scope':'local canonical database snapshot; full consensus replay and independent peers not assessed',
                  'recovery_declaration':None,'recovery_identity':None,
                  'recovery_declaration_verified':False,
                  'source_protocols':{'recovery_main':'ziokt-main-recovery-20261024',
                                      'dna_side':'ziokt-dna-side-20261024'},
                  'source_protocol_activation_proved':False}
        if config.get('chain_observation'):
            from .chain_observation import verify
            observation=loads(secure_read(config['chain_observation'],65536,private=False).decode())
            result['deployed_recovery_observation']=observation
            result['deployed_recovery_verification']=verify(observation,db,network)
        declaration = root/'etc/corix/networks'/network/'recovery.json'
        if declaration.is_file():
            value=loads(secure_read(declaration,65536,private=False).decode())
            # Return the signed public declaration for external verification;
            # displaying it alone is never labelled a validated activation.
            result['recovery_declaration']=value
            result['recovery_identity']=hashlib.sha256(b'Corium/Recovery/declaration/v1\0'+canonical({k:v for k,v in value.items() if k!='signature'})).hexdigest()
        return result
    finally:
        db.close()

"""Portable signed observation of an actual chain; never activates consensus."""
import hashlib,json,sqlite3,time
from pathlib import Path
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from .protocol import secure_read,strict_json,encoded

DOMAIN=b'Ziokt/deployed-chain-observation/v1\0'


def create(config,key_path):
    from .chain_provenance import snapshot
    key=serialization.load_pem_private_key(secure_read(key_path),password=None)
    if not isinstance(key,ec.EllipticCurvePrivateKey) or not isinstance(key.curve,ec.SECP256K1):raise ValueError('native node observation key required')
    public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
    auth={}
    if config.get('consensus_safety_hold'):
        hold=strict_json(secure_read(config['consensus_safety_hold'],16384),16384)
        original=hold.get('authorized_recovery')
        if isinstance(original,dict):
            fields={'schema','network_id','chain_id','genesis_hash','anchor_h50_hash','recovery_h51_hash','approved_checkpoint_height','approved_checkpoint_hash','authorized_at','validator','validator_pubkey','forbidden_legacy_hashes'}
            auth={k:v for k,v in original.items() if k in fields};auth['private_authorization_commitment']=hashlib.sha256(encoded(original)).hexdigest()
    source=dict(config);source.pop('chain_observation',None);state=snapshot(source)
    heights={0,state['tip']['height']}
    if auth:heights|={50,51,auth['approved_checkpoint_height']}
    path=Path(config['state_root'])/'var/lib/corix/networks'/config['network']/'blockchain/chain.db'
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        checkpoints=[]
        for height in sorted(heights):
            row=db.execute('SELECT height,hash,previous_hash,timestamp,validator,signature,total_weight FROM blocks WHERE height=?',(height,)).fetchone()
            if row is None:raise ValueError('declared native checkpoint is missing')
            checkpoints.append(dict(zip(('height','hash','previous_hash','timestamp','validator','signature','total_weight'),row)))
    payload={'schema':'ziokt.deployed-chain-observation.v1','observed_at':int(time.time()),'network':config['network'],'genesis_hash':state['genesis_hash'],'checkpoints':checkpoints,'recovery_authorization_public_fields':auth,'source_protocol_activation_proved':False,'independent_full_history_replay':False,'node_public_key':public}
    return {'payload':payload,'signature':key.sign(DOMAIN+encoded(payload),ec.ECDSA(hashes.SHA256())).hex()}


def verify(document,db,network):
    if type(document) is not dict or set(document)!={'payload','signature'}:raise ValueError('exact signed observation required')
    value=document['payload']
    fields={'schema','observed_at','network','genesis_hash','checkpoints','recovery_authorization_public_fields','source_protocol_activation_proved','independent_full_history_replay','node_public_key'}
    if type(value) is not dict or set(value)!=fields or value['schema']!='ziokt.deployed-chain-observation.v1' or value['network']!=network or value['source_protocol_activation_proved'] is not False or value['independent_full_history_replay'] is not False:raise ValueError('observation scope differs')
    key=serialization.load_pem_public_key(value['node_public_key'].encode())
    if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256K1):raise ValueError('native observer key required')
    key.verify(bytes.fromhex(document['signature']),DOMAIN+encoded(value),ec.ECDSA(hashes.SHA256()))
    checkpoints=value['checkpoints']
    if type(checkpoints) is not list or not 1<=len(checkpoints)<=32:raise ValueError('bounded actual checkpoints required')
    seen=set()
    for block in checkpoints:
        if type(block) is not dict or set(block)!={'height','hash','previous_hash','timestamp','validator','signature','total_weight'} or type(block['height']) is not int or block['height'] in seen:raise ValueError('exact distinct checkpoint headers required')
        seen.add(block['height']);row=db.execute('SELECT height,hash,previous_hash,timestamp,validator,signature,total_weight FROM blocks WHERE height=?',(block['height'],)).fetchone()
        if row is None or tuple(block[k] for k in ('height','hash','previous_hash','timestamp','validator','signature','total_weight'))!=tuple(row):raise ValueError('observation checkpoint does not match canonical node database')
    auth=value['recovery_authorization_public_fields']
    if not isinstance(auth,dict):raise ValueError('public recovery fields required')
    if auth:
        headers={b['height']:b['hash'] for b in checkpoints}
        if auth.get('schema')!='ziokt.recovery-authorization.v1' or auth.get('network_id')!=network or auth.get('genesis_hash')!=value['genesis_hash'] or type(auth.get('approved_checkpoint_height')) is not int:raise ValueError('public recovery chain identity differs')
        for height,expected in [(50,auth.get('anchor_h50_hash')),(51,auth.get('recovery_h51_hash')),(auth['approved_checkpoint_height'],auth.get('approved_checkpoint_hash'))]:
            if headers.get(height)!=expected:raise ValueError('public recovery checkpoint differs')
    genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()
    if 0 not in seen or not genesis or value['genesis_hash']!=genesis[0]:raise ValueError('observation genesis binding differs')
    return {'signature_verified':True,'canonical_checkpoint_headers_matched':True,'observer':hashlib.sha256(value['node_public_key'].encode()).hexdigest(),'independent_full_history_replay':False,'source_protocol_activation_proved':False}

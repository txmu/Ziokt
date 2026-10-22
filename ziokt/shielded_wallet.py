"""Local-only experimental note wallet; never load wallet witnesses into MCP."""
import base64
import hashlib
import secrets
import struct
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .protocol import encoded, strict_json


def receiver():
    # Separate one-time ownership and delivery keys; neither is a node identity.
    from ._runtime import zs_random_scalar, zs_base
    spend = zs_random_scalar()
    delivery = X25519PrivateKey.generate()
    private = delivery.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public = delivery.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    return {'public_key': zs_base(spend).hex(), 'delivery_key': public}, {'spend_key': spend.hex(), 'delivery_key': private.hex()}


def _key(private, public, aad):
    shared = private.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(public)))
    return HKDF(hashes.SHA256(), 32, hashlib.sha256(aad).digest(), b'Corium/ZKN/sealed-note/v1').derive(shared)


def _seal(public, value, aad, size):
    raw = encoded(value)
    if len(raw)+64 > size: raise ValueError('encrypted disclosure budget')
    ephemeral = X25519PrivateKey.generate(); nonce = secrets.token_bytes(12)
    prefix = ephemeral.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    plaintext = struct.pack('!I',len(raw))+raw+secrets.token_bytes(size-64-len(raw))
    return base64.b64encode(prefix+nonce+AESGCM(_key(ephemeral,public,aad)).encrypt(nonce,plaintext,aad)).decode()


def _open(private, ciphertext, aad, size):
    blob = base64.b64decode(ciphertext,validate=True)
    if len(blob)!=size: raise ValueError('fixed encrypted frame required')
    key = X25519PrivateKey.from_private_bytes(bytes.fromhex(private))
    plain = AESGCM(_key(key,blob[:32].hex(),aad)).decrypt(blob[32:44],blob[44:],aad)
    length = struct.unpack('!I',plain[:4])[0]
    if length>len(plain)-4: raise ValueError('encrypted frame length')
    return strict_json(plain[4:4+length])


def note(network, token_id, address):
    from ._runtime import zs_random_scalar, zs_commit, zs_point, zs_hex
    if set(address)!={'public_key','delivery_key'}: raise ValueError('exact one-time receiver required')
    zs_point(address['public_key']); zs_hex(address['delivery_key'])
    blind = zs_random_scalar(); commitment = zs_commit(network,token_id,blind)
    public = {'commitment':commitment,'public_key':address['public_key']}
    witness = {'network_id':network,'token_id':token_id,'blind':blind.hex(),**public}
    public['ciphertext'] = _seal(address['delivery_key'],witness,encoded({'network_id':network,**public}),2048)
    return public,witness


def open_note(network, value, keys):
    from ._runtime import zs_note, zs_commit, zs_base, zs_scalar
    zs_note(value)
    if zs_base(zs_scalar(keys['spend_key'])).hex()!=value['public_key']: raise ValueError('wrong note spending key')
    aad=encoded({'network_id':network,**{k:value[k] for k in ('commitment','public_key')}})
    witness=_open(keys['delivery_key'],value['ciphertext'],aad,2048)
    if (set(witness)!={'network_id','token_id','blind','commitment','public_key'} or witness['network_id']!=network or
            witness['commitment']!=value['commitment'] or witness['public_key']!=value['public_key'] or
            zs_commit(network,witness['token_id'],zs_scalar(witness['blind']))!=value['commitment']): raise ValueError('note witness mismatch')
    return witness


def transfer(network, ring, anchor, input_note_id, witness, keys, output, output_witness):
    from ._runtime import zs_ring_sign, zs_scalar, zs_ssub, ZS_VERSION
    identifiers=sorted(ring)
    if input_note_id not in ring: raise ValueError('input missing from ring')
    if witness['token_id']!=output_witness['token_id'] or witness['network_id']!=network or output_witness['network_id']!=network: raise ValueError('asset/network mismatch')
    value={'version':ZS_VERSION,'network_id':network,'ring':identifiers,'anchor':anchor,'note':output}
    value['proof']=zs_ring_sign(network,value,[ring[i] for i in identifiers],output['commitment'],identifiers.index(input_note_id),zs_scalar(keys['spend_key']),zs_ssub(zs_scalar(witness['blind']),zs_scalar(output_witness['blind'])))
    return value


def withdraw(network, ring, anchor, input_note_id, witness, keys, recipient):
    from ._runtime import zs_ring_sign, zs_scalar, zs_base, zs_asset, zs_hex, ZS_VERSION
    zs_hex(recipient);identifiers=sorted(ring)
    value={'version':ZS_VERSION,'network_id':network,'ring':identifiers,'anchor':anchor,
           'token_id':witness['token_id'],'recipient':recipient}
    commitment=zs_base(zs_asset(network,witness['token_id'])).hex()
    value['proof']=zs_ring_sign(network,value,[ring[i] for i in identifiers],commitment,
        identifiers.index(input_note_id),zs_scalar(keys['spend_key']),zs_scalar(witness['blind']))
    return value


def sign_transaction(network,kind,payload,private_pem=None):
    """A shielded relay uses a fresh outer key; a vote uses its real validator key."""
    import time
    from cryptography.hazmat.primitives.asymmetric import ec
    from ._runtime import ZS_TYPES, asset_transaction_bytes
    if kind not in ZS_TYPES or payload.get('network_id')!=network:raise ValueError('exact privacy transaction scope required')
    if private_pem is None:
        if kind in {'zkn_shield_deposit','privacy_review_vote','privacy_review_revoke'}:raise ValueError('existing owner/requester/validator signing identity required')
        private=ec.generate_private_key(ec.SECP256K1())
    else:
        private=serialization.load_pem_private_key(private_pem,password=None)
        if not isinstance(private,ec.EllipticCurvePrivateKey) or not isinstance(private.curve,ec.SECP256K1):raise ValueError('native secp256k1 identity required')
    tx={'type':kind,'data':payload,'timestamp':time.time_ns()//1_000_000,
        'public_key':private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')}
    tx['signature']=private.sign(asset_transaction_bytes(tx),ec.ECDSA(hashes.SHA256())).hex()
    return tx


def encrypt_wallet(value,password):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    if not isinstance(password,bytes) or not 16<=len(password)<=4096:raise ValueError('private wallet password must contain at least 16 bytes')
    raw = encoded(value)
    if len(raw) > 65520: raise ValueError('bounded encrypted wallet required')
    strict_json(raw, limit=65520)
    salt=secrets.token_bytes(16);nonce=secrets.token_bytes(12)
    key=Scrypt(salt=salt,length=32,n=32768,r=8,p=1).derive(password)
    return {'schema':'corium.shielded-wallet.v1','salt':salt.hex(),'nonce':nonce.hex(),
            'ciphertext':base64.b64encode(AESGCM(key).encrypt(nonce,raw,b'Corium/shielded-wallet/v1')).decode()}


def decrypt_wallet(value,password):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    if type(password) is not bytes or not 16 <= len(password) <= 4096: raise ValueError('bounded wallet password required')
    if type(value) is not dict or set(value)!={'schema','salt','nonce','ciphertext'} or value['schema']!='corium.shielded-wallet.v1':raise ValueError('versioned encrypted wallet required')
    if any(type(value[k]) is not str for k in ('salt','nonce','ciphertext')) or len(value['salt']) != 32 or len(value['nonce']) != 24 or len(value['ciphertext']) > 87384:
        raise ValueError('bounded encrypted wallet required')
    salt=bytes.fromhex(value['salt']);nonce=bytes.fromhex(value['nonce']);data=base64.b64decode(value['ciphertext'],validate=True)
    if len(salt)!=16 or len(nonce)!=12 or len(data)>65536 or not 16<=len(password)<=4096:raise ValueError('bounded encrypted wallet required')
    key=Scrypt(salt=salt,length=32,n=32768,r=8,p=1).derive(password)
    return strict_json(AESGCM(key).decrypt(nonce,data,b'Corium/shielded-wallet/v1'))


def address_from_keys(keys):
    from ._runtime import zs_base, zs_scalar, zs_hex, zs_point
    if type(keys) is not dict or set(keys) != {'spend_key', 'delivery_key'}:
        raise ValueError('exact wallet keys required')
    public = zs_base(zs_scalar(keys['spend_key'])).hex()
    zs_point(public)
    delivery = X25519PrivateKey.from_private_bytes(zs_hex(keys['delivery_key']))
    return {'public_key': public, 'delivery_key': delivery.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()}


def validate_wallet(wallet):
    from ._runtime import identifier, zs_testnet
    if type(wallet) is not dict or set(wallet) not in ({'network_id', 'keys', 'address'}, {'network_id', 'keys', 'address', 'recovery'}):
        raise ValueError('versioned receiver wallet required')
    identifier(wallet['network_id'], 'network_id')
    zs_testnet(wallet['network_id'])
    if address_from_keys(wallet['keys']) != wallet['address']:
        raise ValueError('wallet receiver and private keys disagree')
    return wallet


def recover_wallet(root, wallet):
    """Recover this one-time receiver from one read-only canonical DB snapshot.

    All note decryption and key-image matching stay local. Cached recovery data
    is replaced, so a reorg can restore a previously marked spent note.
    """
    from contextlib import closing
    from . import _runtime as r
    wallet = validate_wallet(wallet)
    network, keys = wallet['network_id'], wallet['keys']
    notes = []
    with closing(r.corium_db(root, network, 'blockchain/chain.db')) as db:
        db.execute('BEGIN')
        block = db.execute('SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
        if not block: raise ValueError('canonical chain head required')
        if type(block[0]) is not int or block[0]<0:raise ValueError('canonical chain height is inconsistent')
        r.zs_hex(block[1])
        if r.zs_exists(db, 'zkn_shield_notes'):
            row = db.execute('SELECT note_id,public_key,commitment,ciphertext,height FROM zkn_shield_notes WHERE public_key=?', (wallet['address']['public_key'],)).fetchone()
            if row:
                note = dict(zip(('public_key', 'commitment', 'ciphertext'), row[1:4]))
                if r.zs_note_id(note) != row[0] or not 0 <= row[4] <= block[0]:
                    raise ValueError('canonical note record is inconsistent')
                witness = open_note(network, note, keys)
                image = r.zs_mul(r.zs_scalar(keys['spend_key']), r.zs_hp(b'Corium/ZKN/key-image/v1\0' + network.encode() + b'\0', r.zs_point(note['public_key']))).hex()
                spent_row=db.execute('SELECT height,transaction_hash FROM zkn_shield_images WHERE image=?',(image,)).fetchone()
                if spent_row:
                    if type(spent_row[0]) is not int or not row[4]<=spent_row[0]<=block[0]:raise ValueError('canonical spend height is inconsistent')
                    r.zs_hex(spent_row[1])
                spent = spent_row is not None
                notes.append({'note_id': row[0], 'height': row[4], 'witness': witness, 'key_image': image, 'spent': spent})
    return {k: wallet[k] for k in ('network_id', 'keys', 'address')} | {
        'recovery': {'schema': 'corium.shielded-recovery.v1', 'anchor': {'height': block[0], 'hash': block[1]}, 'notes': notes}}


def disclosure(network, request_id, request, input_note_id, witness, keys, *, approved):
    from ._runtime import zs_schnorr_sign, zs_scalar
    # Caller must independently fetch current canonical status; consensus rechecks.
    if approved is not True or input_note_id not in request['scope'] or witness['network_id']!=network: raise ValueError('explicit approved scoped disclosure required')
    aad=encoded({'network_id':network,'request_id':request_id,'note_id':input_note_id})
    value={'network_id':network,'request_id':request_id,'note_id':input_note_id,'ciphertext':_seal(request['recipient_key'],{'schema':'corium.voluntary-opening.v1','request_id':request_id,'note_id':input_note_id,'witness':witness},aad,4096)}
    value['authorization']=zs_schnorr_sign(zs_scalar(keys['spend_key']),value,network)
    return value


def open_disclosure(network, value, recipient_private):
    aad=encoded({'network_id':network,'request_id':value['request_id'],'note_id':value['note_id']})
    return _open(recipient_private,value['ciphertext'],aad,4096)


def main():
    import argparse,json
    from pathlib import Path
    from .protocol import secure_read
    from .cli import write_exclusive
    parser=argparse.ArgumentParser(description='Local experimental shielded wallet; no MCP secret input')
    commands=parser.add_subparsers(dest='command',required=True)
    command=commands.add_parser('receiver');command.add_argument('--network',required=True);command.add_argument('--wallet',type=Path,required=True);command.add_argument('--address',type=Path,required=True);command.add_argument('--password-file',type=Path,required=True)
    for name in ('inspect', 'recover'):
        command = commands.add_parser(name)
        command.add_argument('--wallet', type=Path, required=True)
        command.add_argument('--password-file', type=Path, required=True)
        if name == 'recover':
            command.add_argument('--root', type=Path, required=True)
            command.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    if args.command != 'receiver':
        password = secure_read(args.password_file,4096).rstrip(b'\r\n')
        wallet = validate_wallet(decrypt_wallet(strict_json(secure_read(args.wallet,131072), limit=131072, string_limit=87384), password))
        if args.command == 'inspect':
            print(json.dumps({'network_id': wallet['network_id'], 'address': wallet['address'], 'production_enabled': False}))
        else:
            if args.output.exists(): raise ValueError('recovery output must be a new file')
            recovered = recover_wallet(args.root.absolute(), wallet)
            write_exclusive(args.output, encrypt_wallet(recovered, password))
            notes = recovered['recovery']['notes']
            print(json.dumps({'network_id': wallet['network_id'], 'anchor': recovered['recovery']['anchor'],
                              'owned_notes': len(notes), 'unspent_notes': sum(not note['spent'] for note in notes), 'production_enabled': False}))
        return
    from ._runtime import zs_testnet
    zs_testnet(args.network)
    if args.wallet.exists() or args.address.exists():raise ValueError('wallet and address outputs must be new files')
    address,keys=receiver();password=secure_read(args.password_file,4096).rstrip(b'\r\n')
    write_exclusive(args.wallet,encrypt_wallet({'network_id':args.network,'keys':keys,'address':address},password))
    write_exclusive(args.address,address)
    print(json.dumps({'wallet':str(args.wallet),'address':str(args.address),'network_id':args.network,'production_enabled':False}))


if __name__=='__main__':main()

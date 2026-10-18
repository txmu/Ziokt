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
    salt=secrets.token_bytes(16);nonce=secrets.token_bytes(12)
    key=Scrypt(salt=salt,length=32,n=32768,r=8,p=1).derive(password)
    return {'schema':'corium.shielded-wallet.v1','salt':salt.hex(),'nonce':nonce.hex(),
            'ciphertext':base64.b64encode(AESGCM(key).encrypt(nonce,encoded(value),b'Corium/shielded-wallet/v1')).decode()}


def decrypt_wallet(value,password):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    if set(value)!={'schema','salt','nonce','ciphertext'} or value['schema']!='corium.shielded-wallet.v1':raise ValueError('versioned encrypted wallet required')
    salt=bytes.fromhex(value['salt']);nonce=bytes.fromhex(value['nonce']);data=base64.b64decode(value['ciphertext'],validate=True)
    if len(salt)!=16 or len(nonce)!=12 or len(data)>65536 or not 16<=len(password)<=4096:raise ValueError('bounded encrypted wallet required')
    key=Scrypt(salt=salt,length=32,n=32768,r=8,p=1).derive(password)
    return strict_json(AESGCM(key).decrypt(nonce,data,b'Corium/shielded-wallet/v1'))


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
    args=parser.parse_args()
    from ._runtime import zs_testnet
    zs_testnet(args.network)
    if args.wallet.exists() or args.address.exists():raise ValueError('wallet and address outputs must be new files')
    address,keys=receiver();password=secure_read(args.password_file,4096).rstrip(b'\r\n')
    write_exclusive(args.wallet,encrypt_wallet({'network_id':args.network,'keys':keys,'address':address},password))
    write_exclusive(args.address,address)
    print(json.dumps({'wallet':str(args.wallet),'address':str(args.address),'network_id':args.network,'production_enabled':False}))


if __name__=='__main__':main()

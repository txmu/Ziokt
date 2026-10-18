"""Local-only padded service descriptors. Secret keys never enter DNS/MCP."""
import base64
import os
import struct
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey,X25519PublicKey
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .protocol import encoded,strict_json,ProtocolError
from .naming import split_name,GROUPS


def context(network_id,name,component):
    canonical,_,_,_=split_name(name)
    if not isinstance(network_id,str) or not 1<=len(network_id)<=64 or component not in GROUPS:
        raise ValueError('explicit network and target component required')
    return b'Ziokt/private-name/v1\n'+encoded({'network_id':network_id,'name':canonical,'component':component})


def seal(value,recipient_public,*,network_id,name,component):
    aad=context(network_id,name,component);data=encoded(value)
    if len(data)>4032:raise ValueError('bounded service descriptor required')
    ephemeral=X25519PrivateKey.generate();public=ephemeral.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    shared=ephemeral.exchange(X25519PublicKey.from_public_bytes(recipient_public))
    key=HKDF(hashes.SHA256(),32,None,aad).derive(shared);nonce=os.urandom(12)
    padded=struct.pack('!I',len(data))+data+os.urandom(4036-len(data)-4)
    cipher=public+nonce+AESGCM(key).encrypt(nonce,padded,aad)
    assert len(cipher)==4096
    return {'scheme':'ziokt.sealed.v1','ciphertext':base64.b64encode(cipher).decode()}


def open_descriptor(value,recipient_private,*,network_id,name,component):
    try:
        if not isinstance(value,dict) or set(value)!={'scheme','ciphertext'} or value['scheme']!='ziokt.sealed.v1':raise ValueError()
        cipher=base64.b64decode(value['ciphertext'],validate=True)
        if len(cipher)!=4096:raise ValueError()
        aad=context(network_id,name,component)
        shared=X25519PrivateKey.from_private_bytes(recipient_private).exchange(X25519PublicKey.from_public_bytes(cipher[:32]))
        key=HKDF(hashes.SHA256(),32,None,aad).derive(shared)
        padded=AESGCM(key).decrypt(cipher[32:44],cipher[44:],aad)
        size=struct.unpack('!I',padded[:4])[0]
        if size>4032:raise ValueError()
        return strict_json(padded[4:4+size])
    except Exception as error:
        raise ProtocolError('PRIVATE_NAME_REJECTED','private description authentication failed') from error

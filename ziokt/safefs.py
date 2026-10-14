"""SafeFS modern private vault: bounded AEAD objects and federated ciphertext.

No host mounts, kernel settings, network-interface changes, pickle loading or
physical-erasure claims. A compromised OS can still observe decrypted memory.
"""
import hashlib
from pathlib import Path,PurePosixPath
import secrets
import unicodedata

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.exceptions import InvalidTag

from .ano import defence
from .protocol import ProtocolError,encoded,identifier,make_private,secure_read,strict_json
from .cli import write_binary_exclusive

MAX_FILE=8*1024*1024
MAX_SEALED=16*1024*1024


def virtual_name(name):
    if (not isinstance(name,str) or not 1<=len(name.encode())<=1024 or unicodedata.normalize('NFC',name)!=name or
            '\\' in name or '\0' in name or any(ord(c)<32 for c in name) or PurePosixPath(name).is_absolute() or
            any(p in {'..','.'} for p in name.split('/')) or len(name.split('/'))>8 or '' in name.split('/')):
        raise ProtocolError('INVALID_SAFEFS','normalized relative virtual filename required')
    return name


def _private_dir(root):
    root=Path(root)
    if root.is_symlink():raise ProtocolError('UNSAFE_FILE','vault path cannot be a symlink')
    root.mkdir(mode=0o700,parents=True,exist_ok=True);make_private(root)
    return root


class Vault:
    def __init__(self,root,scope,key):
        identifier(scope,'vault scope')
        if not isinstance(key,bytes) or len(key)!=32:raise ProtocolError('INVALID_SAFEFS','independent private 32-byte vault key required')
        self.root=_private_dir(root);self.objects=_private_dir(self.root/'objects');self.scope=scope;self.key=key

    def _key(self,salt):return HKDF(hashes.SHA256(),32,salt,('Ziokt/SafeFS/key/v1/'+self.scope).encode()).derive(self.key)

    def seal(self,name,data):
        virtual_name(name)
        decision=defence({'owned_key':len(self.key)==32,'bounded_content':isinstance(data,bytes) and len(data)<=MAX_FILE},('owned_key','bounded_content'))
        if decision['decision']!='allow':raise ProtocolError('SAFEFS_LIMIT','vault plaintext exceeds bounded file budget')
        metadata=encoded({'schema':'ziokt.safefs-file.v1','name':name,'size':len(data)})
        plain=len(metadata).to_bytes(4,'big')+metadata+data
        size=max(16384,1<<(len(plain)+44-1).bit_length())
        if size>MAX_SEALED:raise ProtocolError('SAFEFS_LIMIT','sealed vault object exceeds budget')
        salt=secrets.token_bytes(16);nonce=secrets.token_bytes(12);plain+=secrets.token_bytes(size-44-len(plain))
        return salt+nonce+AESGCM(self._key(salt)).encrypt(nonce,plain,('Ziokt/SafeFS/file/v1/'+self.scope).encode())

    def open(self,blob):
        if not isinstance(blob,bytes) or not 16384<=len(blob)<=MAX_SEALED or len(blob)&(len(blob)-1):raise ProtocolError('INVALID_SAFEFS','padded authenticated vault object required')
        try:
            plain=AESGCM(self._key(blob[:16])).decrypt(blob[16:28],blob[28:],('Ziokt/SafeFS/file/v1/'+self.scope).encode())
            header=int.from_bytes(plain[:4],'big')
            if not 1<=header<=2048 or header>len(plain)-4:raise ValueError()
            value=strict_json(plain[4:4+header],2048)
            if (not isinstance(value,dict) or set(value)!={'schema','name','size'} or value['schema']!='ziokt.safefs-file.v1' or
                    type(value['size']) is not int or not 0<=value['size']<=MAX_FILE or 4+header+value['size']>len(plain)):raise ValueError()
            virtual_name(value['name']);return value['name'],plain[4+header:4+header+value['size']]
        except (ValueError,TypeError,InvalidTag):raise ProtocolError('SAFEFS_AUTH_FAILED','vault authentication or scope rejected')

    def put(self,name,data):
        blob=self.seal(name,data);digest='sha256:'+hashlib.sha256(blob).hexdigest();write_binary_exclusive(self.objects/digest[7:],blob)
        return {'schema':'ziokt.safefs-object.v1','digest':digest,'sealed_size':len(blob),'plaintext_metadata_public':False}

    def blob(self,digest):
        from .community import hash_id
        hash_id(digest);blob=secure_read(self.objects/digest[7:],MAX_SEALED)
        if hashlib.sha256(blob).hexdigest()!=digest[7:]:raise ProtocolError('ARTIFACT_DIGEST_MISMATCH','vault ciphertext changed')
        return blob

    def get(self,digest):return self.open(self.blob(digest))

    def publish(self,community,signing_key,digest):
        blob=self.blob(digest)
        # Independent application/vault and community confidentiality domains.
        manifest=community.put_file(blob)
        event=community.publish(signing_key,'files','safefs-'+digest[7:48],{'name':'SafeFS encrypted object',**manifest})
        return {'schema':'ziokt.safefs-publication.v1','event':event,'ciphertext_digest':digest,'plaintext_disclosed':False}


def sandbox_plan():
    import os,shutil
    return {'schema':'ziokt.safefs-sandbox.v1','requires_root':False,'host_mutations':False,
        'namespace_tool_available':shutil.which('unshare') is not None and os.name=='posix',
        'kernel_isolation_verified':False,'network_required':False,'memory_budget':64*1024*1024,
        'physical_erasure_guaranteed':False}

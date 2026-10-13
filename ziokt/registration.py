"""Optional native-chain registration gate with privately encrypted text uploads."""
import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
import struct

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey,X25519PublicKey
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .client import NativeClient
from .config import load
from .community import exact,PUBLIC,content_id
from .protocol import ProtocolError,secure_read,make_private,encoded
from .security import sign


def registration_policy(value,members):
    exact(value,{'required','provider_id','issuer','admin_public','admin_mailbox'})
    if (type(value['required']) is not bool or not isinstance(value['provider_id'],str) or
            any(not isinstance(value[k],str) or not PUBLIC.fullmatch(value[k]) for k in ('issuer','admin_public','admin_mailbox')) or
            value['admin_public'] not in members):
        raise ProtocolError('INVALID_CONFIG','exact registration authority and mailbox required')
    return value


class RegistrationGate:
    def __init__(self,community,config_path):
        self.community=community
        self.policy=registration_policy(community.policy['registration'],community.policy['members'])
        federation=load(config_path)
        if not federation['enabled'] or federation['federation_id']!=community.community_id:
            raise ProtocolError('SCOPE_MISMATCH','enabled registration federation must match community')
        provider=next((p for p in federation['providers'] if p['provider_id']==self.policy['provider_id'] and p['native_project']=='corium'),None)
        if provider is None:raise ProtocolError('INVALID_CONFIG','fixed native Corium registration authority required')
        self.client=NativeClient(community.community_id,provider)
        self.directory=community.root/'registration-documents'
        if self.directory.is_symlink():raise ProtocolError('UNSAFE_FILE','registration vault cannot be a symlink')
        self.directory.mkdir(mode=0o700,exist_ok=True);make_private(self.directory)
        with community.lock,community.db:
            community.db.execute('CREATE TABLE IF NOT EXISTS registration_uploads (member TEXT,policy TEXT,commitment TEXT,cipher_digest TEXT,tx TEXT,PRIMARY KEY(member,policy))')

    def submit(self,member,data):
        with self.community.lock:
            self.community._current()
            if member not in self.community.policy['members']:raise ProtocolError('POLICY_DENIED','community member required for registration')
            if not isinstance(data,bytes) or not 1<=len(data)<=65536:raise ProtocolError('INVALID_DOCUMENT','bounded personal-information text file required')
            try:text=data.decode('utf-8','strict')
            except UnicodeDecodeError:raise ProtocolError('INVALID_DOCUMENT','UTF-8 text file required')
            if not text.strip():raise ProtocolError('INVALID_DOCUMENT','nonempty personal-information text required')
            salt=secrets.token_bytes(32);commitment=content_id(salt+data)
            aad=encoded({'community':self.community.community_id,'member':member,'policy':self.community.policy_id,'commitment':commitment})
            ephemeral=X25519PrivateKey.generate()
            try:shared=ephemeral.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(self.policy['admin_mailbox'])))
            except ValueError:raise ProtocolError('INVALID_CONFIG','registration mailbox public key rejected')
            key=HKDF(hashes.SHA256(),32,None,b'Ziokt/registration/v1\n'+aad).derive(shared)
            nonce=secrets.token_bytes(12)
            public=ephemeral.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
            cipher=public+nonce+AESGCM(key).encrypt(nonce,salt+data,aad)
            target=self.directory/content_id(cipher)[7:]
            from .cli import write_binary_exclusive
            write_binary_exclusive(target,cipher)
            operation='identity-'+hashlib.sha256((member+commitment+self.community.policy_id).encode()).hexdigest()[:48]
            plan=self.client.call('operation.prepare',{'operation_id':operation,'action':'identity.register','resource':'identity:'+member,
                'arguments':{'document_commitment':commitment,'policy_digest':self.community.policy_id},'expected_revision':None})
            result=self.client.call('operation.commit',{'operation_id':operation,'plan_digest':plan['plan_digest']})
            with self.community.db:
                self.community.db.execute('INSERT OR REPLACE INTO registration_uploads VALUES (?,?,?,?,?)',
                    (member,self.community.policy_id,commitment,content_id(cipher),result['result']['transaction_hash']))
            return {'submitted':True,'transaction_hash':result['result']['transaction_hash'],'state':'等待链上登记确认'}

    def status(self,member):
        with self.community.lock:
            self.community._current()
            row=self.community.db.execute('SELECT commitment,cipher_digest,tx FROM registration_uploads WHERE member=? AND policy=?',(member,self.community.policy_id)).fetchone()
            if not row:return {'registered':False,'state':'请上传个人信息文本文件'}
            secure_read(self.directory/row[1][7:],65632)
            try:fact=self.client.call('identity.fact',{'member_public':member,'policy_digest':self.community.policy_id,'issuer':self.policy['issuer']})
            except ProtocolError as exc:
                if exc.code=='NATIVE_FACT_PENDING':return {'registered':False,'state':'等待链上登记确认','transaction_hash':row[2]}
                raise
            if (fact.get('registered') is not True or fact.get('member_public')!=member or fact.get('policy_digest')!=self.community.policy_id or
                    fact.get('issuer')!=self.policy['issuer'] or fact.get('document_commitment')!=row[0] or fact.get('transaction_hash')!=row[2]):
                raise ProtocolError('REGISTRATION_REJECTED','registration proof differs from uploaded document commitment')
            return {'registered':True,'state':'资料登记已上链','transaction_hash':row[2],'height':fact['height']}

    def require(self,member):
        if self.policy['required'] and not self.status(member)['registered']:
            raise ProtocolError('REGISTRATION_REQUIRED','请上传个人信息文本文件并完成链上登记')

    def purge(self,member):
        with self.community.lock:
            self.community._current()
            row=self.community.db.execute('SELECT cipher_digest FROM registration_uploads WHERE member=? AND policy=?',(member,self.community.policy_id)).fetchone()
            if not row: return {'purged':False,'state':'无登记记录'}
            target=self.directory/row[0][7:]
            if target.is_symlink():
                raise ProtocolError('UNSAFE_FILE','registration ciphertext cannot be a symlink')
            if target.exists():
                secure_read(target,65632)
                # Unlink encrypted material without following or overwriting
                # another file through a replaced path. Storage media and
                # backups determine whether physical erasure is possible.
                target.unlink(missing_ok=True)
            self.community.db.execute('PRAGMA secure_delete=ON')
            with self.community.db:
                self.community.db.execute('DELETE FROM registration_uploads WHERE member=? AND policy=?',(member,self.community.policy_id))
            return {'purged':True,'member':member,'state':'本地登记材料与索引已删除'}


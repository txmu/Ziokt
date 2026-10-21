"""Private collectible gifts: fresh receivers, sealed receipts and durable retry.

Transport relays have no collectible keys. The native ledger still exposes
collectible references and one-time ownership transitions; this is not a proof
of untraceability against colluding relays or a global traffic observer.
"""
import base64
import hashlib
import os
import stat
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import _runtime
from .community_privacy import mailbox_public, seal_mail, open_mail
from .protocol import ProtocolError, encoded, identifier, make_private, secure_read, strict_json

HEX = re.compile('[a-f0-9]{64}\\Z')


def _key(pem):
    if not isinstance(pem,str) or len(pem)>8192:
        raise ProtocolError('INVALID_ZKN', 'bounded native ownership key required')
    try:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256K1): raise ValueError()
        return key
    except (ValueError, TypeError): raise ProtocolError('INVALID_ZKN', 'native collectible ownership key required')


def public_pem(key):
    return key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')


def receiver(network, lifetime=3600):
    """Generate a new offer and separate private wallet material for ONE gift."""
    identifier(network, 'network')
    if type(lifetime) is not int or not 1 <= lifetime <= 86400: raise ProtocolError('INVALID_ZKN', 'bounded receiver lifetime required')
    key = ec.generate_private_key(ec.SECP256K1()); mail = secrets.token_bytes(32)
    value = {'schema': 'ziokt.zkn-receiver.v1', 'network_id': network, 'public_key': public_pem(key),
             'mailbox': mailbox_public(mail), 'nonce': secrets.token_hex(16), 'expires': int(time.time())+lifetime}
    offer = {**value, 'signature': _runtime.native_ec_sign(key, b'Ziokt/ZKN/receiver/v1\n'+encoded(value))}
    wallet = {'schema': 'ziokt.zkn-wallet.v1', 'offer': offer, 'mailbox_private': mail.hex(),
              'owner_private': key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()}
    return offer, wallet


def verify_receiver(offer, network):
    fields = {'schema', 'network_id', 'public_key', 'mailbox', 'nonce', 'expires', 'signature'}
    if (not isinstance(offer, dict) or set(offer) != fields or offer['schema'] != 'ziokt.zkn-receiver.v1' or
            offer['network_id'] != network or not isinstance(offer['public_key'],str) or len(offer['public_key'])>1024 or
            not isinstance(offer['signature'],str) or len(offer['signature'])>160 or not isinstance(offer['mailbox'], str) or not HEX.fullmatch(offer['mailbox']) or
            not isinstance(offer['nonce'], str) or not re.fullmatch('[a-f0-9]{32}', offer['nonce']) or
            type(offer['expires']) is not int or not int(time.time()) < offer['expires'] <= int(time.time())+86400):
        raise ProtocolError('INVALID_ZKN', 'fresh scoped one-time receiver required')
    _runtime.native_ec_verify(offer['public_key'], offer['signature'], b'Ziokt/ZKN/receiver/v1\n'+encoded({k:v for k,v in offer.items() if k!='signature'}))
    return hashlib.sha256(offer['public_key'].encode()).hexdigest()


def verify_snapshot(snapshot, network):
    if (not isinstance(snapshot,dict) or set(snapshot)!={'manifest','public_key','signature'} or
            not isinstance(snapshot['public_key'],str) or len(snapshot['public_key'])>1024 or
            not isinstance(snapshot['signature'],str) or len(snapshot['signature'])>160): raise ProtocolError('INVALID_ZKN','signed collectible snapshot required')
    value=snapshot['manifest']
    fields={'schema','network_id','token_id','block_hash','height','packer','packed_at','contents_digest','contents_size','zkt_score'}
    if not isinstance(value,dict) or not isinstance(value.get('schema'),str) or value['schema'] not in {'ziokt.zkn-snapshot.v1','ziokt.zkn-snapshot.v2'}:
        raise ProtocolError('INVALID_ZKN','known collectible snapshot version required')
    v2=value['schema'].endswith('.v2')
    if v2: fields|={'lucky_digit','relay_obligation'}
    if (set(value)!=fields or value['network_id']!=network or
            any(not isinstance(value[k],str) or not HEX.fullmatch(value[k]) for k in ('token_id','block_hash','packer')) or
            value['token_id']!=_runtime.asset_token_id(network,value['block_hash']) or
            hashlib.sha256(snapshot['public_key'].rstrip('\n').encode()).hexdigest()!=value['packer'] or
            not isinstance(value['contents_digest'],str) or not re.fullmatch('sha256:[a-f0-9]{64}',value['contents_digest']) or
            any(type(value[k]) is not int or not 0<=value[k]<2**53 for k in ('height','packed_at','contents_size','zkt_score')) or
            value['contents_size']>64*1024*1024 or
            v2 and (not isinstance(value['lucky_digit'],str) or not re.fullmatch('[0-9A-F]',value['lucky_digit']) or value['relay_obligation']!='free-p2p-forwarding-v1')):
        raise ProtocolError('INVALID_ZKN','collectible snapshot scope or content changed')
    _runtime.native_ec_verify(snapshot['public_key'],snapshot['signature'],(b'Ziokt/ZKN/snapshot/v2\n' if v2 else b'Ziokt/ZKN/snapshot/v1\n')+encoded(value))
    return value


def gift(snapshot, nonce, offer, owner_private, *, extension=None):
    network=offer.get('network_id') if isinstance(offer,dict) else None
    value=verify_snapshot(snapshot,network)
    recipient=verify_receiver(offer,network)
    if type(nonce) is not int or not 1<=nonce<2**53: raise ProtocolError('INVALID_ZKN','next collectible sequence required')
    receipt={'schema':'ziokt.zkn-receipt.v1','network_id':network,'token_id':value['token_id'],'nonce':nonce,
             'recipient':recipient,'manifest_digest':'sha256:'+hashlib.sha256(encoded(snapshot)).hexdigest(),
             'lucky_digit':value.get('lucky_digit'),'offer_nonce':offer['nonce']}
    if extension is not None:
        extension({'schema':'ziokt.extension-event.v1','kind':'zkn-gift','network_id':network,
                   'content_digest':receipt['manifest_digest'],'hops':2,'private':True,'free_forwarding':True})
    sealed=seal_mail(recipient,offer['mailbox'],'ZKN',encoded(receipt).decode())
    tx={'type':'zkn_private_transfer','data':{'network_id':network,'token_id':value['token_id'],'nonce':nonce,
        'recipient':recipient,'receipt':sealed['ciphertext']},'timestamp':int(time.time()),'public_key':public_pem(_key(owner_private))}
    tx['signature']=_runtime.native_ec_sign(_key(owner_private),_runtime.asset_transaction_bytes(tx))
    _runtime.asset_signed_gift(tx,network)
    return tx


def accept_gift(wallet, snapshot, transaction, fact, *, confirmations=2):
    if not isinstance(wallet,dict) or set(wallet)!={'schema','offer','mailbox_private','owner_private'} or wallet['schema']!='ziokt.zkn-wallet.v1':
        raise ProtocolError('INVALID_ZKN','private one-time wallet required')
    network=wallet['offer']['network_id'];value=verify_snapshot(snapshot,network)
    tx,tx_hash,_=_runtime.asset_signed_gift(transaction,network)
    if tx['data']['token_id'] != value['token_id']:
        raise ProtocolError('GIFT_REJECTED', 'gift transaction and collectible snapshot differ')
    # An expired invitation does not invalidate a gift already included.
    recipient=hashlib.sha256(public_pem(_key(wallet['owner_private'])).encode()).hexdigest()
    if tx['data']['recipient']!=recipient or public_pem(_key(wallet['owner_private']))!=wallet['offer']['public_key']:
        raise ProtocolError('POLICY_DENIED','gift belongs to another receiver')
    if type(confirmations) is not int or not 1<=confirmations<=128: raise ProtocolError('INVALID_ZKN','bounded confirmation policy required')
    from .ano import defence
    if (not isinstance(fact,dict) or fact.get('phase')!='on-chain' or fact.get('transaction_hash')!=tx_hash or
            fact.get('transaction')!=tx or type(fact.get('confirmations')) is not int or fact['confirmations']<confirmations or
            not isinstance(fact.get('inclusion'),dict) or fact['inclusion'].get('assurance')!='native-signed-inclusion'):
        raise ProtocolError('GIFT_PENDING','gift needs native signed inclusion on the reviewed canonical branch')
    decision=defence({'transaction_signature':True,'receiver_binding':tx['data']['recipient']==recipient,'native_inclusion':fact['inclusion']['assurance']=='native-signed-inclusion',
        'confirmation_depth':fact['confirmations']>=confirmations},('transaction_signature','receiver_binding','native_inclusion','confirmation_depth'))
    if decision['decision']!='allow':raise ProtocolError('GIFT_PENDING','collectible defensive evidence incomplete')
    plain=open_mail(bytes.fromhex(wallet['mailbox_private']),recipient,{'to':recipient,'ciphertext':tx['data']['receipt']})
    expected={'schema':'ziokt.zkn-receipt.v1','network_id':network,'token_id':value['token_id'],'nonce':tx['data']['nonce'],
              'recipient':recipient,'manifest_digest':'sha256:'+hashlib.sha256(encoded(snapshot)).hexdigest(),
              'lucky_digit':value.get('lucky_digit'),'offer_nonce':wallet['offer']['nonce']}
    if plain['subject']!='ZKN' or strict_json(plain['text'].encode())!=expected: raise ProtocolError('GIFT_REJECTED','sealed collectible receipt changed')
    return {**expected,'transaction_hash':tx_hash,'confirmed':True,'fee_required':False}


DELIVERY_SIZE=32768


def delivery_digest(request,delivery_id):
    return 'sha256:'+hashlib.sha256(encoded({'schema':'ziokt.zkn-delivery.v2','delivery_id':delivery_id,'request':request})).hexdigest()


def wrap_delivery(value,delivery_id,maximum,*,response=False):
    """Fresh fixed-size transport capsule; existing end-to-end mTLS seals its bytes."""
    from .remote import padded_json
    if not isinstance(delivery_id,str) or not HEX.fullmatch(delivery_id) or delivery_id=='0'*64:
        raise ProtocolError('INVALID_REQUEST','fresh bounded collectible delivery identifier required')
    schema='ziokt.zkn-delivery-result.v2' if response else 'ziokt.zkn-delivery.v2'
    return padded_json({'schema':schema,'delivery_id':delivery_id,'payload':base64.b64encode(encoded(value)).decode()},maximum,fixed_size=DELIVERY_SIZE)


def unwrap_delivery(value,length,*,response=False):
    from .remote import valid_padding
    schema='ziokt.zkn-delivery-result.v2' if response else 'ziokt.zkn-delivery.v2'
    if (not isinstance(value,dict) or set(value)!={'schema','delivery_id','payload','padding'} or value['schema']!=schema or
            length!=DELIVERY_SIZE or not isinstance(value['delivery_id'],str) or not HEX.fullmatch(value['delivery_id']) or value['delivery_id']=='0'*64 or
            not isinstance(value['payload'],str) or len(value['payload'])>DELIVERY_SIZE or not valid_padding(value['padding'])):
        raise ProtocolError('INVALID_REQUEST','fixed versioned collectible delivery capsule required')
    try:inner=strict_json(base64.b64decode(value['payload'],validate=True),DELIVERY_SIZE)
    except (ValueError,TypeError):raise ProtocolError('INVALID_REQUEST','collectible capsule payload rejected')
    if not isinstance(inner,dict) or not response and set(inner)!={'request','grant'}:
        raise ProtocolError('INVALID_REQUEST','typed collectible capsule payload required')
    return inner,value['delivery_id']


MAX_OUTBOX_BYTES=256*1024*1024
MAX_GIFT_BYTES=65536


class GiftOutbox:
    """Encrypted durable signed bytes, bounded work, idempotent chain reconciliation."""
    def __init__(self,path,key,*,privacy_mode='mixed',mix_window=(1,8)):
        if not isinstance(privacy_mode,str) or privacy_mode not in {'mixed','legacy'} or not isinstance(mix_window,tuple) or len(mix_window)!=2 or any(type(n) is not int for n in mix_window) or not 0<=mix_window[0]<=mix_window[1]<=60:
            raise ProtocolError('INVALID_ZKN','bounded explicit private delivery scheduling required')
        self.privacy_mode,self.mix_window=privacy_mode,mix_window
        path=Path(path)
        if not isinstance(key,bytes) or len(key)!=32: raise ProtocolError('INVALID_ZKN','private 32-byte outbox key required')
        if path.is_symlink(): raise ProtocolError('UNSAFE_FILE','outbox cannot be a symlink')
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if path.exists():
            # Check metadata without reading the whole private database into RAM.
            descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
            try:
                info=os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode) or os.name!='nt' and (info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600):
                    raise ProtocolError('UNSAFE_FILE','owner-private regular outbox database required')
            finally:os.close(descriptor)
        self.key=key;self.lock=threading.RLock()
        self.db=sqlite3.connect(path,timeout=5,check_same_thread=False);make_private(path)
        self.db.execute('PRAGMA synchronous=FULL');self.db.execute('PRAGMA secure_delete=ON')
        self.db.execute('PRAGMA cache_size=-2048');self.db.execute('PRAGMA mmap_size=0')
        page_size=self.db.execute('PRAGMA page_size').fetchone()[0]
        pages=self.db.execute('PRAGMA page_count').fetchone()[0]
        # Preserve oversized legacy databases for reading/reconciliation, but do
        # not permit them to grow. Newly created databases cap allocation at 256MiB.
        self.db.execute('PRAGMA max_page_count='+str(max(pages,MAX_OUTBOX_BYTES//page_size)))
        self.db.execute('CREATE TABLE IF NOT EXISTS gifts(id TEXT PRIMARY KEY,body BLOB,phase TEXT,attempts INTEGER,next_try INTEGER)')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            columns={row[1] for row in self.db.execute('PRAGMA table_info(gifts)')}
            if 'operation_id' not in columns:self.db.execute('ALTER TABLE gifts ADD COLUMN operation_id TEXT')
            if 'delivery_mode' not in columns:self.db.execute("ALTER TABLE gifts ADD COLUMN delivery_mode TEXT NOT NULL DEFAULT 'legacy'")
            if 'lease_token' not in columns:self.db.execute('ALTER TABLE gifts ADD COLUMN lease_token TEXT')
            if 'lease_until' not in columns:self.db.execute('ALTER TABLE gifts ADD COLUMN lease_until INTEGER NOT NULL DEFAULT 0')
            # Existing signed bodies and keys are untouched. Preserve the latest old
            # operation intent when migrating a queue whose acknowledgement was lost.
            for ident,attempts in self.db.execute('SELECT id,attempts FROM gifts WHERE operation_id IS NULL').fetchall():
                self.db.execute('UPDATE gifts SET operation_id=? WHERE id=?',('gift-'+ident[:40]+'-'+str(max(0,attempts-1)),ident))

    def close(self): self.db.close()

    def enqueue(self,tx):
        _,tx_hash,_=_runtime.asset_signed_gift(tx,tx['data']['network_id'])
        with self.lock,self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old=self.db.execute('SELECT body FROM gifts WHERE id=?',(tx_hash,)).fetchone()
            if old:
                if self._open(tx_hash,old[0])!=tx: raise ProtocolError('IDEMPOTENCY_CONFLICT','queued gift changed')
                return tx_hash
            if len(encoded(tx))>MAX_GIFT_BYTES:raise ProtocolError('OUTBOX_LIMIT','signed gift exceeds durable row budget')
            page_size=self.db.execute('PRAGMA page_size').fetchone()[0]
            pages=self.db.execute('PRAGMA page_count').fetchone()[0]
            if pages*page_size+len(encoded(tx))+1024*1024>MAX_OUTBOX_BYTES:raise ProtocolError('BACKPRESSURE','outbox byte budget requires archival')
            if self.db.execute('SELECT COUNT(*) FROM gifts').fetchone()[0]>=4096: raise ProtocolError('BACKPRESSURE','collectible outbox requires archival')
            nonce=secrets.token_bytes(12);body=nonce+AESGCM(self.key).encrypt(nonce,encoded(tx),tx_hash.encode())
            delay=0 if self.privacy_mode=='legacy' else self.mix_window[0]+secrets.randbelow(self.mix_window[1]-self.mix_window[0]+1)
            self.db.execute('INSERT INTO gifts(id,body,phase,attempts,next_try,operation_id,delivery_mode) VALUES (?,?,\'queued\',0,?,?,?)',(tx_hash,body,int(time.time())+delay,'gift-'+secrets.token_hex(24),self.privacy_mode))
        return tx_hash

    def _open(self,tx_hash,body):
        from cryptography.exceptions import InvalidTag
        try: return strict_json(AESGCM(self.key).decrypt(body[:12],body[12:],tx_hash.encode()))
        except (ValueError,InvalidTag): raise ProtocolError('OUTBOX_AUTH_FAILED','outbox authentication rejected')

    def status(self):
        with self.lock:
            return [{'transaction_hash':r[0],'phase':r[1],'attempts':r[2]} for r in self.db.execute('SELECT id,phase,attempts FROM gifts ORDER BY id LIMIT 4096')]

    def cycle(self,call,choose_route,*,confirmations=2,maximum=8,cancellation=None):
        if type(confirmations) is not int or not 1<=confirmations<=128 or type(maximum) is not int or not 1<=maximum<=16:
            raise ProtocolError('INVALID_ZKN','bounded gift work and confirmation policy required')
        with self.lock:
            now=int(time.time())
            rows=self.db.execute("SELECT id,attempts,operation_id,delivery_mode,next_try FROM gifts WHERE phase!='conflict' AND next_try<=? AND lease_until<=? LIMIT 4096",(now,now)).fetchall()
            # Mix newly due entries, but give aged entries bounded-queue FIFO
            # priority so random selection cannot starve an individual gift.
            aged=sorted((row for row in rows if row[4]<=now-60),key=lambda row:row[4])[:maximum]
            fresh=[row for row in rows if row not in aged]
            secrets.SystemRandom().shuffle(fresh)
            chosen=aged+fresh[:maximum-len(aged)]
            secrets.SystemRandom().shuffle(chosen)
            for tx_hash,attempts,operation_id,delivery_mode,_ in chosen:
                if cancellation is not None and cancellation.is_set():break
                lease=secrets.token_hex(32)
                with self.db:
                    self.db.execute('BEGIN IMMEDIATE')
                    now=int(time.time())
                    claimed=self.db.execute("UPDATE gifts SET lease_token=?,lease_until=? WHERE id=? AND phase!='conflict' AND next_try<=? AND lease_until<=?",(lease,now+300,tx_hash,now,now)).rowcount
                    if not claimed:continue
                    attempts,operation_id=self.db.execute('SELECT attempts,operation_id FROM gifts WHERE id=?',(tx_hash,)).fetchone()
                row=self.db.execute('SELECT length(body),substr(body,1,?) FROM gifts WHERE id=?',(MAX_GIFT_BYTES+29,tx_hash)).fetchone()
                if row[0]>MAX_GIFT_BYTES+28:raise ProtocolError('OUTBOX_LIMIT','stored gift exceeds row budget')
                body=row[1]
                tx=self._open(tx_hash,body);phase='queued';route=None
                def renew():
                    with self.db:
                        now=int(time.time())
                        owned=self.db.execute('UPDATE gifts SET lease_until=? WHERE id=? AND lease_token=? AND lease_until>?',(now+300,tx_hash,lease,now)).rowcount
                    if not owned:raise ProtocolError('OUTBOX_LEASE_LOST','delivery worker lease expired or changed; reconcile before retry')
                def owned_call(method,arguments,route):
                    renew()
                    result=call(method,arguments,route)
                    renew()
                    return result
                try:
                    route=choose_route(tx_hash,attempts)
                    # Even a confirmed row is rechecked, so a branch rollback
                    # returns it to waiting rather than silently losing custody.
                    fact=owned_call('zkn.fact',{'transaction_hash':tx_hash},route)
                    if not isinstance(fact,dict):raise ProtocolError('NATIVE_FACT_REJECTED','typed gift inclusion required')
                    if fact.get('phase')=='on-chain':
                        if (fact.get('transaction')!=tx or fact.get('transaction_hash')!=tx_hash or
                                not isinstance(fact.get('inclusion'),dict) or fact['inclusion'].get('assurance')!='native-signed-inclusion'):
                            raise ProtocolError('NATIVE_FACT_REJECTED','included gift differs from queued signed bytes')
                        phase='confirmed' if type(fact.get('confirmations')) is int and fact['confirmations']>=confirmations else 'waiting'
                    elif fact.get('phase')=='pending-native-consensus':
                        if fact.get('transaction')!=tx: raise ProtocolError('NATIVE_FACT_REJECTED','pending gift differs')
                        phase='waiting'
                    elif fact.get('phase')=='absent':
                        op=operation_id
                        plan=owned_call('operation.prepare',{'operation_id':op,'action':'zkn.gift','resource':'zkn:'+tx['data']['token_id'],
                                  'arguments':{'transaction':tx},'expected_revision':None},route)
                        owned_call('operation.commit',{'operation_id':op,'plan_digest':plan['plan_digest']},route)
                        phase='waiting'
                    else: raise ProtocolError('NATIVE_FACT_REJECTED','unknown gift inclusion phase')
                except (OSError,ProtocolError) as exc:
                    if isinstance(exc,ProtocolError) and exc.code in {'GIFT_CONFLICT','RECIPIENT_REUSED','POLICY_DENIED'}: phase='conflict'
                    failed=getattr(choose_route,'failed',None)
                    if failed is not None and route is not None and not (isinstance(exc,ProtocolError) and exc.code=='OUTBOX_LEASE_LOST'): failed(route)
                with self.db:
                    self.db.execute('UPDATE gifts SET phase=?,attempts=?,next_try=?,lease_token=NULL,lease_until=0 WHERE id=? AND lease_token=?',(phase,min(attempts+1,2**31-1),int(time.time())+(45+secrets.randbelow(46) if phase=='confirmed' else secrets.randbelow(max(2,min(300,2**min(attempts+1,8))))+1),tx_hash,lease))
        return self.status()


def validate_edition(network,token,kind,serial,contents_digest):
    identifier(network,'network')
    if (not isinstance(token,str) or not HEX.fullmatch(token) or not isinstance(kind,str) or kind not in {'repeat','unique'} or
            not isinstance(serial,str) or not re.fullmatch('0|[1-9][0-9]{0,127}',serial) or
            kind=='repeat' and serial!='0' or kind=='unique' and serial=='0' or
            not isinstance(contents_digest,str) or not re.fullmatch('sha256:[a-f0-9]{64}',contents_digest)):
        raise ProtocolError('INVALID_ZKC','typed collectible edition and exact content digest required')


def issue_edition(network, token, kind, serial, contents_digest, owner_private):
    """Repeat uses serial 0; unique editions use distinct decimal serials."""
    validate_edition(network,token,kind,serial,contents_digest)
    key=_key(owner_private)
    tx={'type':'zkc_issue','data':{'network_id':network,'token_id':token,'kind':kind,'serial':serial,'contents_digest':contents_digest},
        'timestamp':int(time.time()),'public_key':public_pem(key)}
    tx['signature']=_runtime.native_ec_sign(key,_runtime.asset_transaction_bytes(tx))
    _runtime.asset_signed_gift(tx,network,'zkc_issue')
    return tx


def pack_editions(transactions, network, owner_private, recipient_offer, *, extension=None):
    """Seal an integrity-bound collection; receiver verifies each issue on chain."""
    if not isinstance(transactions,list) or not 1<=len(transactions)<=64: raise ProtocolError('INVALID_ZKC','one to 64 edition references per pack')
    recipient=verify_receiver(recipient_offer,network);seen=set()
    for tx in transactions:
        _runtime.asset_signed_gift(tx,network,'zkc_issue')
        # Validate syntax independently of an untrusted packet's issue claims.
        p=tx['data']
        if set(p)!={'network_id','token_id','kind','serial','contents_digest'}:raise ProtocolError('INVALID_ZKC','exact edition payload required')
        validate_edition(network,p.get('token_id'),p.get('kind'),p.get('serial'),p.get('contents_digest'))
        eid=_runtime.zkc_edition_id(p)
        if eid in seen: raise ProtocolError('EDITION_CONFLICT','pack repeats an edition reference')
        seen.add(eid)
    value={'schema':'ziokt.zkc-pack.v1','network_id':network,'editions':transactions,'nonce':secrets.token_hex(16)}
    key=_key(owner_private)
    envelope={'payload':value,'public_key':public_pem(key),'signature':_runtime.native_ec_sign(key,b'Ziokt/ZKC/pack/v1\n'+encoded(value))}
    raw=encoded(envelope)
    if extension is not None: extension({'schema':'ziokt.extension-event.v1','kind':'zkc-pack','network_id':network,
        'content_digest':'sha256:'+hashlib.sha256(raw).hexdigest(),'hops':2,'private':True,'free_forwarding':True})
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey,X25519PublicKey
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    ephemeral=X25519PrivateKey.generate()
    secret=HKDF(hashes.SHA256(),32,None,b'Ziokt/ZKC/pack/v1/'+recipient.encode()).derive(ephemeral.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(recipient_offer['mailbox']))))
    size=max(16384,1<<(len(raw)+64-1).bit_length())
    if size>1024*1024: raise ProtocolError('RESPONSE_LIMIT','edition pack exceeds sealed budget')
    nonce=secrets.token_bytes(12)
    public=ephemeral.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    plain=len(raw).to_bytes(4,'big')+raw+secrets.token_bytes(size-64-len(raw))
    return public+nonce+AESGCM(secret).encrypt(nonce,plain,recipient.encode())


def unpack_editions(blob, wallet, *, publisher, query=None, confirmations=2):
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey,X25519PublicKey
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    from cryptography.exceptions import InvalidTag
    if not isinstance(blob,bytes) or not 16384<=len(blob)<=1024*1024 or len(blob)&(len(blob)-1): raise ProtocolError('INVALID_ZKC','padded sealed edition pack required')
    recipient=hashlib.sha256(wallet['offer']['public_key'].encode()).hexdigest()
    try:
        secret=HKDF(hashes.SHA256(),32,None,b'Ziokt/ZKC/pack/v1/'+recipient.encode()).derive(X25519PrivateKey.from_private_bytes(bytes.fromhex(wallet['mailbox_private'])).exchange(X25519PublicKey.from_public_bytes(blob[:32])))
        plain=AESGCM(secret).decrypt(blob[32:44],blob[44:],recipient.encode());size=int.from_bytes(plain[:4],'big')
        if not 1<=size<=len(plain)-4: raise ValueError()
        envelope=strict_json(plain[4:4+size],1024*1024)
    except (ValueError,TypeError,InvalidTag): raise ProtocolError('PACK_AUTH_FAILED','edition pack authentication rejected')
    if not isinstance(envelope,dict) or set(envelope)!={'payload','public_key','signature'} or envelope['public_key']!=publisher: raise ProtocolError('SIGNATURE_REJECTED','edition pack publisher differs')
    value=envelope['payload']
    if (not isinstance(value,dict) or set(value)!={'schema','network_id','editions','nonce'} or value['schema']!='ziokt.zkc-pack.v1' or
            value['network_id']!=wallet['offer']['network_id'] or not isinstance(value['editions'],list) or not 1<=len(value['editions'])<=64 or
            not isinstance(value['nonce'],str) or not re.fullmatch('[a-f0-9]{32}',value['nonce'])): raise ProtocolError('INVALID_ZKC','edition pack schema or network differs')
    _runtime.native_ec_verify(publisher,envelope['signature'],b'Ziokt/ZKC/pack/v1\n'+encoded(value))
    if type(confirmations) is not int or not 1<=confirmations<=128: raise ProtocolError('INVALID_ZKC','bounded confirmation policy required')
    seen=set();result=[]
    for tx in value['editions']:
        _,tx_hash,_=_runtime.asset_signed_gift(tx,value['network_id'],'zkc_issue')
        p=tx['data']
        if set(p)!={'network_id','token_id','kind','serial','contents_digest'}:raise ProtocolError('INVALID_ZKC','exact edition payload required')
        validate_edition(value['network_id'],p.get('token_id'),p.get('kind'),p.get('serial'),p.get('contents_digest'))
        eid=_runtime.zkc_edition_id(p)
        if eid in seen: raise ProtocolError('EDITION_CONFLICT','duplicate edition in pack')
        seen.add(eid)
        if query is not None:
            fact=query('zkc.fact',{'transaction_hash':tx_hash})
            if (not isinstance(fact,dict) or fact.get('phase')!='on-chain' or fact.get('transaction_hash')!=tx_hash or fact.get('transaction')!=tx or
                    type(fact.get('confirmations')) is not int or fact['confirmations']<confirmations or
                    not isinstance(fact.get('inclusion'),dict) or fact['inclusion'].get('assurance')!='native-signed-inclusion'):
                raise ProtocolError('EDITION_PENDING','edition needs fresh canonical inclusion')
        result.append({'edition_id':eid,**tx['data'],'transaction_hash':tx_hash})
    return {'schema':'ziokt.zkc-unpacked.v1','editions':result,'ledger_confirmed':query is not None,'fee_required':False}


class GiftRoutes:
    """Select another admitted multihop path after failure, never direct fallback."""
    def __init__(self,endpoint):
        from .routes import validate_route
        self.endpoint=endpoint;self.directory=None;self.config=None;self.last=None;self.excluded=set();self.excluded_until=0
        policy=validate_route(endpoint.get('connection_policy'),endpoint)
        if policy['mode']=='discovered-peers':
            from .peer_directory import load_directory,DiscoveryWorker
            self.directory,self.config=load_directory(endpoint['discovery'])
            if 'signing_key' in self.config:
                if self.directory.worker is None:self.directory.worker=DiscoveryWorker(self.directory,self.config)
                self.directory.worker.start()
        elif policy['mode']=='peer-multihop':
            self.candidates=[endpoint]
        elif policy['mode']=='approved-paths':
            from .routes import _candidate_endpoint
            self.candidates=[_candidate_endpoint(endpoint,c) for c in endpoint['candidates']]
        else: raise ProtocolError('NO_POLICY_COMPLIANT_PATH','private gifts require two to four keyless proxy hops')
        if self.directory is None:
            for candidate in self.candidates:
                self._admit(candidate.get('carrier'))

    @staticmethod
    def _admit(carrier):
        if not isinstance(carrier,dict) or carrier.get('kind')!='peer-multihop':raise ProtocolError('NO_POLICY_COMPLIANT_PATH','private gift direct fallback denied')
        from .peer_proxy import validate_peer_carrier
        validate_peer_carrier(carrier,'127.0.0.1')

    def __call__(self,tx_hash,attempts):
        if self.excluded and time.time()>=self.excluded_until:self.excluded.clear()
        if self.directory is None:
            # Uniform initial route spread; subsequent attempts cycle approved paths.
            result=secrets.choice([candidate for candidate in self.candidates if candidate is not self.last] or self.candidates)
        else:
            carrier=self.directory.build_route(self.config['hop_count'],self.config['client_tls'],(self.endpoint['host'],self.endpoint['port']),exclude=self.excluded,randomize=True)
            result={**self.endpoint,'carrier':carrier,'connection_policy':{'mode':'peer-multihop','allow_direct_fallback':False}}
        self._admit(result.get('carrier'));self.last=result;return result

    def failed(self,route):
        # Blame is not cryptographic evidence of misconduct: route exclusion is
        # temporary local scheduling, never a membership or reputation penalty.
        if self.directory is not None:
            addresses={(h['host'],h['port']) for h in route['carrier']['hops']}
            self.excluded_until=time.time()+30
            self.excluded={p['public_key'] for p in self.directory.peers() if (p['endpoint']['host'],p['endpoint']['port']) in addresses}

    def recovered(self): self.excluded.clear()


class GiftRPC:
    def __init__(self,federation,provider,context,signing_key,*,cancellation=None,delivery_version=2):
        if type(delivery_version) is not int or delivery_version not in {1,2}:raise ProtocolError('INVALID_ZKN','explicit supported collectible delivery version required')
        self.delivery_version=delivery_version
        identifier(federation,'federation');identifier(provider,'provider')
        self.federation,self.provider,self.context,self.signing_key=federation,provider,context,signing_key
        self.cancellation=cancellation

    def __call__(self,method,params,endpoint):
        from .remote import request_remote,resource_for
        from .security import grant
        GiftRoutes._admit(endpoint.get('carrier'))
        request={'provider_id':self.provider,'method':method,'params':params}
        delivery_id=secrets.token_hex(32) if self.delivery_version==2 else None
        digest=delivery_digest(request,delivery_id) if delivery_id else 'sha256:'+hashlib.sha256(encoded(request)).hexdigest()
        return request_remote(endpoint['host'],endpoint['port'],self.context,request,
            lambda:grant(self.signing_key,audience=self.provider,action=method,resource=resource_for(method,params),
                         federation=self.federation,request_digest=digest),
            carrier=endpoint['carrier'],cancellation=self.cancellation,privacy_padding=True,delivery_id=delivery_id)

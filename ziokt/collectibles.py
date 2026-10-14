"""Private collectible gifts: fresh receivers, sealed receipts and durable retry.

Transport relays have no collectible keys. The native ledger still exposes
collectible references and one-time ownership transitions; this is not a proof
of untraceability against colluding relays or a global traffic observer.
"""
import base64
import hashlib
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
            offer['network_id'] != network or not isinstance(offer['mailbox'], str) or not HEX.fullmatch(offer['mailbox']) or
            not isinstance(offer['nonce'], str) or not re.fullmatch('[a-f0-9]{32}', offer['nonce']) or
            type(offer['expires']) is not int or not int(time.time()) < offer['expires'] <= int(time.time())+86400):
        raise ProtocolError('INVALID_ZKN', 'fresh scoped one-time receiver required')
    _runtime.native_ec_verify(offer['public_key'], offer['signature'], b'Ziokt/ZKN/receiver/v1\n'+encoded({k:v for k,v in offer.items() if k!='signature'}))
    return hashlib.sha256(offer['public_key'].encode()).hexdigest()


def verify_snapshot(snapshot, network):
    if not isinstance(snapshot,dict) or set(snapshot)!={'manifest','public_key','signature'}: raise ProtocolError('INVALID_ZKN','signed collectible snapshot required')
    value=snapshot['manifest']
    fields={'schema','network_id','token_id','block_hash','height','packer','packed_at','contents_digest','contents_size','zkt_score'}
    if not isinstance(value,dict) or value.get('schema') not in {'ziokt.zkn-snapshot.v1','ziokt.zkn-snapshot.v2'}:
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


class GiftOutbox:
    """Encrypted durable signed bytes, bounded work, idempotent chain reconciliation."""
    def __init__(self,path,key):
        path=Path(path)
        if not isinstance(key,bytes) or len(key)!=32: raise ProtocolError('INVALID_ZKN','private 32-byte outbox key required')
        if path.is_symlink(): raise ProtocolError('UNSAFE_FILE','outbox cannot be a symlink')
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if path.exists(): secure_read(path,32*1024*1024)
        self.key=key;self.lock=threading.RLock()
        self.db=sqlite3.connect(path,timeout=5,check_same_thread=False);make_private(path)
        self.db.execute('PRAGMA synchronous=FULL');self.db.execute('PRAGMA secure_delete=ON')
        self.db.execute('CREATE TABLE IF NOT EXISTS gifts(id TEXT PRIMARY KEY,body BLOB,phase TEXT,attempts INTEGER,next_try INTEGER)');self.db.commit()

    def close(self): self.db.close()

    def enqueue(self,tx):
        _,tx_hash,_=_runtime.asset_signed_gift(tx,tx['data']['network_id'])
        with self.lock,self.db:
            old=self.db.execute('SELECT body FROM gifts WHERE id=?',(tx_hash,)).fetchone()
            if old:
                if self._open(tx_hash,old[0])!=tx: raise ProtocolError('IDEMPOTENCY_CONFLICT','queued gift changed')
                return tx_hash
            if self.db.execute('SELECT COUNT(*) FROM gifts').fetchone()[0]>=4096: raise ProtocolError('BACKPRESSURE','collectible outbox requires archival')
            nonce=secrets.token_bytes(12);body=nonce+AESGCM(self.key).encrypt(nonce,encoded(tx),tx_hash.encode())
            self.db.execute('INSERT INTO gifts VALUES (?,?,\'queued\',0,0)',(tx_hash,body))
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
            rows=self.db.execute("SELECT id,body,attempts FROM gifts WHERE phase!='conflict' AND next_try<=? ORDER BY next_try,id LIMIT ?",(int(time.time()),maximum)).fetchall()
            for tx_hash,body,attempts in rows:
                if cancellation is not None and cancellation.is_set(): break
                tx=self._open(tx_hash,body);phase='queued';route=None
                try:
                    route=choose_route(tx_hash,attempts)
                    # Even a confirmed row is rechecked, so a branch rollback
                    # returns it to waiting rather than silently losing custody.
                    fact=call('zkn.fact',{'transaction_hash':tx_hash},route)
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
                        op='gift-'+tx_hash[:40]+'-'+str(attempts)
                        plan=call('operation.prepare',{'operation_id':op,'action':'zkn.gift','resource':'zkn:'+tx['data']['token_id'],
                                  'arguments':{'transaction':tx},'expected_revision':None},route)
                        call('operation.commit',{'operation_id':op,'plan_digest':plan['plan_digest']},route)
                        phase='waiting'
                    else: raise ProtocolError('NATIVE_FACT_REJECTED','unknown gift inclusion phase')
                except (OSError,ProtocolError) as exc:
                    if isinstance(exc,ProtocolError) and exc.code in {'GIFT_CONFLICT','RECIPIENT_REUSED','POLICY_DENIED'}: phase='conflict'
                    failed=getattr(choose_route,'failed',None)
                    if failed is not None and route is not None: failed(route)
                with self.db:
                    self.db.execute('UPDATE gifts SET phase=?,attempts=?,next_try=? WHERE id=?',(phase,min(attempts+1,2**31-1),int(time.time())+(60 if phase=='confirmed' else min(300,2**min(attempts+1,8))+secrets.randbelow(4)),tx_hash))
        return self.status()


def validate_edition(network,token,kind,serial,contents_digest):
    identifier(network,'network')
    if (not isinstance(token,str) or not HEX.fullmatch(token) or kind not in {'repeat','unique'} or
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
            if (fact.get('phase')!='on-chain' or fact.get('transaction_hash')!=tx_hash or fact.get('transaction')!=tx or
                    type(fact.get('confirmations')) is not int or fact['confirmations']<confirmations or
                    fact.get('inclusion',{}).get('assurance')!='native-signed-inclusion'):
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
            result=self.candidates[(int(tx_hash[:8],16)+attempts)%len(self.candidates)]
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
    def __init__(self,federation,provider,context,signing_key,*,cancellation=None):
        identifier(federation,'federation');identifier(provider,'provider')
        self.federation,self.provider,self.context,self.signing_key=federation,provider,context,signing_key
        self.cancellation=cancellation

    def __call__(self,method,params,endpoint):
        from .remote import request_remote,resource_for
        from .security import grant
        request={'provider_id':self.provider,'method':method,'params':params}
        return request_remote(endpoint['host'],endpoint['port'],self.context,request,
            lambda:grant(self.signing_key,audience=self.provider,action=method,resource=resource_for(method,params),
                         federation=self.federation,request_digest='sha256:'+hashlib.sha256(encoded(request)).hexdigest()),
            carrier=endpoint['carrier'],cancellation=self.cancellation,privacy_padding=True)

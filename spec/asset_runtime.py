"""Native signed registration receipts and transferable block-snapshot ZKN assets."""

ASSET_TYPES = {'ziokt_identity_register', 'ziokt_content', 'zkn_mint', 'zkn_transfer', 'zkn_private_transfer', 'zkc_issue'} | ZS_TYPES


def asset_tables(db):
    # Typed dynamic DDL remains represented in Corium's custom-schema recovery.
    definitions = {
        'ziokt_registrations': 'network TEXT,member TEXT,commitment TEXT,policy TEXT,issuer TEXT,transaction_hash TEXT,height INTEGER,PRIMARY KEY(network,member,policy)',
        'zkn_tokens': 'token_id TEXT PRIMARY KEY,block_hash TEXT UNIQUE,owner TEXT,nonce INTEGER,manifest TEXT,mint_transaction TEXT,height INTEGER',
        'zkn_receivers': 'address TEXT PRIMARY KEY,transaction_hash TEXT UNIQUE,height INTEGER',
    }
    definitions['zkc_editions']='edition_id TEXT PRIMARY KEY,token_id TEXT,kind TEXT,serial TEXT,contents_digest TEXT,issuer TEXT,transaction_hash TEXT,height INTEGER'
    for table, fields in definitions.items(): db.execute('CREATE TABLE IF NOT EXISTS "'+table+'" ('+fields+')')


def asset_token_id(network, block_hash):
    return hashlib.sha256(('Ziokt/ZKN/v1\n'+network+'\n'+block_hash).encode()).hexdigest()


def asset_transaction_bytes(tx):
    # Recovery networks bind native wallet signatures to chain namespace and actor.
    network=tx['data'].get('network_id')
    if network in {'ziokt-main-recovery-20261024','ziokt-dna-side-20261024'}:
        return encoded({'schema':'corium.chain-transaction.v3','network':network,'public_key':tx['public_key'],
                        'type':tx['type'],'data':tx['data'],'timestamp':tx['timestamp']})
    # Match Corium's historical signed serialization exactly.
    return ('{"type":'+json.dumps(tx['type'])+',"data":'+encoded(tx['data']).decode()+',"timestamp":'+str(tx['timestamp'])+'}').encode()


def zkc_edition_id(payload):
    return hashlib.sha256(b'Ziokt/ZKC/edition/v1\n'+encoded({k:payload[k] for k in ('network_id','token_id','kind','serial')})).hexdigest()


def asset_signed_gift(tx, network, kind='zkn_private_transfer'):
    if (not isinstance(tx,dict) or set(tx)!={'type','data','timestamp','public_key','signature'} or
            kind not in ({'zkn_transfer','zkn_private_transfer','zkc_issue'}|ZS_TYPES) or tx['type']!=kind or type(tx['timestamp']) is not int or not 0<tx['timestamp']<2**53 or
            not isinstance(tx['data'],dict) or (kind != 'zkn_transfer' and tx['data'].get('network_id')!=network) or
            not isinstance(tx['public_key'],str) or len(tx['public_key'])>1024 or
            not isinstance(tx['signature'],str) or len(tx['signature'])>160):
        fail('INVALID_ZKN','scoped signed private gift transaction required')
    raw=asset_transaction_bytes(tx)
    if len(raw)>(65536 if kind in ZS_TYPES else 8192): fail('RESPONSE_LIMIT','gift transaction exceeds budget')
    native_ec_verify(tx['public_key'],tx['signature'],raw)
    return tx,hashlib.sha256(raw).hexdigest(),hashlib.sha256(tx['public_key'].rstrip('\n').encode()).hexdigest()


def asset_publish_transaction(root, network, tx, tx_hash):
    directory=root/'var/lib/corix/p2p/objects/transactions'
    private_mkdir(directory)
    target=directory/tx_hash;body=encoded(tx)
    if target.exists():
        if strict_json(secure_read(target,65536))!=tx: fail('IDEMPOTENCY_CONFLICT','immutable P2P gift object changed')
    else:
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        make_private(target)
        with os.fdopen(fd,'wb') as stream: stream.write(body);stream.flush();os.fsync(stream.fileno())
    with closing(asset_writable_database(root/'var/lib/corix/p2p/dht.db')) as dht,dht:
        dht.execute('INSERT OR REPLACE INTO local_chunks VALUES (?,?,0,?)',(tx_hash,str(target),len(body)))
    return target


def asset_writable_database(path):
    check=native_database(path);check.close()
    return sqlite3.connect(Path(path).absolute().as_uri()+'?mode=rw',uri=True,timeout=5)


def asset_privacy_pending(db, network, kind, value, sender):
    """Reserve privacy conflicts under the caller's BEGIN IMMEDIATE lock.

    Admission policy only: consensus validation must not depend on local mempool
    contents, whose order and membership differ between validators.
    """
    own_requests = global_requests = 0
    ownership = {'zkn_shield_deposit', 'zkn_transfer', 'zkn_private_transfer'}
    kinds = sorted(ZS_TYPES | {'zkn_transfer', 'zkn_private_transfer', 'zkc_issue'})
    rows = db.execute('SELECT type,data,public_key FROM transactions WHERE block_height IS NULL AND type IN (' + ','.join('?' for _ in kinds) + ') LIMIT 4097', kinds)
    for pending_kind, raw, public in rows:
        pending = strict_json(raw.encode())
        if type(pending) is not dict: fail('PRIVACY_CONFLICT', 'pending privacy payload requires native recovery')
        if pending_kind in {'zkn_shield_transfer', 'zkn_shield_withdraw'} and type(pending.get('proof')) is not dict:
            fail('PRIVACY_CONFLICT', 'pending privacy proof requires native recovery')
        if pending_kind in {'zkn_shield_deposit', 'zkn_shield_transfer'} and type(pending.get('note')) is not dict:
            fail('PRIVACY_CONFLICT', 'pending privacy note requires native recovery')
        same_sender = hashlib.sha256(public.rstrip('\n').encode()).hexdigest() == sender
        if kind in ownership | {'zkc_issue'} and pending_kind in ownership | {'zkc_issue'} and (kind in ownership or pending_kind in ownership) and pending.get('token_id') == value['token_id']:
            fail('PRIVACY_CONFLICT', 'asset already has a pending ownership change')
        if kind in {'zkn_shield_transfer', 'zkn_shield_withdraw'} and pending_kind in {'zkn_shield_transfer', 'zkn_shield_withdraw'} and pending.get('proof', {}).get('image') == value['proof']['image']:
            fail('PRIVACY_CONFLICT', 'nullifier already pending')
        if kind in {'zkn_shield_deposit', 'zkn_shield_transfer'} and pending_kind in {'zkn_shield_deposit', 'zkn_shield_transfer'}:
            note = pending.get('note', {})
            if any(note.get(field) == value['note'][field] for field in ('public_key', 'commitment')):
                fail('PRIVACY_CONFLICT', 'one-time note key or commitment already pending')
        if pending_kind == 'privacy_review_request':
            global_requests += 1
            own_requests += int(same_sender)
            if kind == 'privacy_review_request' and same_sender and pending.get('nonce') == value['nonce']:
                fail('PRIVACY_CONFLICT', 'request nonce already pending')
        if value.get('request_id') and value.get('request_id') == pending.get('request_id'):
            if kind == 'privacy_review_revoke' or pending_kind == 'privacy_review_revoke':
                fail('PRIVACY_CONFLICT', 'review closure conflicts with a pending review action')
            if kind == pending_kind == 'privacy_review_vote' and same_sender:
                fail('PRIVACY_CONFLICT', 'review vote already pending')
            if kind == pending_kind == 'privacy_review_disclose' and value['note_id'] == pending.get('note_id'):
                fail('PRIVACY_CONFLICT', 'disclosure already pending')
    if kind == 'privacy_review_request':
        height = zs_height(db)
        own_confirmed = global_confirmed = 0
        if zs_exists(db, 'privacy_requests'):
            own_confirmed = db.execute('SELECT COUNT(*) FROM privacy_requests WHERE requester=? AND expires>=? AND revoked=0', (sender, height)).fetchone()[0]
            global_confirmed = db.execute('SELECT COUNT(*) FROM privacy_requests WHERE expires>=? AND revoked=0', (height,)).fetchone()[0]
        if own_confirmed + own_requests >= 8 or global_confirmed + global_requests >= 4096:
            fail('PRIVACY_CONFLICT', 'confirmed and pending review request quota')


def asset_submit_gift(root, network, tx, kind='zkn_private_transfer'):
    tx,tx_hash,sender=asset_signed_gift(tx,network,kind)
    with closing(asset_writable_database(root/'var/lib/corix/networks'/network/'blockchain/chain.db')) as db:
        try:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT type,data,signature,public_key,timestamp FROM transactions WHERE hash=?',(tx_hash,)).fetchone()
            expected=(tx['type'],encoded(tx['data']).decode(),tx['signature'],tx['public_key'],tx['timestamp'])
            if old:
                if tuple(old)!=expected: fail('IDEMPOTENCY_CONFLICT','gift transaction bytes changed')
            else:
                if db.execute('SELECT COUNT(*) FROM transactions WHERE block_height IS NULL').fetchone()[0]>=4096:
                    fail('BACKPRESSURE','pending transaction budget exhausted')
                asset_validate(db,network,tx['type'],tx['data'],sender)
                if kind in ZS_TYPES or kind in {'zkn_transfer', 'zkn_private_transfer', 'zkc_issue'}:
                    asset_privacy_pending(db, network, kind, tx['data'], sender)
                for (raw,) in db.execute("SELECT data FROM transactions WHERE type IN ('zkn_transfer','zkn_private_transfer','zkc_issue') AND block_height IS NULL LIMIT 4097"):
                    pending=strict_json(raw.encode())
                    if kind=='zkn_private_transfer' and 'nonce' in pending and pending.get('token_id')==tx['data']['token_id'] and pending.get('nonce')==tx['data']['nonce']:
                        fail('GIFT_CONFLICT','another gift already spends this collectible sequence')
                    if kind=='zkn_private_transfer' and pending.get('recipient')==tx['data']['recipient']:
                        fail('RECIPIENT_REUSED','one-time receiver already has a pending gift')
                    if kind=='zkc_issue' and 'kind' in pending and zkc_edition_id(pending)==zkc_edition_id(tx['data']):
                        fail('EDITION_PENDING','edition already has a pending issue; reuse its transaction')
                db.execute('INSERT INTO transactions (hash,type,data,signature,public_key,timestamp,block_height) VALUES (?,?,?,?,?,?,NULL)',(tx_hash,*expected))
            db.commit()
        except BaseException: db.rollback();raise
    # If registration is interrupted after the transaction commit, submitting
    # these same bytes again safely repairs publication without a second gift.
    asset_publish_transaction(root,network,tx,tx_hash)
    return {'transaction_hash':tx_hash,'phase':'pending-native-consensus','fee_required':False}


def asset_forward_pending(root, network):
    """Every packer republishes bounded signed collectible objects at no fee."""
    with closing(corium_db(root,network,'blockchain/chain.db')) as db:
        rows=db.execute("SELECT hash,type,data,signature,public_key,timestamp FROM transactions WHERE type IN ('zkn_private_transfer','zkc_issue','zkn_shield_deposit','zkn_shield_transfer','zkn_shield_withdraw','privacy_review_request','privacy_review_vote','privacy_review_revoke','privacy_review_disclose') ORDER BY timestamp DESC LIMIT 64").fetchall()
    for tx_hash,kind,data,signature,public,stamp in rows:
        tx={'type':kind,'data':strict_json(data.encode()),'signature':signature,'public_key':public,'timestamp':stamp}
        _,checked,_=asset_signed_gift(tx,network,kind)
        if checked!=tx_hash: fail('NATIVE_FACT_REJECTED','forwarding object digest changed')
        asset_publish_transaction(root,network,tx,tx_hash)
    return len(rows)


def asset_manifest(envelope, network, db):
    if not isinstance(envelope, dict) or set(envelope) != {'manifest','public_key','signature'}:
        fail('INVALID_ZKN', 'exact native ZKN signature required')
    value = envelope['manifest']
    fields = {'schema','network_id','token_id','block_hash','height','packer','packed_at','contents_digest','contents_size','zkt_score'}
    if not isinstance(value, dict) or value.get('schema') not in {'ziokt.zkn-snapshot.v1','ziokt.zkn-snapshot.v2'}:
        fail('INVALID_ZKN', 'versioned native collectible required')
    if value['schema'] == 'ziokt.zkn-snapshot.v2':
        fields |= {'lucky_digit','relay_obligation'}
        if (not isinstance(value.get('lucky_digit'),str) or not re.fullmatch('[0-9A-F]',value['lucky_digit']) or
                value.get('relay_obligation') != 'free-p2p-forwarding-v1'):
            fail('INVALID_ZKN','immutable hexadecimal collectible digit and forwarding obligation required')
    if set(value) != fields or value['network_id'] != network:
        fail('INVALID_ZKN', 'scoped ZKN snapshot manifest required')
    if any(not isinstance(value[k], str) or not re.fullmatch('[a-f0-9]{64}', value[k]) for k in ('token_id','block_hash','packer')):
        fail('INVALID_ZKN', 'native ZKN identities must be exact digests')
    if value['token_id'] != asset_token_id(network,value['block_hash']) or not re.fullmatch('sha256:[a-f0-9]{64}', str(value['contents_digest'])):
        fail('INVALID_ZKN', 'ZKN token or content identity changed')
    if (any(type(value[k]) is not int or value[k] < 0 for k in ('height','packed_at','contents_size','zkt_score')) or
            value['contents_size'] > 64*1024*1024 or value['zkt_score'] >= 2**53):
        fail('INVALID_ZKN', 'bounded native ZKN snapshot fields required')
    block = db.execute('SELECT height,validator,timestamp FROM blocks WHERE hash=?', (value['block_hash'],)).fetchone()
    if not block or tuple(block) != (value['height'],value['packer'],value['packed_at']):
        fail('INVALID_ZKN', 'snapshot does not match its packed block')
    if hashlib.sha256(envelope['public_key'].rstrip('\n').encode()).hexdigest() != value['packer']:
        fail('INVALID_ZKN', 'snapshot signer is not its packer')
    domain = b'Ziokt/ZKN/snapshot/v2\n' if value['schema'].endswith('.v2') else b'Ziokt/ZKN/snapshot/v1\n'
    native_ec_verify(envelope['public_key'],envelope['signature'],domain+encoded(value))
    return value


def asset_validate(db, network, tx_type, payload, sender):
    if tx_type in ZS_TYPES:
        try:return zs_validate(db,network,tx_type,payload,sender)
        except (ValueError,TypeError,KeyError) as exc:fail('PRIVACY_REJECTED',str(exc))
    if tx_type=='zkc_issue':
        fields={'network_id','token_id','kind','serial','contents_digest'}
        if (not isinstance(payload,dict) or set(payload)!=fields or payload['network_id']!=network or
                not isinstance(payload['token_id'],str) or not re.fullmatch('[a-f0-9]{64}',payload['token_id']) or
                not isinstance(payload['kind'],str) or payload['kind'] not in {'repeat','unique'} or not isinstance(payload['serial'],str) or
                not re.fullmatch('0|[1-9][0-9]{0,127}',payload['serial']) or
                payload['kind']=='repeat' and payload['serial']!='0' or payload['kind']=='unique' and payload['serial']=='0' or
                not isinstance(payload['contents_digest'],str) or not re.fullmatch('sha256:[a-f0-9]{64}',payload['contents_digest'])):
            fail('INVALID_ZKC','exact collectible edition without payment fields required')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='zkn_tokens'").fetchone(): fail('NATIVE_STATE_UNAVAILABLE','parent collectible must be included')
        owner=db.execute('SELECT owner FROM zkn_tokens WHERE token_id=?',(payload['token_id'],)).fetchone()
        if not owner or owner[0]!=sender: fail('POLICY_DENIED','only current parent collectible holder may issue editions')
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='zkc_editions'").fetchone():
            prior=db.execute('SELECT contents_digest FROM zkc_editions WHERE edition_id=?',(zkc_edition_id(payload),)).fetchone()
            if prior and (payload['kind']=='unique' or prior[0]!=payload['contents_digest']): fail('EDITION_CONFLICT','edition serial or repeat content already assigned')
        return payload
    if tx_type=='ziokt_content':
        if not isinstance(payload,dict) or set(payload)!={'text','data_base64','content_type'} or any(not isinstance(v,str) for v in payload.values()) or len(payload['text'].encode())>8192 or not re.fullmatch('[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+',payload['content_type']):
            fail('INVALID_CONTENT','bounded text and binary content required')
        try: data=base64.b64decode(payload['data_base64'],validate=True)
        except (ValueError,TypeError): fail('INVALID_CONTENT','binary encoding rejected')
        if len(data)>4096: fail('RESPONSE_LIMIT','binary ledger payload exceeds budget')
        return payload
    if tx_type == 'ziokt_identity_register':
        fields = {'schema','network_id','federation_id','member_public','document_commitment','policy_digest'}
        if not isinstance(payload,dict) or set(payload)!=fields or payload['schema']!='ziokt.identity-registration.v1' or payload['network_id']!=network:
            fail('INVALID_REGISTRATION','scoped registration commitment required')
        identifier(payload['federation_id'],'federation_id')
        if (not re.fullmatch('[a-f0-9]{64}',str(payload['member_public'])) or
                any(not re.fullmatch('sha256:[a-f0-9]{64}',str(payload[k])) for k in ('document_commitment','policy_digest'))):
            fail('INVALID_REGISTRATION','exact member and registration commitments required')
        return payload
    if tx_type == 'zkn_mint':
        if not isinstance(payload,dict) or set(payload)!={'snapshot'}: fail('INVALID_ZKN','signed snapshot mint required')
        value=asset_manifest(payload['snapshot'],network,db)
        if value['packer']!=sender: fail('POLICY_DENIED','only block packer can issue its ZKN snapshot')
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='zkn_tokens'").fetchone():
            if db.execute('SELECT 1 FROM zkn_tokens WHERE token_id=?',(value['token_id'],)).fetchone():
                fail('IDEMPOTENCY_CONFLICT','block snapshot NFT already minted')
        return value
    if tx_type in {'zkn_transfer','zkn_private_transfer'}:
        fields = {'token_id','recipient','nonce'}
        if tx_type == 'zkn_private_transfer': fields |= {'network_id','receipt'}
        if network in {'ziokt-main-recovery-20261024','ziokt-dna-side-20261024'}: fields.add('network_id')
        if not isinstance(payload,dict) or set(payload)!=fields:
            fail('INVALID_ZKN','exact native NFT transfer required')
        if tx_type == 'zkn_private_transfer':
            if payload['network_id'] != network: fail('SCOPE_MISMATCH','gift belongs to another network')
            try:
                receipt=base64.b64decode(payload['receipt'],validate=True)
                if len(receipt)!=2048: raise ValueError()
            except (ValueError,TypeError): fail('INVALID_ZKN','fixed sealed collectible receipt required')
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='zkn_receivers'").fetchone() and db.execute('SELECT 1 FROM zkn_receivers WHERE address=?',(payload['recipient'],)).fetchone():
                fail('RECIPIENT_REUSED','private gift requires a fresh one-time receiver')
        if (not re.fullmatch('[a-f0-9]{64}',str(payload['token_id'])) or not re.fullmatch('[a-f0-9]{64}',str(payload['recipient'])) or
                type(payload['nonce']) is not int or not 1 <= payload['nonce'] < 2**53):
            fail('INVALID_ZKN','bounded NFT recipient and transfer nonce required')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='zkn_tokens'").fetchone():
            fail('NATIVE_STATE_UNAVAILABLE','NFT mint has not been confirmed')
        row=db.execute('SELECT owner,nonce FROM zkn_tokens WHERE token_id=?',(payload['token_id'],)).fetchone()
        if not row or row[0]!=sender or payload['nonce']!=row[1]+1:
            fail('POLICY_DENIED','current NFT owner and next transfer nonce required')
        return payload
    fail('INVALID_PARAMS','unsupported native asset transaction')


def asset_apply(db, network, tx_hash, tx_type, payload, sender, height):
    if tx_type in ZS_TYPES:
        try:return zs_apply(db,network,tx_type,payload,sender,tx_hash,height)
        except (ValueError,TypeError,KeyError) as exc:fail('PRIVACY_REJECTED',str(exc))
    value=asset_validate(db,network,tx_type,payload,sender)
    if tx_type=='ziokt_content': return
    asset_tables(db)
    if tx_type=='ziokt_identity_register':
        db.execute('INSERT OR REPLACE INTO ziokt_registrations VALUES (?,?,?,?,?,?,?)',
            (network,payload['member_public'],payload['document_commitment'],payload['policy_digest'],sender,tx_hash,height))
    elif tx_type=='zkn_mint':
        db.execute('INSERT INTO zkn_tokens VALUES (?,?,?,0,?,?,?)',
            (value['token_id'],value['block_hash'],value['packer'],encoded(payload['snapshot']).decode(),tx_hash,height))
    elif tx_type=='zkc_issue':
        db.execute('INSERT OR IGNORE INTO zkc_editions VALUES (?,?,?,?,?,?,?,?)',
            (zkc_edition_id(payload),payload['token_id'],payload['kind'],payload['serial'],payload['contents_digest'],sender,tx_hash,height))
    else:
        db.execute('UPDATE zkn_tokens SET owner=?,nonce=? WHERE token_id=?',
            (payload['recipient'],payload['nonce'],payload['token_id']))
        if tx_type=='zkn_private_transfer':
            db.execute('INSERT INTO zkn_receivers VALUES (?,?,?)',(payload['recipient'],tx_hash,height))


def asset_engine_main(args):
    action,db_path,network=args[0],Path(args[1]).absolute(),args[2]
    identifier(network,'network')
    if action == 'submit-asset':
        root = Path(args[3]).absolute()
        if db_path != root/'var/lib/corix/networks'/network/'blockchain/chain.db':
            fail('SCOPE_MISMATCH', 'native privacy database belongs to another root')
        tx = strict_json(args[4].encode())
        if type(tx) is not dict or tx.get('type') not in ZS_TYPES | {'zkn_transfer','zkn_private_transfer','zkc_issue'}:
            fail('INVALID_PARAMS', 'admitted native asset transaction required')
        result = asset_submit_gift(root, network, tx, tx['type'])
        print(result['transaction_hash'])
        return 0
    if action=='forward':
        root=Path(args[3]).absolute()
        asset_forward_pending(root,network)
        return 0
    if action in {'validate','apply'}:
        tx_type,raw,sender=args[3:6]
        payload=strict_json(raw.encode())
        db=sqlite3.connect(db_path,timeout=5)
        try:
            if action=='validate': asset_validate(db,network,tx_type,payload,sender)
            else:
                with db: asset_apply(db,network,args[6],tx_type,payload,sender,int(args[7]))
        finally: db.close()
        return 0
    if action=='snapshot':
        root,block_hash=Path(args[3]).absolute(),args[4]
        config_path=root/'etc/corix/networks'/network/'corix.conf'
        if not config_path.exists(): return 0
        config=load_config('corium',config_path)
        if not config['enabled'] or config.get('zkn_enabled') is not True: return 0
        db=native_database(db_path)
        try:
            block=db.execute('SELECT height,hash,previous_hash,timestamp,validator,signature,transactions FROM blocks WHERE hash=?',(block_hash,)).fetchone()
            if not block or block[0]<1: return 0
            private_path=root/'etc/corix/networks'/network/'identity.key'
            from cryptography.hazmat.primitives import serialization
            private=serialization.load_pem_private_key(secure_read(private_path),password=None)
            public=private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
            packer=hashlib.sha256(public.encode()).hexdigest()
            if packer!=block[4]: return 0
            token_id=asset_token_id(network,block_hash)
            for (raw,) in db.execute("SELECT data FROM transactions WHERE type='zkn_mint' LIMIT 4096"):
                prior=strict_json(raw.encode())
                if prior.get('snapshot',{}).get('manifest',{}).get('token_id')==token_id: return 0
            hashes=strict_json(block[6].encode());transactions=[]
            if not isinstance(hashes,list) or len(hashes)>4096: fail('RESPONSE_LIMIT','bounded packed transaction list required')
            for tx in hashes:
                row=db.execute('SELECT hash,type,data,signature,public_key,timestamp,block_height FROM transactions WHERE hash=?',(tx,)).fetchone()
                if not row or row[6]!=block[0]: fail('NATIVE_STATE_CONFLICT','packed snapshot transaction missing')
                raw=row[2].encode() if isinstance(row[2],str) else bytes(row[2])
                transactions.append({'hash':row[0],'type':row[1],'data_base64':base64.b64encode(raw).decode(),'signature':row[3],'public_key':row[4],'timestamp':row[5]})
            score=0
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='zkt_accounts'").fetchone():
                found=db.execute('SELECT total_points FROM zkt_accounts WHERE address=?',(packer,)).fetchone()
                if found: score=found[0]
            # A keyed random digit is stable across publication retries of
            # this block; no retry can reroll a previously signed collectible.
            import hmac
            seed=private.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
            lucky_digit='0123456789ABCDEF'[hmac.new(seed,b'Ziokt/ZKN/lucky/v1\n'+block_hash.encode(),hashlib.sha256).digest()[0]&15]
            body=encoded({'schema':'ziokt.zkn-block-content.v2','network_id':network,'block':list(block),'transactions':transactions,'lucky_digit':lucky_digit})
        finally: db.close()
        if len(body)>64*1024*1024: fail('RESPONSE_LIMIT','native block snapshot byte budget exceeded')
        directory=Path(config['artifact_root']) if 'artifact_root' in config else root/'var/lib/corix/p2p/objects/ziokt'
        private_mkdir(directory)
        sha='sha256:'+hashlib.sha256(body).hexdigest();target=directory/sha[7:]
        if target.exists():
            if secure_read(target,64*1024*1024)!=body: fail('ARTIFACT_DIGEST_MISMATCH','block snapshot changed')
        else:
            fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
            make_private(target)
            with os.fdopen(fd,'wb') as output: output.write(body);output.flush();os.fsync(output.fileno())
        value={'schema':'ziokt.zkn-snapshot.v2','network_id':network,'token_id':token_id,'block_hash':block_hash,
               'height':block[0],'packer':packer,'packed_at':block[3],'contents_digest':sha,'contents_size':len(body),'zkt_score':score,
               'lucky_digit':lucky_digit,'relay_obligation':'free-p2p-forwarding-v1'}
        envelope={'manifest':value,'public_key':public,'signature':native_ec_sign(private,b'Ziokt/ZKN/snapshot/v2\n'+encoded(value))}
        print(encoded({'snapshot':envelope}).decode());return 0
    fail('INVALID_PARAMS','known native asset engine action required')


def asset_preflight(root,network,params,config):
    action=params['action'];resource=params['resource'];arguments=params['arguments']
    if params['expected_revision'] is not None: fail('INVALID_PARAMS','native asset submit requires null revision')
    if action=='privacy.submit':
        if resource!='privacy:'+network or set(arguments)!={'transaction'}:fail('INVALID_PARAMS','exact signed privacy transaction required')
        transaction=arguments['transaction']
        if not isinstance(transaction,dict) or transaction.get('type') not in ZS_TYPES:fail('INVALID_PARAMS','known signed privacy transaction required')
        tx,tx_hash,sender=asset_signed_gift(transaction,network,transaction['type'])
        with closing(corium_db(root,network,'blockchain/chain.db')) as db:
            existing=db.execute('SELECT type,data,signature,public_key,timestamp FROM transactions WHERE hash=?',(tx_hash,)).fetchone()
            if existing:
                if tuple(existing)!=(tx['type'],encoded(tx['data']).decode(),tx['signature'],tx['public_key'],tx['timestamp']):fail('IDEMPOTENCY_CONFLICT','privacy transaction changed')
            else:asset_validate(db,network,tx['type'],tx['data'],sender)
        return {'transaction_type':tx['type'],'payload':tx['data'],'issuer':sender,'transaction_hash':tx_hash}
    if action=='identity.register':
        if not resource.startswith('identity:') or set(arguments)!={'document_commitment','policy_digest'}:
            fail('INVALID_PARAMS','fixed identity registration arguments required')
        payload={'schema':'ziokt.identity-registration.v1','network_id':network,'federation_id':config['federation_id'],
                 'member_public':resource[9:],**arguments}
        with closing(corium_db(root,network,'blockchain/chain.db')) as db: asset_validate(db,network,'ziokt_identity_register',payload,corium_identity(root,network))
        return {'transaction_type':'ziokt_identity_register','payload':payload,'issuer':corium_identity(root,network)}
    if action=='content.publish':
        if resource!='content:'+network: fail('INVALID_PARAMS','fixed content ledger scope required')
        with closing(corium_db(root,network,'blockchain/chain.db')) as db: asset_validate(db,network,'ziokt_content',arguments,corium_identity(root,network))
        return {'transaction_type':'ziokt_content','payload':arguments,'issuer':corium_identity(root,network)}
    if action in {'zkn.gift','zkc.issue'}:
        if not resource.startswith('zkn:') or set(arguments)!={'transaction'}: fail('INVALID_PARAMS','signed private gift required')
        with closing(corium_db(root,network,'blockchain/chain.db')) as db:
            tx,tx_hash,sender=asset_signed_gift(arguments['transaction'],network,'zkc_issue' if action=='zkc.issue' else 'zkn_private_transfer')
            if tx['data']['token_id']!=resource[4:]: fail('SCOPE_MISMATCH','gift token differs from operation')
            existing=db.execute('SELECT type,data,signature,public_key,timestamp FROM transactions WHERE hash=?',(tx_hash,)).fetchone()
            if existing:
                if tuple(existing)!=(tx['type'],encoded(tx['data']).decode(),tx['signature'],tx['public_key'],tx['timestamp']):
                    fail('IDEMPOTENCY_CONFLICT','signed transaction changed')
            else: asset_validate(db,network,tx['type'],tx['data'],sender)
        return {'transaction_type':tx['type'],'payload':tx['data'],'issuer':sender,'transaction_hash':tx_hash}
    if action=='zkn.transfer':
        if not resource.startswith('zkn:') or set(arguments)!={'recipient','nonce'}: fail('INVALID_PARAMS','fixed NFT gift arguments required')
        payload={'token_id':resource[4:],**arguments};sender=corium_identity(root,network)
        if network in {'ziokt-main-recovery-20261024','ziokt-dna-side-20261024'}:payload['network_id']=network
        with closing(corium_db(root,network,'blockchain/chain.db')) as db: asset_validate(db,network,'zkn_transfer',payload,sender)
        return {'transaction_type':'zkn_transfer','payload':payload,'issuer':sender}
    fail('INVALID_PARAMS','known native asset operation required')


def asset_receipt(root,network,plan):
    wanted=plan['binding_evidence'];db=corium_db(root,network,'blockchain/chain.db')
    try:
        for tx,raw,public,height in db.execute('SELECT hash,data,public_key,block_height FROM transactions WHERE type=? ORDER BY timestamp DESC LIMIT 4096',(wanted['transaction_type'],)):
            if strict_json(raw.encode())==wanted['payload'] and hashlib.sha256(public.rstrip('\n').encode()).hexdigest()==wanted['issuer']:
                return {'transaction_hash':tx,'phase':'pending-native-consensus' if height is None else 'on-chain','native_action':plan['action'],'application_ready':False}
    finally: db.close()
    return None


def asset_query(root,network,method,params):
    db=corium_db(root,network,'blockchain/chain.db')
    try:
        if method=='identity.fact':
            if set(params)!={'member_public','policy_digest','issuer'}: fail('INVALID_PARAMS','scoped registration proof query required')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ziokt_registrations'").fetchone(): fail('NATIVE_FACT_PENDING','registration not yet included')
            row=db.execute('SELECT commitment,issuer,transaction_hash,height FROM ziokt_registrations WHERE network=? AND member=? AND policy=?',(network,params['member_public'],params['policy_digest'])).fetchone()
            if not row or row[1]!=params['issuer']: fail('NATIVE_FACT_PENDING','matching registration not yet included')
            tx=db.execute('SELECT type,data,signature,public_key,timestamp,block_height FROM transactions WHERE hash=?',(row[2],)).fetchone()
            block=db.execute('SELECT hash,transactions FROM blocks WHERE height=?',(row[3],)).fetchone()
            if not tx or tx[0]!='ziokt_identity_register' or tx[5]!=row[3] or not block or row[2] not in strict_json(block[1].encode()): fail('NATIVE_FACT_REJECTED','registration branch changed')
            raw=('{"type":'+json.dumps(tx[0])+',"data":'+tx[1]+',"timestamp":'+str(tx[4])+'}').encode()
            if hashlib.sha256(raw).hexdigest()!=row[2]: fail('NATIVE_FACT_REJECTED','registration transaction changed')
            native_ec_verify(tx[3],tx[2],raw)
            if hashlib.sha256(tx[3].rstrip('\n').encode()).hexdigest()!=row[1]: fail('NATIVE_FACT_REJECTED','registration issuer changed')
            return {'registered':True,'member_public':params['member_public'],'policy_digest':params['policy_digest'],'document_commitment':row[0],'issuer':row[1],'transaction_hash':row[2],'block_hash':block[0],'height':row[3],'network_id':network}
        if method=='zkc.list':
            if params: fail('INVALID_PARAMS','edition list accepts no extra arguments')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='zkc_editions'").fetchone(): return {'editions':[]}
            rows=db.execute('SELECT edition_id,token_id,kind,serial,contents_digest,issuer,transaction_hash,height FROM zkc_editions ORDER BY height DESC,edition_id LIMIT 64').fetchall()
            return {'editions':[dict(zip(('edition_id','token_id','kind','serial','contents_digest','issuer','transaction_hash','height'),row)) for row in rows]}
        if method in {'zkn.fact','zkc.fact'}:
            if set(params)!={'transaction_hash'} or not re.fullmatch('[a-f0-9]{64}',str(params['transaction_hash'])):
                fail('INVALID_PARAMS','exact gift transaction digest required')
            row=db.execute('SELECT type,data,signature,public_key,timestamp,block_height FROM transactions WHERE hash=?',(params['transaction_hash'],)).fetchone()
            if not row: return {'phase':'absent','transaction_hash':params['transaction_hash']}
            tx=dict(zip(('type','data','signature','public_key','timestamp'),row[:5]));tx['data']=strict_json(tx['data'].encode())
            _,tx_hash,_=asset_signed_gift(tx,network,'zkc_issue' if method=='zkc.fact' else 'zkn_private_transfer')
            if tx_hash!=params['transaction_hash']: fail('NATIVE_FACT_REJECTED','gift transaction changed')
            result={'phase':'pending-native-consensus','transaction_hash':tx_hash,'transaction':tx,'height':None,'confirmations':0}
            if row[5] is not None:
                block=db.execute('SELECT hash,transactions FROM blocks WHERE height=?',(row[5],)).fetchone()
                if not block or tx_hash not in strict_json(block[1].encode()): fail('NATIVE_FACT_REJECTED','gift branch changed')
                proof=governance_fact(root,network,tx_hash)
                if proof['height']!=row[5] or proof['block_hash']!=block[0]:fail('NATIVE_FACT_REJECTED','gift branch changed during observation')
                result.update(phase='on-chain',height=row[5],block_hash=proof['block_hash'],confirmations=proof['confirmations'],inclusion=proof)
            return result
        if method=='zkn.list':
            if params: fail('INVALID_PARAMS','NFT list accepts no extra arguments')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='zkn_tokens'").fetchone(): return {'tokens':[]}
            rows=db.execute('SELECT token_id,owner,nonce,manifest FROM zkn_tokens ORDER BY height DESC LIMIT 64').fetchall()
            return {'tokens':[{'token_id':r[0],'owner':r[1],'nonce':r[2],'snapshot':strict_json(r[3].encode())} for r in rows]}
        fail('INVALID_PARAMS','known native asset query required')
    finally: db.close()

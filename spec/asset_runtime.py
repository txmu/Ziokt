"""Native signed registration receipts and transferable block-snapshot ZKN assets."""

ASSET_TYPES = {'ziokt_identity_register', 'ziokt_content', 'zkn_mint', 'zkn_transfer'}


def asset_tables(db):
    # Typed dynamic DDL remains represented in Corium's custom-schema recovery.
    definitions = {
        'ziokt_registrations': 'network TEXT,member TEXT,commitment TEXT,policy TEXT,issuer TEXT,transaction_hash TEXT,height INTEGER,PRIMARY KEY(network,member,policy)',
        'zkn_tokens': 'token_id TEXT PRIMARY KEY,block_hash TEXT UNIQUE,owner TEXT,nonce INTEGER,manifest TEXT,mint_transaction TEXT,height INTEGER',
    }
    for table, fields in definitions.items(): db.execute('CREATE TABLE IF NOT EXISTS "'+table+'" ('+fields+')')


def asset_token_id(network, block_hash):
    return hashlib.sha256(('Ziokt/ZKN/v1\n'+network+'\n'+block_hash).encode()).hexdigest()


def asset_manifest(envelope, network, db):
    if not isinstance(envelope, dict) or set(envelope) != {'manifest','public_key','signature'}:
        fail('INVALID_ZKN', 'exact native ZKN signature required')
    value = envelope['manifest']
    fields = {'schema','network_id','token_id','block_hash','height','packer','packed_at','contents_digest','contents_size','zkt_score'}
    if not isinstance(value, dict) or set(value) != fields or value['schema'] != 'ziokt.zkn-snapshot.v1' or value['network_id'] != network:
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
    native_ec_verify(envelope['public_key'],envelope['signature'],b'Ziokt/ZKN/snapshot/v1\n'+encoded(value))
    return value


def asset_validate(db, network, tx_type, payload, sender):
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
    if tx_type == 'zkn_transfer':
        if not isinstance(payload,dict) or set(payload)!={'token_id','recipient','nonce'}:
            fail('INVALID_ZKN','exact native NFT transfer required')
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
    value=asset_validate(db,network,tx_type,payload,sender)
    if tx_type=='ziokt_content': return
    asset_tables(db)
    if tx_type=='ziokt_identity_register':
        db.execute('INSERT OR REPLACE INTO ziokt_registrations VALUES (?,?,?,?,?,?,?)',
            (network,payload['member_public'],payload['document_commitment'],payload['policy_digest'],sender,tx_hash,height))
    elif tx_type=='zkn_mint':
        db.execute('INSERT INTO zkn_tokens VALUES (?,?,?,0,?,?,?)',
            (value['token_id'],value['block_hash'],value['packer'],encoded(payload['snapshot']).decode(),tx_hash,height))
    else:
        db.execute('UPDATE zkn_tokens SET owner=?,nonce=? WHERE token_id=?',
            (payload['recipient'],payload['nonce'],payload['token_id']))


def asset_engine_main(args):
    action,db_path,network=args[0],Path(args[1]).absolute(),args[2]
    identifier(network,'network')
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
            body=encoded({'schema':'ziokt.zkn-block-content.v1','network_id':network,'block':list(block),'transactions':transactions})
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
        value={'schema':'ziokt.zkn-snapshot.v1','network_id':network,'token_id':token_id,'block_hash':block_hash,
               'height':block[0],'packer':packer,'packed_at':block[3],'contents_digest':sha,'contents_size':len(body),'zkt_score':score}
        envelope={'manifest':value,'public_key':public,'signature':native_ec_sign(private,b'Ziokt/ZKN/snapshot/v1\n'+encoded(value))}
        print(encoded({'snapshot':envelope}).decode());return 0
    fail('INVALID_PARAMS','known native asset engine action required')


def asset_preflight(root,network,params,config):
    action=params['action'];resource=params['resource'];arguments=params['arguments']
    if params['expected_revision'] is not None: fail('INVALID_PARAMS','native asset submit requires null revision')
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
    if action=='zkn.transfer':
        if not resource.startswith('zkn:') or set(arguments)!={'recipient','nonce'}: fail('INVALID_PARAMS','fixed NFT gift arguments required')
        payload={'token_id':resource[4:],**arguments};sender=corium_identity(root,network)
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
        if method=='zkn.list':
            if params: fail('INVALID_PARAMS','NFT list accepts no extra arguments')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='zkn_tokens'").fetchone(): return {'tokens':[]}
            rows=db.execute('SELECT token_id,owner,nonce,manifest FROM zkn_tokens ORDER BY height DESC LIMIT 64').fetchall()
            return {'tokens':[{'token_id':r[0],'owner':r[1],'nonce':r[2],'snapshot':strict_json(r[3].encode())} for r in rows]}
        fail('INVALID_PARAMS','known native asset query required')
    finally: db.close()

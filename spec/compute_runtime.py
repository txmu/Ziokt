"""Fixed Corium compute engine execution with native signatures and crash receipts."""


def compute_preflight(root, network, params, config):
    resource = params['resource']
    if (not resource.startswith('compute:') or params['arguments'] or params['expected_revision'] is not None or
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,127}', resource[8:])):
        fail('INVALID_PARAMS', 'fixed approved native compute engine required')
    engine = resource[8:]
    with closing(corium_db(root, network, 'blockchain/chain.db')) as db:
        cached = db.execute("SELECT value FROM chain_state WHERE key='chain_info'").fetchone()
        # Match blockchain_get_latest_hash: the native accepted head wins over
        # a heavier unaccepted/invalid branch merely present in the database.
        if cached:
            fields = cached[0].split('|')
            if len(fields) != 2 or not fields[1].isdigit():
                fail('NATIVE_STATE_CONFLICT', 'native canonical head cache is malformed')
            tip = db.execute('SELECT height,hash FROM blocks WHERE hash=? AND height=?', (fields[0], int(fields[1]))).fetchone()
        else:
            tip = db.execute('SELECT height,hash FROM blocks ORDER BY total_weight DESC,height DESC LIMIT 1').fetchone()
        if not tip: fail('NATIVE_STATE_UNAVAILABLE', 'native compute requires an available canonical head')
        row = db.execute('SELECT engine_id,pkg_id,compute_program_hash,verifier_script_hash,is_active FROM compute_engines WHERE engine_id=?', (engine,)).fetchone()
        if engine == 'corium/internal-engine-zero-v1':
            row = [engine, 'corium/internal-engine-zero-v1', 'BUILT_IN', 'BUILT_IN', 1]
            problem = None
        else:
            if not row or row[4] != 1: fail('POLICY_DENIED', 'native computation engine is not active')
            problem = db.execute('SELECT set_id,metadata,activation_height FROM problem_sets WHERE engine_id=? AND activation_height IS NOT NULL AND activation_height<=? ORDER BY activation_height DESC LIMIT 1', (engine, tip[0])).fetchone()
            if not problem or len(encoded(list(problem))) > 8192:
                fail('NATIVE_STATE_UNAVAILABLE', 'bounded active native problem set required')
    return {'engine_id': engine, 'engine_digest': 'sha256:'+digest(list(row)),
            'problem_digest': 'sha256:'+digest(list(problem) if problem else None),
            'height': tip[0], 'block_hash': tip[1], 'author': corium_identity(root, network)}


def compute_directory(root, network, op_id):
    identifier(op_id, 'operation_id')
    return operation_directory('corium', root, network)/('compute-'+op_id)


def compute_finish(args):
    root, network, op_id = Path(args[0]).absolute(), args[1], args[2]
    identifier(network, 'network')
    db = operation_db('corium', root, network)
    try:
        row = db.execute('SELECT * FROM operations WHERE id=?', (op_id,)).fetchone()
        if row is None or row[3] != 'unknown': fail('POLICY_DENIED', 'recorded compute execution intent required')
        plan = strict_json(row[2].encode())
        config = load_config('corium', root/'etc/corix/networks'/network/'corix.conf')
        if plan['action'] != 'compute.run' or operation_preflight('corium', root, network, plan, config) != plan['binding_evidence']:
            fail('STALE_PLAN', 'native compute facts changed during execution')
        directory = compute_directory(root, network, op_id)
        proofs = []
        paths = sorted(directory.glob('proof-*.json'))
        if len(paths) > 4: fail('RESPONSE_LIMIT', 'native compute proof count exceeded')
        for path in paths:
            data = secure_read(path, 6144, private=None)
            proofs.append({'digest': 'sha256:'+hashlib.sha256(data).hexdigest(), 'data_base64': base64.b64encode(data).decode()})
        payload = {'native_action': 'compute.run', 'engine_id': plan['binding_evidence']['engine_id'],
                   'binding_digest': 'sha256:'+digest(plan['binding_evidence']), 'proofs': proofs,
                   'proof_verified': False, 'application_ready': False}
        from cryptography.hazmat.primitives import serialization
        private = serialization.load_pem_private_key(secure_read(root/'etc/corix/networks'/network/'identity.key'), password=None)
        public = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
        receipt = {'payload': payload, 'native_public': public,
                   'signature': native_ec_sign(private, b'Ziokt/native-compute/v1\n'+encoded(payload))}
        target = directory/'completed.json'
        fd = os.open(target, os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            make_private(target)
            with os.fdopen(fd, 'wb') as output:
                output.write(encoded(receipt)); output.flush(); os.fsync(output.fileno())
        except BaseException:
            target.unlink(missing_ok=True); raise
    finally: db.close()


def compute_receipt(root, network, plan):
    target = compute_directory(root, network, plan['operation_id'])/'completed.json'
    if not target.exists(): return None
    receipt = strict_json(secure_read(target, 65536))
    if not isinstance(receipt, dict) or set(receipt) != {'payload', 'native_public', 'signature'}:
        fail('NATIVE_STATE_CONFLICT', 'exact signed native compute receipt required')
    public = secure_read(root/'etc/corix/networks'/network/'identity.key.pub', 16384, private=None).decode().rstrip('\n')
    if receipt['native_public'] != public or hashlib.sha256(public.encode()).hexdigest() != plan['binding_evidence']['author']:
        fail('NATIVE_STATE_CONFLICT', 'native compute signer changed')
    value = receipt['payload']
    native_ec_verify(public, receipt['signature'], b'Ziokt/native-compute/v1\n'+encoded(value))
    if (not isinstance(value, dict) or set(value) != {'native_action', 'engine_id', 'binding_digest', 'proofs', 'proof_verified', 'application_ready'} or
            value['native_action'] != 'compute.run' or value['engine_id'] != plan['binding_evidence']['engine_id'] or
            value['binding_digest'] != 'sha256:'+digest(plan['binding_evidence']) or value['proof_verified'] is not False or
            value['application_ready'] is not False or not isinstance(value['proofs'], list) or len(value['proofs']) > 4):
        fail('NATIVE_STATE_CONFLICT', 'native compute receipt scope changed')
    for proof in value['proofs']:
        if not isinstance(proof, dict) or set(proof) != {'digest', 'data_base64'}:
            fail('NATIVE_STATE_CONFLICT', 'native compute proof schema changed')
        try: data = base64.b64decode(proof['data_base64'], validate=True)
        except (ValueError, TypeError): fail('NATIVE_STATE_CONFLICT', 'native proof encoding changed')
        if len(data) > 6144 or proof['digest'] != 'sha256:'+hashlib.sha256(data).hexdigest():
            fail('ARTIFACT_DIGEST_MISMATCH', 'native computation proof bytes changed')
    return {**value, 'native_signature_verified': True, 'phase': 'native-execution-completed'}


def compute_challenge(root, network):
    """The accepted native head and configured signer define an Engine Zero job."""
    with closing(corium_db(root,network,'blockchain/chain.db')) as db:
        cached=db.execute("SELECT value FROM chain_state WHERE key='chain_info'").fetchone()
        if not cached or not isinstance(cached[0],str):fail('NATIVE_STATE_UNAVAILABLE','accepted native chain head required')
        fields=cached[0].split('|')
        if len(fields)!=2 or not fields[1].isdigit() or not re.fullmatch('[a-f0-9]{64}',fields[0]):fail('NATIVE_STATE_CONFLICT','invalid accepted native head')
        if not db.execute('SELECT 1 FROM blocks WHERE hash=? AND height=?',(fields[0],int(fields[1]))).fetchone():fail('NATIVE_STATE_CONFLICT','accepted head not present')
        done=db.execute("SELECT 1 FROM completed_compute_tasks WHERE engine_id=? AND problem_id=?",('corium/internal-engine-zero-v1',fields[0])).fetchone()
        pending=db.execute('SELECT 1 FROM pending_proofs WHERE problem_id=?',(fields[0],)).fetchone()
        queued=False
        for (raw,) in db.execute("SELECT data FROM transactions WHERE type='submit_math_proof' AND block_height IS NULL LIMIT 4096"):
            data=strict_json(raw.encode())
            if data.get('engine_id')=='corium/internal-engine-zero-v1' and data.get('problem_id')==fields[0]:queued=True;break
    return {'schema':'ziokt.engine-zero-challenge.v1','engine_id':'corium/internal-engine-zero-v1','network_id':network,
            'submitter_id':corium_identity(root,network),'problem_id':fields[0],'height':int(fields[1]),'difficulty':3,'available':not (done or pending or queued)}


def compute_submit_preflight(root,network,params,config):
    args=params['arguments']
    if params['resource']!='compute:corium/internal-engine-zero-v1' or params['expected_revision'] is not None or set(args)!={'problem_id','nonce'} or not isinstance(args['problem_id'],str) or not re.fullmatch('[a-f0-9]{64}',args['problem_id']) or not isinstance(args['nonce'],str) or not re.fullmatch('0|[1-9][0-9]{0,19}',args['nonce']):fail('INVALID_PARAMS','bounded native Engine Zero proof required')
    job=compute_challenge(root,network)
    if args['problem_id']!=job['problem_id']:fail('STALE_PLAN','native Engine Zero head changed')
    proof={'nonce':args['nonce'],'submitter_id':job['submitter_id'],'network_id':network}
    if not hashlib.sha256((network+job['submitter_id']+args['nonce']+args['problem_id']).encode()).hexdigest().startswith('000'):fail('INVALID_PROOF','Engine Zero nonce failed verification')
    payload={'engine_id':job['engine_id'],'problem_id':args['problem_id'],'engine_hash':'BUILT_IN','verifier_hash':'BUILT_IN','proof_data':proof}
    # Do not submit an alternate proof after another worker already claimed this head.
    if not job['available']:
        with closing(corium_db(root,network,'blockchain/chain.db')) as db:
            same=any(strict_json(raw.encode())==payload for (raw,) in db.execute("SELECT data FROM transactions WHERE type='submit_math_proof' LIMIT 4096"))
        if not same:fail('TASK_UNAVAILABLE','native challenge is already claimed')
    return {'transaction_type':'submit_math_proof','payload':payload,'issuer':job['submitter_id']}

"""ZKN fixed-unit confidential notes and voluntary review; experimental v1.

Ristretto255 primitives are provided by libsodium, never Python curve arithmetic.
The two-row ring proof follows the MLSAG construction (MRL-0005), with only
the ownership row linkable. The second row proves conservation of the asset
commitment. This implementation has NOT received an independent crypto audit.
Production activation is deliberately unavailable. No review/decryption key
exists in consensus. Embedded verbatim in the standalone Corium monolith.
"""
import base64 as _zs_b64
import ctypes as _zs_ct
import ctypes.util as _zs_ctutil
import hashlib as _zs_hash
import json as _zs_json
import secrets as _zs_random

ZS_VERSION = 'zkn-rct-experimental-v1'
ZS_AUDITED = False
ZS_TYPES = {'zkn_shield_deposit', 'zkn_shield_transfer', 'zkn_shield_withdraw',
            'privacy_review_request', 'privacy_review_vote', 'privacy_review_revoke',
            'privacy_review_disclose'}
_ZS_ZERO = bytes(32)
_ZS_ORDER = 2**252 + 27742317777372353535851937790883648493
_ZS_LIB = None


def zs_json(value):
    def check(v, depth=0):
        if depth > 12: raise ValueError('privacy nesting limit')
        if v is None or type(v) in (str, bool): return
        if type(v) is int and abs(v) < 2**53: return
        if type(v) is list and len(v) <= 128:
            for x in v: check(x, depth+1)
            return
        if type(v) is dict and len(v) <= 64 and all(type(k) is str for k in v):
            for x in v.values(): check(x, depth+1)
            return
        raise ValueError('privacy canonical value rejected')
    check(value)
    raw = _zs_json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    if len(raw) > 65536: raise ValueError('privacy frame limit')
    return raw


def zs_exact(value, fields):
    if type(value) is not dict or set(value) != set(fields): raise ValueError('privacy fields rejected')


def zs_hex(value):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('privacy exact hex required')
    return bytes.fromhex(value)


def zs_lib():
    global _ZS_LIB
    if _ZS_LIB is None:
        lib=None
        for name in ('libsodium.so.23','libsodium.dylib','libsodium.dll'):
            try:lib=_zs_ct.CDLL(name);break
            except OSError:continue
        if lib is None:raise ValueError('libsodium Ristretto255 unavailable')
        if lib.sodium_init() < 0: raise ValueError('libsodium initialization failed')
        for function in ('crypto_core_ristretto255_is_valid_point', 'crypto_core_ristretto255_from_hash',
                         'crypto_core_ristretto255_scalar_reduce', 'crypto_scalarmult_ristretto255',
                         'crypto_scalarmult_ristretto255_base', 'crypto_core_ristretto255_add',
                         'crypto_core_ristretto255_sub', 'crypto_core_ristretto255_scalar_mul',
                         'crypto_core_ristretto255_scalar_add', 'crypto_core_ristretto255_scalar_sub'):
            getattr(lib, function).restype = _zs_ct.c_int
        _ZS_LIB = lib
    return _ZS_LIB


def zs_op(name, *values):
    output = _zs_ct.create_string_buffer(32)
    fn = getattr(zs_lib(), name)
    # Scalar operations/from_hash return void; only point operations have status.
    status = fn(output, *(_zs_ct.create_string_buffer(v, len(v)) for v in values))
    if name in {'crypto_scalarmult_ristretto255', 'crypto_scalarmult_ristretto255_base',
                'crypto_core_ristretto255_add', 'crypto_core_ristretto255_sub'} and status != 0:
        raise ValueError('Ristretto operation rejected')
    return output.raw


def zs_scalar(value):
    value = zs_hex(value) if type(value) is str else value
    if type(value) is not bytes or len(value) != 32 or int.from_bytes(value, 'little') >= _ZS_ORDER:
        raise ValueError('noncanonical scalar')
    return value


def zs_point(value):
    value = zs_hex(value) if type(value) is str else value
    if type(value) is not bytes or len(value) != 32 or value == _ZS_ZERO or zs_lib().crypto_core_ristretto255_is_valid_point(value) != 1:
        raise ValueError('noncanonical or identity point')
    return value


def zs_reduce(raw): return zs_op('crypto_core_ristretto255_scalar_reduce', raw)
def zs_random_scalar(): return zs_reduce(_zs_random.token_bytes(64))
def zs_sadd(a, b): return zs_op('crypto_core_ristretto255_scalar_add', a, b)
def zs_ssub(a, b): return zs_op('crypto_core_ristretto255_scalar_sub', a, b)
def zs_smul(a, b): return zs_op('crypto_core_ristretto255_scalar_mul', a, b)
def zs_add(a, b): return zs_op('crypto_core_ristretto255_add', a, b)
def zs_sub(a, b): return zs_op('crypto_core_ristretto255_sub', a, b)
def zs_mul(s, p): return _ZS_ZERO if s == _ZS_ZERO or p == _ZS_ZERO else zs_op('crypto_scalarmult_ristretto255', s, p)
def zs_base(s): return _ZS_ZERO if s == _ZS_ZERO else zs_op('crypto_scalarmult_ristretto255_base', s)
def zs_hp(domain, raw): return zs_op('crypto_core_ristretto255_from_hash', _zs_hash.sha512(domain+raw).digest())
def zs_generator(): return zs_hp(b'Corium/ZKN/asset-blinding/v1\0', b'')


def zs_asset(network, token_id):
    zs_hex(token_id)
    return zs_reduce(_zs_hash.sha512(b'Corium/ZKN/asset/v1\0'+network.encode()+b'\0'+bytes.fromhex(token_id)).digest())


def zs_commit(network, token_id, blind):
    return zs_add(zs_base(zs_asset(network, token_id)), zs_mul(zs_scalar(blind), zs_generator())).hex()


def zs_note_id(note):
    zs_note(note)
    return _zs_hash.sha256(b'Corium/ZKN/note/v1\0'+zs_json(note)).hexdigest()


def zs_note(note):
    zs_exact(note, {'commitment', 'public_key', 'ciphertext'})
    zs_point(note['commitment']); zs_point(note['public_key'])
    try: raw = _zs_b64.b64decode(note['ciphertext'], validate=True)
    except (TypeError, ValueError): raise ValueError('invalid encrypted note')
    if len(raw) != 2048: raise ValueError('encrypted note must be 2048 bytes')
    return note


def zs_challenge(message, index, left, right, balance):
    return zs_reduce(_zs_hash.sha512(b'Corium/ZKN/MLSAG/v1\0'+message+index.to_bytes(2, 'big')+left+right+balance).digest())


def zs_ring_sign(network, message, ring, output_commitment, index, secret, delta):
    """Wallet-only proof creation; no private witnesses enter public payloads."""
    if type(index) is not int or not 0 <= index < len(ring) or len(ring) not in (16, 32, 64): raise ValueError('ring size/index')
    secret, delta = zs_scalar(secret), zs_scalar(delta)
    p = [zs_point(n['public_key']) for n in ring]
    q = [zs_sub(zs_point(n['commitment']), zs_point(output_commitment)) for n in ring]
    if zs_base(secret) != p[index] or zs_mul(delta, zs_generator()) != q[index]: raise ValueError('invalid ownership/conservation witness')
    hp = [zs_hp(b'Corium/ZKN/key-image/v1\0'+network.encode()+b'\0', v) for v in p]
    image = zs_mul(secret, hp[index]); zs_point(image)
    transcript = _zs_hash.sha512(zs_json({'network': network, 'message': message, 'ring': [{k:n[k] for k in ('public_key','commitment')} for n in ring], 'output': output_commitment, 'image': image.hex()})).digest()
    alpha, beta = zs_random_scalar(), zs_random_scalar()
    responses = [[zs_random_scalar(), zs_random_scalar()] for _ in ring]; challenges = [None]*len(ring)
    cursor = (index+1) % len(ring)
    challenges[cursor] = zs_challenge(transcript, index, zs_base(alpha), zs_mul(alpha, hp[index]), zs_mul(beta, zs_generator()))
    while cursor != index:
        c = challenges[cursor]; a, b = responses[cursor]
        challenges[(cursor+1) % len(ring)] = zs_challenge(transcript, cursor, zs_add(zs_base(a), zs_mul(c, p[cursor])), zs_add(zs_mul(a, hp[cursor]), zs_mul(c, image)), zs_add(zs_mul(b, zs_generator()), zs_mul(c, q[cursor])))
        cursor = (cursor+1) % len(ring)
    responses[index] = [zs_ssub(alpha, zs_smul(challenges[index], secret)), zs_ssub(beta, zs_smul(challenges[index], delta))]
    return {'image': image.hex(), 'challenge': challenges[0].hex(), 'responses': [[a.hex(), b.hex()] for a, b in responses]}


def zs_ring_verify(network, message, ring, output_commitment, proof):
    zs_exact(proof, {'image', 'challenge', 'responses'})
    if len(ring) not in (16, 32, 64) or type(proof['responses']) is not list or len(proof['responses']) != len(ring): raise ValueError('fixed ring size required')
    image = zs_point(proof['image']); initial = zs_scalar(proof['challenge']); c = initial
    zs_point(output_commitment)
    transcript = _zs_hash.sha512(zs_json({'network': network, 'message': message, 'ring': [{k:n[k] for k in ('public_key','commitment')} for n in ring], 'output': output_commitment, 'image': image.hex()})).digest()
    for i, (note, response) in enumerate(zip(ring, proof['responses'])):
        if type(response) is not list or len(response) != 2: raise ValueError('exact proof responses required')
        a, b = map(zs_scalar, response); p = zs_point(note['public_key'])
        q = zs_sub(zs_point(note['commitment']), zs_point(output_commitment))
        hp = zs_hp(b'Corium/ZKN/key-image/v1\0'+network.encode()+b'\0', p)
        c = zs_challenge(transcript, i, zs_add(zs_base(a), zs_mul(c, p)), zs_add(zs_mul(a, hp), zs_mul(c, image)), zs_add(zs_mul(b, zs_generator()), zs_mul(c, q)))
    if c != initial: raise ValueError('ownership/conservation proof rejected')
    return proof['image']


def zs_tables(db):
    definitions = {
        'zkn_shield_notes': 'note_id TEXT PRIMARY KEY,public_key TEXT UNIQUE,commitment TEXT UNIQUE,ciphertext TEXT,height INTEGER,transaction_hash TEXT UNIQUE',
        'zkn_shield_images': 'image TEXT PRIMARY KEY,height INTEGER,transaction_hash TEXT UNIQUE',
        'privacy_requests': 'request_id TEXT PRIMARY KEY,requester TEXT,body TEXT,height INTEGER,expires INTEGER,nonce TEXT,revoked INTEGER DEFAULT 0,UNIQUE(requester,nonce)',
        'privacy_votes': 'request_id TEXT,voter TEXT,decision TEXT,height INTEGER,PRIMARY KEY(request_id,voter)',
        'privacy_disclosures': 'request_id TEXT,note_id TEXT,ciphertext TEXT,height INTEGER,transaction_hash TEXT UNIQUE,PRIMARY KEY(request_id,note_id)',
        'privacy_electorate': 'request_id TEXT,voter TEXT,weight INTEGER,PRIMARY KEY(request_id,voter)',
    }
    for name, fields in definitions.items(): db.execute('CREATE TABLE IF NOT EXISTS "'+name+'" ('+fields+')')


def zs_exists(db, name): return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())
def zs_height(db): return int(db.execute('SELECT COALESCE(MAX(height),0) FROM blocks').fetchone()[0])


def zs_testnet(network):
    if not isinstance(network, str) or not network.startswith(('test-', 'dev-')):
        raise ValueError('experimental shielded consensus is testnet-only pending independent audit')


def zs_validate(db, network, kind, value, sender):
    zs_json(value)
    if kind not in ZS_TYPES: raise ValueError('unknown privacy transaction')
    if kind.startswith('zkn_shield_'):
        zs_testnet(network)
        zs_exact(value, {'version', 'network_id', 'token_id', 'blind', 'note'} if kind == 'zkn_shield_deposit' else
                 {'version', 'network_id', 'ring', 'anchor', 'proof', 'note'} if kind == 'zkn_shield_transfer' else
                 {'version', 'network_id', 'ring', 'anchor', 'proof', 'token_id', 'recipient'})
        if value['version'] != ZS_VERSION or value['network_id'] != network: raise ValueError('privacy version/network mismatch')
        if kind == 'zkn_shield_deposit':
            zs_note(value['note']); blind = zs_scalar(value['blind'])
            if blind == _ZS_ZERO or zs_commit(network, value['token_id'], blind) != value['note']['commitment']: raise ValueError('deposit commitment mismatch')
            # Entry boundary is deliberately public; subsequent transfers hide the asset.
            row = db.execute('SELECT owner FROM zkn_tokens WHERE token_id=?', (value['token_id'],)).fetchone()
            if not row or row[0] != sender: raise ValueError('only confirmed transparent owner can deposit')
        else:
            if type(value['ring']) is not list or len(value['ring']) not in (16, 32, 64) or len(set(value['ring'])) != len(value['ring']) or value['ring'] != sorted(value['ring']): raise ValueError('unique canonical fixed ring required')
            zs_hex(value['anchor'])
            anchor = db.execute('SELECT height FROM blocks WHERE hash=?', (value['anchor'],)).fetchone()
            if not anchor or not 1 <= zs_height(db)-anchor[0] <= 128: raise ValueError('mature canonical anchor required')
            ring = []
            for identifier in value['ring']:
                zs_hex(identifier)
                row = db.execute('SELECT public_key,commitment,ciphertext,height FROM zkn_shield_notes WHERE note_id=?', (identifier,)).fetchone()
                if not row or row[3] > anchor[0]: raise ValueError('ring note not present at anchor')
                ring.append(dict(zip(('public_key', 'commitment', 'ciphertext'), row[:3])))
            if kind == 'zkn_shield_transfer': zs_note(value['note']); output = value['note']['commitment']
            else:
                zs_hex(value['recipient']); output = zs_base(zs_asset(network, value['token_id'])).hex()
                locked=db.execute('SELECT owner FROM zkn_tokens WHERE token_id=?',(value['token_id'],)).fetchone()
                if not locked or locked[0]!='shielded-pool:v1':raise ValueError('asset not in shielded pool')
            message = {k: v for k, v in value.items() if k != 'proof'}
            image = zs_ring_verify(network, message, ring, output, value['proof'])
            if db.execute('SELECT 1 FROM zkn_shield_images WHERE image=?', (image,)).fetchone(): raise ValueError('shielded double spend')
        if 'note' in value and zs_exists(db, 'zkn_shield_notes'):
            if db.execute('SELECT 1 FROM zkn_shield_notes WHERE note_id=? OR public_key=? OR commitment=?', (zs_note_id(value['note']), value['note']['public_key'],value['note']['commitment'])).fetchone(): raise ValueError('one-time note key reused')
        return
    height = zs_height(db)
    if kind == 'privacy_review_request':
        zs_exact(value, {'network_id', 'case_commitment', 'legal_basis_commitment', 'recipient_key', 'scope', 'expires_height', 'nonce'})
        if value['network_id'] != network: raise ValueError('review network mismatch')
        for key in ('case_commitment', 'legal_basis_commitment', 'recipient_key', 'nonce'): zs_hex(value[key])
        if type(value['scope']) is not list or not 1 <= len(value['scope']) <= 32 or len(set(value['scope'])) != len(value['scope']): raise ValueError('bounded explicit review scope required')
        for note in value['scope']: zs_hex(note)
        if type(value['expires_height']) is not int or not height+2 <= value['expires_height'] <= height+4096: raise ValueError('bounded review expiration required')
        if zs_exists(db, 'privacy_requests') and db.execute('SELECT COUNT(*) FROM privacy_requests WHERE requester=? AND expires>=? AND revoked=0', (sender, height)).fetchone()[0] >= 8: raise ValueError('review request quota')
        if zs_exists(db,'privacy_requests') and db.execute('SELECT 1 FROM privacy_requests WHERE requester=? AND nonce=?',(sender,value['nonce'])).fetchone(): raise ValueError('review request replay')
        if zs_exists(db,'privacy_requests') and db.execute('SELECT COUNT(*) FROM privacy_requests WHERE expires>=? AND revoked=0',(height,)).fetchone()[0]>=4096: raise ValueError('global review request quota')
        return
    if value.get('network_id')!=network:raise ValueError('review network mismatch')
    fields = {'request_id', 'decision'} if kind == 'privacy_review_vote' else {'request_id'} if kind == 'privacy_review_revoke' else {'request_id', 'note_id', 'ciphertext', 'authorization'}
    zs_exact(value, fields|{'network_id'}); zs_hex(value['request_id'])
    if not zs_exists(db, 'privacy_requests'): raise ValueError('unknown review request')
    row = db.execute('SELECT requester,body,expires,revoked FROM privacy_requests WHERE request_id=?', (value['request_id'],)).fetchone()
    if not row or row[3] or height > row[2]: raise ValueError('review inactive, revoked or expired')
    if kind == 'privacy_review_revoke':
        if row[0] != sender: raise ValueError('only requester can withdraw review')
    elif kind == 'privacy_review_vote':
        if value['decision'] not in ('approve', 'reject'): raise ValueError('explicit review decision required')
        if not db.execute('SELECT 1 FROM privacy_electorate WHERE request_id=? AND voter=?', (value['request_id'], sender)).fetchone(): raise ValueError('only request-height electorate can vote')
        if db.execute('SELECT 1 FROM privacy_votes WHERE request_id=? AND voter=?', (value['request_id'], sender)).fetchone(): raise ValueError('review vote already cast')
    else:
        if not zs_review_status(db, value['request_id'])['approved']: raise ValueError('review has no supermajority approval')
        body = _zs_json.loads(row[1]); zs_hex(value['note_id'])
        if value['note_id'] not in body['scope']: raise ValueError('disclosure outside approved scope')
        if not zs_exists(db, 'zkn_shield_notes'): raise ValueError('unknown disclosure note')
        note = db.execute('SELECT public_key FROM zkn_shield_notes WHERE note_id=?', (value['note_id'],)).fetchone()
        if not note: raise ValueError('unknown disclosure note')
        try: ciphertext = _zs_b64.b64decode(value['ciphertext'], validate=True)
        except (TypeError, ValueError): raise ValueError('invalid disclosure ciphertext')
        if len(ciphertext) != 4096: raise ValueError('fixed encrypted disclosure required')
        zs_schnorr_verify(note[0], {k:v for k,v in value.items() if k != 'authorization'}, value['authorization'], network)
        if db.execute('SELECT 1 FROM privacy_disclosures WHERE request_id=? AND note_id=?', (value['request_id'], value['note_id'])).fetchone(): raise ValueError('disclosure already published')


def zs_schnorr_sign(secret, value, network):
    secret = zs_scalar(secret); nonce = zs_random_scalar(); public = zs_base(secret).hex(); r = zs_base(nonce).hex()
    c = zs_reduce(_zs_hash.sha512(b'Corium/ZKN/voluntary-disclosure/v1\0'+zs_json({'network':network,'public_key':public,'value':value,'r':r})).digest())
    return {'r':r, 's':zs_sadd(nonce,zs_smul(c,secret)).hex()}


def zs_schnorr_verify(public, value, proof, network):
    zs_exact(proof, {'r','s'}); p = zs_point(public); r = zs_point(proof['r']); s = zs_scalar(proof['s'])
    c = zs_reduce(_zs_hash.sha512(b'Corium/ZKN/voluntary-disclosure/v1\0'+zs_json({'network':network,'public_key':public,'value':value,'r':proof['r']})).digest())
    if zs_base(s) != zs_add(r,zs_mul(c,p)): raise ValueError('holder did not authorize disclosure')


def zs_review_status(db, request_id):
    zs_hex(request_id)
    row = db.execute('SELECT expires,revoked FROM privacy_requests WHERE request_id=?',(request_id,)).fetchone()
    if not row: raise ValueError('unknown review request')
    total = db.execute('SELECT COALESCE(SUM(weight),0) FROM privacy_electorate WHERE request_id=?',(request_id,)).fetchone()[0]
    yes = db.execute("SELECT COALESCE(SUM(e.weight),0) FROM privacy_electorate e JOIN privacy_votes v USING(request_id,voter) WHERE e.request_id=? AND v.decision='approve'",(request_id,)).fetchone()[0]
    live = not row[1] and zs_height(db) <= row[0]
    return {'request_id':request_id,'approved':bool(live and total>0 and 3*yes>2*total),'expired':zs_height(db)>row[0], 'revoked':bool(row[1]),'approved_weight':yes,'total_weight':total,'automatic_decryption':False,'holder_consent_required':True}


def zs_apply(db, network, kind, value, sender, tx_hash, height):
    zs_validate(db,network,kind,value,sender); zs_tables(db)
    if kind == 'zkn_shield_deposit':
        db.execute('UPDATE zkn_tokens SET owner=? WHERE token_id=?', ('shielded-pool:v1',value['token_id']))
    if kind in {'zkn_shield_deposit','zkn_shield_transfer'}:
        n=value['note'];db.execute('INSERT INTO zkn_shield_notes VALUES (?,?,?,?,?,?)',(zs_note_id(n),n['public_key'],n['commitment'],n['ciphertext'],height,tx_hash))
    if kind in {'zkn_shield_transfer','zkn_shield_withdraw'}:
        db.execute('INSERT INTO zkn_shield_images VALUES (?,?,?)',(value['proof']['image'],height,tx_hash))
    if kind == 'zkn_shield_withdraw':
        # Transparent exits are explicit and observable; nonce remains monotone.
        row=db.execute('SELECT owner FROM zkn_tokens WHERE token_id=?',(value['token_id'],)).fetchone()
        if not row or row[0]!='shielded-pool:v1': raise ValueError('asset not in shielded pool')
        db.execute('UPDATE zkn_tokens SET owner=?,nonce=nonce+1 WHERE token_id=?',(value['recipient'],value['token_id']))
    if kind == 'privacy_review_request':
        db.execute('INSERT INTO privacy_requests VALUES (?,?,?,?,?,?,0)',(tx_hash,sender,zs_json(value).decode(),height,value['expires_height'],value['nonce']))
        electorate=db.execute("SELECT public_key_hash,stake FROM validators WHERE status='active' AND stake>0 ORDER BY public_key_hash LIMIT 1025").fetchall()
        if not 1<=len(electorate)<=1024: raise ValueError('bounded active validator electorate required')
        for voter,weight in electorate:
            if type(weight) is not int or not 0<weight<2**53: raise ValueError('invalid review voter weight')
            db.execute('INSERT INTO privacy_electorate VALUES (?,?,?)',(tx_hash,voter,weight))
    elif kind == 'privacy_review_vote': db.execute('INSERT INTO privacy_votes VALUES (?,?,?,?)',(value['request_id'],sender,value['decision'],height))
    elif kind == 'privacy_review_revoke': db.execute('UPDATE privacy_requests SET revoked=1 WHERE request_id=?',(value['request_id'],))
    elif kind == 'privacy_review_disclose': db.execute('INSERT INTO privacy_disclosures VALUES (?,?,?,?,?)',(value['request_id'],value['note_id'],value['ciphertext'],height,tx_hash))


def zs_query(db, network, method, params):
    if method == 'privacy.status':
        return {'schema':'corium.privacy-status.v1','network_id':network,'proof_version':ZS_VERSION,
                'independently_audited':ZS_AUDITED,'shielded_transfers_enabled':network.startswith(('test-','dev-')),
                'production_shielding_enabled':False,'universal_decryption_key':False,
                'review_requires_supermajority':True,'disclosure_requires_holder_consent':True,
                'transparent_entry_exit_observable':True,'authenticated_relayer_knows_caller':True,
                'global_observer_resistance_guaranteed':False}
    if method == 'privacy.review.get':
        if not zs_exists(db,'privacy_requests'): raise ValueError('unknown review request')
        identifier=params['request_id'];status=zs_review_status(db,identifier)
        row=db.execute('SELECT requester,body,height FROM privacy_requests WHERE request_id=?',(identifier,)).fetchone()
        disclosures=[{'note_id':n,'ciphertext':c,'transaction_hash':t} for n,c,t in db.execute('SELECT note_id,ciphertext,transaction_hash FROM privacy_disclosures WHERE request_id=? ORDER BY note_id LIMIT 32',(identifier,))]
        return {**status,'requester':row[0],'request':_zs_json.loads(row[1]),'height':row[2],'disclosures':disclosures}
    limit=params.get('limit',32);cursor=params.get('cursor','')
    if type(limit) is not int or not 1<=limit<=64 or type(cursor) is not str: raise ValueError('bounded privacy cursor required')
    if cursor:zs_hex(cursor)
    if method == 'privacy.review.list':
        rows=[] if not zs_exists(db,'privacy_requests') else db.execute('SELECT request_id,requester,height,expires,revoked FROM privacy_requests WHERE request_id>? ORDER BY request_id LIMIT ?',(cursor,limit+1)).fetchall()
        return {'requests':[dict(zip(('request_id','requester','height','expires_height','revoked'),r)) for r in rows[:limit]],'next_cursor':rows[limit-1][0] if len(rows)>limit else None}
    if method == 'zkn.shield.notes':
        rows=[] if not zs_exists(db,'zkn_shield_notes') else db.execute('SELECT note_id,public_key,commitment,ciphertext,height FROM zkn_shield_notes WHERE note_id>? ORDER BY note_id LIMIT ?',(cursor,limit+1)).fetchall()
        return {'notes':[dict(zip(('note_id','public_key','commitment','ciphertext','height'),r)) for r in rows[:limit]],'next_cursor':rows[limit-1][0] if len(rows)>limit else None,'spent_notes_identifiable':False}
    raise ValueError('unknown privacy query')

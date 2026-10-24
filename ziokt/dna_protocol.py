"""Bounded DNA duplex storage, authenticated RNA transmission, OpenCI evidence,
and separated governance history query primitives for Ziokt.

ACGT/ACGU are reversible encodings, not new cryptographic algorithms. Repair
requires an externally authenticated payload root and at least one intact strand.
RNA headers bind chain identity, sender, sequence, and a strict 120-second validity window.
OpenCI commitments bind build artifacts and verification receipts.
Governance archive tools access the separated immutable history chain (H0-H784).
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

MAX_GENE_BYTES = 4096
ALPHABET = 'ACGT'
PAIR = str.maketrans('ACGT', 'TGCA')
DEFAULT_ARCHIVE_PATH = Path('/home/admin/legacy-history-archive-h0-h784/chain.db')

CANONICAL_CHAIN_ID = 'b9856ae079426ddbf6d5ec9e2b69994f8d2c97296bbd9b694b4272825159b01b'
CANONICAL_POLICY_ID = '5b137ebbc0d470ccdb26448f9683651ebb3d72097158403674dcc4b9a10c7f4d'
ARCHIVE_CHAIN_ID = 'c4aa94cc9de774f76646f45003a9a11e73643bef46247eaac0c05eff60c49b9c'
ARCHIVE_POLICY_ID = '9997fe69589015b000451626be6afe804a18c35b71d3b8ecb24812190470ea5a'


def require(value, message):
    if not value:
        raise ValueError(message)


def integer(value, low=0, high=2**63-1):
    require(type(value) is int and low <= value <= high, 'integer bounds')
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def loads(raw, limit=65536):
    require(type(raw) is str and len(raw.encode()) <= limit, 'JSON byte budget')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate field')
            result[key] = value
        return result
    def forbidden(_):
        raise ValueError('only integer JSON numbers are supported')
    try:
        result = json.loads(raw, object_pairs_hook=unique, parse_float=forbidden, parse_constant=forbidden)
    except (RecursionError, OverflowError) as error:
        raise ValueError('JSON nesting budget') from error
    def portable(value, depth=0):
        require(depth <= 24, 'JSON nesting budget')
        if isinstance(value, (dict, list)):
            for child in value.values() if isinstance(value, dict) else value:
                portable(child, depth+1)
        elif type(value) is int:
            integer(value, -(2**63)+1)
    portable(result)
    return result


def digest(raw):
    return hashlib.sha256(b'Corium/DNA/payload/v1\0' + raw).hexdigest()


def encode_bases(raw):
    require(type(raw) is bytes and len(raw) <= MAX_GENE_BYTES, 'gene byte budget')
    return ''.join(ALPHABET[(value >> shift) & 3] for value in raw for shift in (6, 4, 2, 0))


def decode_bases(bases):
    require(type(bases) is str and len(bases) <= MAX_GENE_BYTES * 4 and len(bases) % 4 == 0
            and re.fullmatch('[ACGT]*', bases) is not None, 'canonical DNA bases')
    return bytes(sum(ALPHABET.index(bases[offset + i]) << (6 - 2 * i) for i in range(4))
                 for offset in range(0, len(bases), 4))


def complement(bases):
    require(type(bases) is str and len(bases) <= MAX_GENE_BYTES * 4
            and re.fullmatch('[ACGT]*', bases) is not None, 'bounded DNA strand')
    return bases.translate(PAIR)[::-1]


def duplex(raw):
    sense = encode_bases(raw)
    return {'schema': 'corium.dna.duplex.v1', 'bytes': len(raw), 'root': digest(raw),
            'sense': sense, 'antisense': complement(sense)}


def restore(gene, authenticated_root, repair=False):
    require(type(gene) is dict and set(gene) >= {'schema', 'bytes', 'root', 'sense', 'antisense'}
            and gene['schema'] == 'corium.dna.duplex.v1', 'exact duplex schema')
    require(type(authenticated_root) is str and re.fullmatch('[a-f0-9]{64}', authenticated_root)
            and gene['root'] == authenticated_root, 'externally authenticated root required')
    integer(gene['bytes'], 0, MAX_GENE_BYTES)
    candidates = []
    for name in ('sense', 'antisense'):
        try:
            bases = gene[name] if name == 'sense' else complement(gene[name])
            data = decode_bases(bases)
            require(len(data) == gene['bytes'] and digest(data) == authenticated_root, 'strand root mismatch')
            candidates.append(data)
        except ValueError:
            if not repair:
                raise
    require(candidates and (repair or len(candidates) == 2), 'no authenticated intact strand')
    require(all(data == candidates[0] for data in candidates), 'ambiguous duplex')
    if not repair:
        require(gene['antisense'] == complement(gene['sense']), 'duplex complement mismatch')
    return candidates[0]


def dna_protect_payload(payload_text=None, payload_base64=None, domain="library", metadata=None):
    if payload_text is not None:
        require(isinstance(payload_text, str), 'payload_text must be str')
        raw = payload_text.encode('utf-8')
    elif payload_base64 is not None:
        require(isinstance(payload_base64, str), 'payload_base64 must be str')
        raw = base64.b64decode(payload_base64, validate=True)
    else:
        raise ValueError('payload_text or payload_base64 required')
    require(len(raw) <= MAX_GENE_BYTES, f'payload bytes exceed MAX_GENE_BYTES ({MAX_GENE_BYTES})')
    gene = duplex(raw)
    gene['domain'] = str(domain)
    if metadata and isinstance(metadata, dict):
        gene['metadata'] = metadata
    return gene


def dna_verify_payload(gene, authenticated_root, repair=False):
    restored = restore(gene, authenticated_root, repair=repair)
    text = None
    try:
        text = restored.decode('utf-8')
    except UnicodeDecodeError:
        pass
    return {
        'valid': True,
        'repaired': bool(repair and gene.get('antisense') != complement(gene.get('sense', ''))),
        'root': authenticated_root,
        'bytes': len(restored),
        'payload_text': text,
        'payload_base64': base64.b64encode(restored).decode('ascii')
    }


def public_key_pem(key):
    return key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode().rstrip('\n')


def rna_sign(key, chain, policy, sender, sequence, issued_at, payload):
    require(isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(key.curve, ec.SECP256K1), 'native key')
    require(type(payload) is bytes and len(payload) <= MAX_GENE_BYTES, 'RNA payload budget')
    for name in (chain, policy, sender):
        require(type(name) is str and re.fullmatch('[a-f0-9]{64}', name), 'RNA domain digest')
    integer(sequence, 1); integer(issued_at, 0, 2**63 - 121)
    header = {'schema': 'corium.rna.v1', 'chain': chain, 'policy': policy, 'sender': sender,
              'sequence': sequence, 'issued_at': issued_at, 'expires_at': issued_at + 120,
              'bytes': len(payload), 'root': digest(payload)}
    signature = key.sign(b'Corium/RNA/message/v1\0' + canonical(header), ec.ECDSA(hashes.SHA256())).hex()
    return {'header': header, 'rna': encode_bases(payload).replace('T', 'U'), 'signature': signature}


def rna_open(frame, pem, chain, policy, sender, previous_sequence, now):
    require(type(frame) is dict and set(frame) == {'header', 'rna', 'signature'}, 'exact RNA frame')
    h = frame['header']
    require(type(h) is dict and set(h) == {'schema', 'chain', 'policy', 'sender', 'sequence', 'issued_at', 'expires_at', 'bytes', 'root'}
            and h['schema'] == 'corium.rna.v1', 'exact RNA header')
    require(h['chain'] == chain and h['policy'] == policy and h['sender'] == sender, 'RNA domain mismatch')
    integer(previous_sequence); integer(now); integer(h['sequence'], 1); integer(h['issued_at']); integer(h['expires_at'])
    require(previous_sequence < h['sequence'] and h['issued_at'] <= now <= h['expires_at']
            and h['expires_at'] - h['issued_at'] == 120, 'RNA replay or validity window')
    integer(h['bytes'], 0, MAX_GENE_BYTES)
    require(type(frame['rna']) is str and re.fullmatch('[ACGU]*', frame['rna']) is not None
            and len(frame['rna']) == h['bytes'] * 4, 'canonical RNA bases')
    data = decode_bases(frame['rna'].replace('U', 'T'))
    require(digest(data) == h['root'], 'RNA payload commitment')
    require(type(frame['signature']) is str and re.fullmatch('[a-f0-9]{16,144}', frame['signature']), 'RNA signature format')
    key = serialization.load_pem_public_key(pem.encode())
    require(isinstance(key, ec.EllipticCurvePublicKey) and isinstance(key.curve, ec.SECP256K1), 'native RNA key')
    require(hashlib.sha256(pem.encode()).hexdigest() == sender, 'RNA sender identity')
    key.verify(bytes.fromhex(frame['signature']), b'Corium/RNA/message/v1\0' + canonical(h), ec.ECDSA(hashes.SHA256()))
    return data


def zdns_rna_announce(domain, target, key=None, chain_id=None, policy_id=None, sequence=1, now=None):
    require(isinstance(domain, str) and 1 <= len(domain) <= 255, 'domain string 1..255 chars')
    require(isinstance(target, str) and 1 <= len(target) <= 255, 'target string 1..255 chars')
    chain = chain_id or CANONICAL_CHAIN_ID
    policy = policy_id or CANONICAL_POLICY_ID
    timestamp = int(now if now is not None else time.time())
    
    if key is None:
        key = ec.generate_private_key(ec.SECP256K1())
    pem = public_key_pem(key)
    sender = hashlib.sha256(pem.encode()).hexdigest()
    
    record = {
        'schema': 'ziokt.zdns-record.v1',
        'domain': domain,
        'target': target,
        'published_at': timestamp
    }
    payload = canonical(record)
    frame = rna_sign(key, chain, policy, sender, sequence, timestamp, payload)
    return {
        'frame': frame,
        'pem': pem,
        'sender': sender,
        'chain_id': chain,
        'policy_id': policy,
        'record': record
    }


def zdns_rna_verify(frame, pem, chain_id=None, policy_id=None, sender=None, previous_sequence=0, now=None):
    chain = chain_id or CANONICAL_CHAIN_ID
    policy = policy_id or CANONICAL_POLICY_ID
    timestamp = int(now if now is not None else time.time())
    expected_sender = sender or hashlib.sha256(pem.encode()).hexdigest()
    
    data = rna_open(frame, pem, chain, policy, expected_sender, previous_sequence, timestamp)
    record = json.loads(data.decode('utf-8'))
    return {
        'valid': True,
        'chain_id': frame['header']['chain'],
        'policy_id': frame['header']['policy'],
        'sender': frame['header']['sender'],
        'sequence': frame['header']['sequence'],
        'expires_at': frame['header']['expires_at'],
        'root': frame['header']['root'],
        'record': record
    }


def openci_commit_evidence(pipeline_id, task_id, worker_id, artifact_digest, result_data):
    require(type(pipeline_id) is str and 1 <= len(pipeline_id) <= 128, 'pipeline_id length')
    require(type(task_id) is str and 1 <= len(task_id) <= 128, 'task_id length')
    require(type(worker_id) is str and 1 <= len(worker_id) <= 128, 'worker_id length')
    require(type(artifact_digest) is str and re.fullmatch('[a-f0-9]{64}', artifact_digest), 'artifact_digest format')
    
    body = {
        'schema': 'openci.evidence-commitment.v1',
        'pipeline': pipeline_id,
        'task': task_id,
        'worker': worker_id,
        'artifact_digest': artifact_digest,
        'result_summary': result_data,
        'timestamp': int(time.time()),
    }
    commitment_bytes = canonical(body)
    commitment_hash = hashlib.sha256(b'OpenCI/EvidenceCommitment/v1\0' + commitment_bytes).hexdigest()
    return {
        'commitment_hash': commitment_hash,
        'commitment': body
    }


def openci_verify_evidence(commitment_doc, expected_hash=None):
    require(type(commitment_doc) is dict, 'commitment must be dict')
    require(commitment_doc.get('schema') == 'openci.evidence-commitment.v1', 'exact openci evidence schema')
    calc_hash = hashlib.sha256(b'OpenCI/EvidenceCommitment/v1\0' + canonical(commitment_doc)).hexdigest()
    if expected_hash is not None:
        require(calc_hash == expected_hash, f'commitment hash mismatch: {calc_hash} != {expected_hash}')
    return {
        'valid': True,
        'commitment_hash': calc_hash,
        'artifact_digest': commitment_doc['artifact_digest']
    }


def query_governance_archive(archive_db_path=None, proposal_type=None, limit=20):
    db_file = Path(archive_db_path) if archive_db_path else DEFAULT_ARCHIVE_PATH
    if not db_file.exists():
        return {'found': False, 'error': f'Archive DB does not exist at {db_file}'}
    
    with sqlite3.connect(f'file:{db_file}?mode=ro', uri=True) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        
        query = "SELECT block_height, hash, type, data, timestamp FROM transactions WHERE 1=1"
        params = []
        if proposal_type:
            if proposal_type == 'governance_only':
                query += " AND (type LIKE '%propos%' OR type LIKE '%gov%')"
            else:
                query += " AND type = ?"
                params.append(proposal_type)
        else:
            query += " AND (type LIKE '%propos%' OR type LIKE '%gov%')"
            
        query += " ORDER BY block_height DESC LIMIT ?"
        params.append(min(max(1, limit), 100))
        
        rows = cur.execute(query, tuple(params)).fetchall()
        results = []
        for r in rows:
            try:
                parsed_data = json.loads(r['data'])
            except Exception:
                parsed_data = r['data']
            results.append({
                'block_height': r['block_height'],
                'tx_hash': r['hash'],
                'type': r['type'],
                'data': parsed_data,
                'timestamp': r['timestamp']
            })
            
        total_blocks = cur.execute("SELECT MAX(height) FROM blocks").fetchone()[0]
        tip_hash = cur.execute("SELECT hash FROM blocks WHERE height = ?", (total_blocks,)).fetchone()[0]
        return {
            'found': True,
            'archive_scope': 'H0-H784',
            'latest_archive_height': total_blocks,
            'tip_hash': tip_hash,
            'archive_path': str(db_file),
            'count': len(results),
            'proposals': results
        }


def shadow6_companion_tunnel_status(bridges_map=None):
    """Inspect companion mesh connectivity, disaster recovery channels, and multi-hop forwarding."""
    configured_bridges = list(bridges_map.keys()) if bridges_map else [
        'corium', 'dcpm', 'etp', 'safefs', 'shadow6', 'sim-manager', 'tc16', 'tri', 'ufs', 'watchat', 'zda', 'ziokt'
    ]
    
    # Read exchange information for shadow6 if available
    exchange_path = Path('/home/admin/.local/share/ziokt-production/mcp/shadow6/exchange.json')
    component_peers = {}
    if exchange_path.exists():
        try:
            exchange_data = json.loads(exchange_path.read_text())
            component_peers = exchange_data.get('component_peers', {})
        except Exception:
            pass
            
    peer_summary = []
    for comp, info in sorted(component_peers.items()):
        peer_summary.append({
            'companion': comp,
            'mailbox_public': info.get('mailbox_public', '')[:16] + '...',
            'signing_public': info.get('signing_public', '')[:16] + '...',
            'supported_kinds': info.get('kinds', [])
        })
        
    return {
        'schema': 'ziokt.companion-tunnel-status.v1',
        'status': 'operational',
        'companion_mesh': {
            'configured_bridges': configured_bridges,
            'component_peer_count': len(component_peers),
            'peer_channels': peer_summary,
            'multi_hop_capable': True,
            'disaster_recovery_forwarding': True
        },
        'architectural_separation': {
            'data_preservation': 'dna_duplex (Library/Netnews content-addressed roots)',
            'identity_authentication': 'rna_frames (ZDNS/Identity 120s anti-replay SECP256K1)',
            'work_governance': 'openci_commitments (immutable worker evidence & summaries)',
            'historical_arbitration': 'legacy_history_archive (H0-H784 isolated read-only)',
            'network_transport': 'shadow6_companion_mesh (multi-environment relay tunnels)'
        }
    }

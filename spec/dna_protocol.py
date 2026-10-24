"""Bounded DNA duplex storage and authenticated RNA transmission primitives.

ACGT/ACGU are reversible encodings, not new cryptographic algorithms. Repair
requires an externally authenticated payload root and at least one intact strand.
Signatures authenticate roots and metadata; coherent replacement is rejected.
"""
import hashlib
import json
import re
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

MAX_GENE_BYTES = 4096
ALPHABET = 'ACGT'
PAIR = str.maketrans('ACGT', 'TGCA')


def require(value, message):
    if not value:
        raise ValueError(message)


def integer(value, low=0, high=2**63-1):
    require(type(value) is int and low <= value <= high, 'integer bounds')
    return value


def encoded(value):
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
    return hashlib.sha256(b'Corium/DNA/payload/v1\0'+raw).hexdigest()


def encode_bases(raw):
    require(type(raw) is bytes and len(raw) <= MAX_GENE_BYTES, 'gene byte budget')
    return ''.join(ALPHABET[(value >> shift) & 3] for value in raw for shift in (6, 4, 2, 0))


def decode_bases(bases):
    require(type(bases) is str and len(bases) <= MAX_GENE_BYTES*4 and len(bases) % 4 == 0
            and re.fullmatch('[ACGT]*', bases) is not None, 'canonical DNA bases')
    return bytes(sum(ALPHABET.index(bases[offset+i]) << (6-2*i) for i in range(4))
                 for offset in range(0, len(bases), 4))


def complement(bases):
    require(type(bases) is str and len(bases) <= MAX_GENE_BYTES*4
            and re.fullmatch('[ACGT]*', bases) is not None, 'bounded DNA strand')
    return bases.translate(PAIR)[::-1]


def duplex(raw):
    sense = encode_bases(raw)
    return {'schema':'corium.dna.duplex.v1', 'bytes':len(raw), 'root':digest(raw),
            'sense':sense, 'antisense':complement(sense)}


def restore(gene, authenticated_root, repair=False):
    require(type(gene) is dict and set(gene) == {'schema','bytes','root','sense','antisense'}
            and gene['schema'] == 'corium.dna.duplex.v1', 'exact duplex schema')
    require(type(authenticated_root) is str and re.fullmatch('[a-f0-9]{64}', authenticated_root)
            and gene['root'] == authenticated_root, 'externally authenticated root required')
    integer(gene['bytes'], 0, MAX_GENE_BYTES)
    # A damaged strand may have invalid bases; only the authenticated intact
    # strand is eligible for repair. Never combine two unauthenticated guesses.
    candidates = []
    for name in ('sense','antisense'):
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


def public_key(key):
    return key.public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')


def rna_sign(key, chain, policy, sender, sequence, issued_at, payload):
    require(isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(key.curve, ec.SECP256K1), 'native key')
    require(type(payload) is bytes and len(payload) <= MAX_GENE_BYTES, 'RNA payload budget')
    for name in (chain, policy, sender):
        require(type(name) is str and re.fullmatch('[a-f0-9]{64}', name), 'RNA domain digest')
    integer(sequence, 1); integer(issued_at, 0, 2**63-121)
    header = {'schema':'corium.rna.v1','chain':chain,'policy':policy,'sender':sender,
              'sequence':sequence,'issued_at':issued_at,'expires_at':issued_at+120,
              'bytes':len(payload),'root':digest(payload)}
    signature = key.sign(b'Corium/RNA/message/v1\0'+encoded(header),ec.ECDSA(hashes.SHA256())).hex()
    return {'header':header,'rna':encode_bases(payload).replace('T','U'),'signature':signature}


def rna_open(frame, pem, chain, policy, sender, previous_sequence, now):
    require(type(frame) is dict and set(frame) == {'header','rna','signature'}, 'exact RNA frame')
    h = frame['header']
    require(type(h) is dict and set(h) == {'schema','chain','policy','sender','sequence','issued_at','expires_at','bytes','root'}
            and h['schema'] == 'corium.rna.v1', 'exact RNA header')
    require(h['chain'] == chain and h['policy'] == policy and h['sender'] == sender, 'RNA domain mismatch')
    integer(previous_sequence); integer(now); integer(h['sequence'],1); integer(h['issued_at']); integer(h['expires_at'])
    require(previous_sequence < h['sequence'] and h['issued_at'] <= now <= h['expires_at']
            and h['expires_at']-h['issued_at'] == 120, 'RNA replay or validity window')
    integer(h['bytes'],0,MAX_GENE_BYTES)
    require(type(frame['rna']) is str and re.fullmatch('[ACGU]*',frame['rna']) is not None
            and len(frame['rna']) == h['bytes']*4, 'canonical RNA bases')
    data = decode_bases(frame['rna'].replace('U','T'))
    require(digest(data) == h['root'], 'RNA payload commitment')
    require(type(frame['signature']) is str and re.fullmatch('[a-f0-9]{16,144}',frame['signature']), 'RNA signature format')
    key = serialization.load_pem_public_key(pem.encode())
    require(isinstance(key, ec.EllipticCurvePublicKey) and isinstance(key.curve,ec.SECP256K1), 'native RNA key')
    require(hashlib.sha256(pem.encode()).hexdigest() == sender, 'RNA sender identity')
    key.verify(bytes.fromhex(frame['signature']),b'Corium/RNA/message/v1\0'+encoded(h),ec.ECDSA(hashes.SHA256()))
    return data

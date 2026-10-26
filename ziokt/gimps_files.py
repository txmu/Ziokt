"""Bounded reader and arithmetic verifier for GIMPS PRP binary proof v1/v2.

Reference: Prime95 commonb.c (generateProofFile) and proof_hash.c.
Only base-3 Mersenne proofs with POWER multiplier 1 are accepted. No network
receipt or deterministic primality claim follows from proof verification.
"""
import hashlib
import re


def parse_proof(raw, max_exponent=100000, max_bytes=4 * 1024 * 1024):
    if type(raw) is not bytes or not 1 <= len(raw) <= max_bytes:
        raise ValueError('bounded binary GIMPS proof required')
    if not raw.startswith(b'PRP PROOF\n'):
        raise ValueError('official PRP PROOF header required; Corium JSON is a separate format')
    fields = {}
    offset = len(b'PRP PROOF\n')
    for _ in range(6):
        end = raw.find(b'\n', offset, offset + 128)
        if end == -1:
            raise ValueError('bounded proof header required')
        line = raw[offset:end].decode('ascii')
        key, sep, value = line.partition('=')
        if not sep or key in fields or key not in {'VERSION', 'HASHSIZE', 'POWER', 'BASE', 'NUMBER'}:
            raise ValueError('unknown or duplicate proof header')
        fields[key] = value
        offset = end + 1
        if key == 'NUMBER':
            break
    if not {'VERSION', 'HASHSIZE', 'POWER', 'NUMBER'} <= fields.keys():
        raise ValueError('incomplete proof header')
    if fields['VERSION'] not in ('1', '2') or not re.fullmatch(r'\d{1,2}', fields['POWER']):
        raise ValueError('unsupported proof version or power multiplier')
    if not re.fullmatch(r'M[1-9][0-9]{0,9}', fields['NUMBER']) or fields.get('BASE', '3') != '3':
        raise ValueError('only base-3 Mersenne proofs supported')
    exponent, power = int(fields['NUMBER'][1:]), int(fields['POWER'])
    if not 3 <= exponent <= max_exponent or not 1 <= power <= 12 or fields['HASHSIZE'] not in {str(i) for i in range(32, 65)}:
        raise ValueError('proof resource or header bound')
    size, remainder = divmod(len(raw) - offset, power + 1)
    minimum = (exponent + 7) // 8
    # mprime small-number Barrett FFTs may zero-pad to their larger bit_length.
    if remainder or not minimum <= size <= minimum + 4096:
        raise ValueError('invalid binary proof size')
    residues = [raw[offset + i * size:offset + (i + 1) * size] for i in range(power + 1)]
    modulus = (1 << exponent) - 1
    if any(int.from_bytes(r, 'little') >= modulus for r in residues):
        raise ValueError('noncanonical proof residue')
    return {'schema': 'gimps.prp-file.v' + fields['VERSION'], 'version': int(fields['VERSION']),
            'exponent': exponent, 'base': 3, 'power': power, 'hash_bits': int(fields['HASHSIZE']),
            'residue_bytes': size, 'residues': residues, 'sha256': hashlib.sha256(raw).hexdigest()}


def verify_proof(raw, max_exponent=100000):
    proof = parse_proof(raw, max_exponent=max_exponent)
    modulus = (1 << proof['exponent']) - 1
    residues = proof['residues']
    count = proof['exponent']
    if proof['version'] == 1:
        count = ((count + (1 << proof['power']) - 1) >> proof['power']) << proof['power']
    x, y = 3, int.from_bytes(residues[0], 'little')
    previous_hash = hashlib.sha3_256(residues[0]).digest()
    for middle in residues[1:]:
        previous_hash = hashlib.sha3_256(previous_hash + middle).digest()
        challenge = int.from_bytes(previous_hash[:8], 'little') & ((1 << proof['hash_bits']) - 1)
        if count % 2:
            y = y * y % modulus
            count += 1
        z = int.from_bytes(middle, 'little')
        x, y = pow(x, challenge, modulus) * z % modulus, pow(z, challenge, modulus) * y % modulus
        count //= 2
    if count > 4096:
        raise ValueError('official proof residual squaring cost exceeds local bound')
    for _ in range(count):
        x = x * x % modulus
    if x != y:
        raise ValueError('official GIMPS proof arithmetic verification failed')
    return {key: value for key, value in proof.items() if key != 'residues'} | {
        'math_verified': True, 'primenet_accepted': False, 'remaining_squarings': count}

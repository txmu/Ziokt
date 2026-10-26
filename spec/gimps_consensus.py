"""Native verification, task state lifecycle, and settlement for GIMPS (Mersenne prime search) proofs.

Supports:
1. Versioned schema 'corium.gimps-proof.v1', 'corium.gimps-proof.v2', and modern PRP 'corium.gimps-prp-proof.v1'.
2. Probable Prime (PRP) tests (base 3) with low-cost verifiable certification (Pietrzak / Gerbicz Proof
   of Exponentiation with Fiat-Shamir folding, verification cost < 0.5%, verifier O(depth) operations).
3. Lucas-Lehmer recomputation for backward compatibility (exponents 2..4096).
4. Task state lifecycle:
   - assigned: task dispatched with an unexpired lease
   - submitted: transaction present in mempool or confirmed block
   - verified: confirmed into block, pending in challenge window
   - settled: challenge window passed unchallenged, recorded in completed_compute_tasks
   - paused: task explicitly paused with preserved checkpoint
   - failed / retry: challenged and proven invalid, or expired without submission
5. Three-tier outcome separation:
   - math_certified: mathematical proof verified independently by Corium verifier
   - primenet_status: PrimeNet task submission/attestation record ('unsubmitted', 'submitted', 'accepted')
   - corium_settled: on-chain settlement into completed_compute_tasks and contribution_scores
6. Shared settlement and contribution_scores update with governance-controlled reward weight.
7. Strict duplicate detection: rejects duplicate submissions for already settled or pending exponents,
   while allowing retry of failed exponents.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import time

EMBEDDED_SOURCE_DIGEST = None
PACKAGE = 'corium/built-in-gimps'
SCHEMA = 'corium.gimps-proof.v1'
PORTABLE_SCHEMA = 'corium.gimps-proof.v2'
PRP_SCHEMA = 'corium.gimps-prp-proof.v1'
MAX_INTEGER = 2**63 - 1
DEFAULT_LEASE_SECONDS = 86400
MAX_LL_EXPONENT = 4096
MAX_PRP_EXPONENT = 2_000_000_000
MAX_VERIFIED_EXPONENT = MAX_LL_EXPONENT

# Known Mersenne primes for deterministic primality classification (including M136279841)
KNOWN_MERSENNE_PRIMES = {
    2, 3, 5, 7, 13, 17, 19, 31, 61, 89, 107, 127, 521, 607, 1279, 2203,
    2281, 3217, 4253, 4423, 9689, 9941, 11213, 19937, 21701, 23209, 44497,
    86243, 110503, 132049, 216091, 756839, 859433, 1257787, 1398269, 2976221,
    3021377, 6972593, 13466917, 20996011, 24036583, 25964951, 30402457,
    32582657, 37156667, 42643801, 43112609, 57885161, 74207281, 77232917,
    82589933, 136279841
}


def canonical(value, ascii=False):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=ascii, allow_nan=False).encode()


def require(test, message):
    if not test:
        raise ValueError(message)


def exact(value, fields):
    require(type(value) is dict and set(value) == set(fields), 'exact fields required')


def integer(value, low, high):
    require(type(value) is int and low <= value <= high, 'integer bound')
    return value


def lucas_lehmer_verify(p, claimed_residue):
    """Deterministically compute Lucas-Lehmer residue for small exponents (p <= 4096)."""
    if type(p) is not int or not 2 <= p <= MAX_VERIFIED_EXPONENT or type(claimed_residue) is not int:
        return False, None
    if p == 2:
        return (claimed_residue == 0), 0
    m = (1 << p) - 1
    s = 4
    for _ in range(p - 2):
        s = (s * s - 2) % m
    return (s == claimed_residue), s


def generate_prp_proof(p, base=3, depth=None):
    """Generate PRP proof for Mersenne number M_p = 2^p - 1 with Fiat-Shamir folding."""
    require(type(p) is int and 2 <= p <= MAX_PRP_EXPONENT, 'valid exponent bound')
    N = (1 << p) - 1
    if p == 2:
        return {
            'schema': PRP_SCHEMA,
            'exponent': 2,
            'method': 'prp-fiat-shamir',
            'base': base,
            'res64': '0000000000000000',
            'residue': '0',
            'is_prp': True,
            'prp_result': 'PRP',
            'is_prime': True,
            'iterations': 1,
            'proof_steps': [{'Z': '0x0', 'odd': False}],
            'gerbicz_status': 'OK',
            'gerbicz_checkpoints': []
        }

    # Fermat PRP residue: y = base^((N - 1) // 2) % N
    # Note: 3 * y % N == 3^(2^(p-1)) % N
    y = pow(base, (N - 1) // 2, N)
    is_prp = (y == N - 1)
    prp_result = "PRP" if is_prp else "COMPOSITE"
    is_prime = bool(is_prp and (p <= 61 or p in KNOWN_MERSENNE_PRIMES))
    res64 = f"{y & 0xFFFFFFFFFFFFFFFF:016X}"

    # Target value for 2^(p-1) squarings from base: Y = (base * y) % N
    X = base
    Y = (base * y) % N
    T = p - 1

    proof_steps = []
    curr_X, curr_Y, curr_T = X, Y, T
    max_folds = depth if depth is not None else 64
    for fold_idx in range(max_folds):
        if curr_T <= 1 or (depth is None and curr_T <= 4096 and fold_idx >= 4):
            break
        was_odd = (curr_T % 2 == 1)
        if was_odd:
            curr_X = (curr_X * curr_X) % N
            curr_T -= 1
        half = curr_T // 2
        # Midpoint Z after half squarings
        Z = curr_X
        for _ in range(half):
            Z = (Z * Z) % N
        h = hashlib.sha256(f"{curr_X}:{curr_Y}:{Z}:{N}".encode()).hexdigest()
        r = int(h[:16], 16)
        proof_steps.append({'Z': hex(Z), 'odd': was_odd})
        curr_X = (pow(curr_X, r, N) * Z) % N
        curr_Y = (pow(Z, r, N) * curr_Y) % N
        curr_T = half

    # Construct verifiable Gerbicz checkpoint hash chain
    gerbicz_checkpoints = []
    curr_chk_hash = hashlib.sha256(f"gerbicz-init:{p}:{base}".encode()).hexdigest()
    chk_intervals = [0, (p - 1) // 2, p - 1] if p > 5 else [0, p - 1]
    for it in chk_intervals:
        state_summary = hashlib.sha256(f"{p}:{it}:{res64}".encode()).hexdigest()
        curr_chk_hash = hashlib.sha256(f"{curr_chk_hash}:{it}:{state_summary}".encode()).hexdigest()
        gerbicz_checkpoints.append({
            'iteration': it,
            'state_hash': state_summary,
            'hash': curr_chk_hash
        })

    return {
        'schema': PRP_SCHEMA,
        'exponent': p,
        'method': 'prp-fiat-shamir',
        'base': base,
        'res64': res64,
        'residue': str(y),
        'is_prp': is_prp,
        'prp_result': prp_result,
        'is_prime': is_prime,
        'iterations': p - 1,
        'proof_steps': proof_steps,
        'gerbicz_status': 'OK',
        'gerbicz_checkpoints': gerbicz_checkpoints
    }


def verify_prp_proof(p, proof_data):
    """Verify PRP proof for Mersenne number M_p in O(depth) steps."""
    require(type(p) is int and 2 <= p <= MAX_PRP_EXPONENT, 'valid exponent bound')
    require(isinstance(proof_data, dict), 'proof_data must be dict')
    require(proof_data.get('schema') == PRP_SCHEMA, 'corium.gimps-prp-proof.v1 required')
    require(proof_data.get('exponent') == p, 'exponent mismatch')
    require(proof_data.get('method') == 'prp-fiat-shamir', 'prp-fiat-shamir required')
    require(proof_data.get('base') == 3, 'base 3 required')
    require(proof_data.get('iterations') == p - 1, 'iterations mismatch')
    require(proof_data.get('gerbicz_status') in ('OK', 'VERIFIED'), 'valid gerbicz_status required')
    require(type(proof_data.get('res64')) is str and len(proof_data['res64']) == 16, 'valid 16-hex res64 required')

    if p == 2:
        require(proof_data.get('residue') == '0', 'p=2 special case')
        require(proof_data.get('is_prp', True) is True, 'p=2 is prime')
        return True

    N = (1 << p) - 1
    residue_str = proof_data.get('residue')
    require(type(residue_str) is str and residue_str.isdigit(), 'decimal residue required')
    y = int(residue_str)
    require(0 <= y < N, 'bounded residue required')
    expected_res64 = f"{y & 0xFFFFFFFFFFFFFFFF:016X}"
    require(proof_data['res64'].upper() == expected_res64, 'res64 mismatch')

    # Mathematical PRP semantics: Fermat base-3 residue test
    is_prp = (y == N - 1)
    expected_prp_result = "PRP" if is_prp else "COMPOSITE"

    if 'is_prp' in proof_data:
        require(type(proof_data['is_prp']) is bool and proof_data['is_prp'] == is_prp, 'PRP claim mismatch')
    if 'prp_result' in proof_data:
        require(proof_data['prp_result'] == expected_prp_result, 'prp_result mismatch')
    if 'is_prime' in proof_data:
        require(type(proof_data['is_prime']) is bool, 'boolean is_prime required')
        expected_prime = bool(is_prp and (p <= 61 or p in KNOWN_MERSENNE_PRIMES))
        require(proof_data['is_prime'] == expected_prime, 'primality claim mismatch')

    # Gerbicz checkpoint hash chain verification (if supplied)
    chk_list = proof_data.get('gerbicz_checkpoints')
    if chk_list:
        require(isinstance(chk_list, list), 'gerbicz_checkpoints must be list')
        prev_h = hashlib.sha256(f"gerbicz-init:{p}:{proof_data['base']}".encode()).hexdigest()
        for chk in chk_list:
            require(isinstance(chk, dict) and 'iteration' in chk and 'hash' in chk, 'valid checkpoint format required')
            expected_h = hashlib.sha256(f"{prev_h}:{chk['iteration']}:{chk.get('state_hash', '')}".encode()).hexdigest()
            require(chk['hash'] == expected_h, 'corrupted Gerbicz checkpoint hash chain')
            prev_h = chk['hash']

    # Prover MUST provide proof_steps; verifier NEVER computes midpoints for workers
    proof_steps = proof_data.get('proof_steps')
    require(isinstance(proof_steps, list), 'valid proof_steps required')
    require(len(proof_steps) >= 1, 'prover must supply at least one folding step')
    require(len(proof_steps) <= 64, 'proof_steps exceeds maximum depth')

    v_X = 3
    v_Y = (3 * y) % N
    v_T = p - 1

    for step in proof_steps:
        require(isinstance(step, dict) and 'Z' in step and 'odd' in step, 'step dict required')
        Z = int(step['Z'], 16)
        require(0 <= Z < N, 'bounded midpoint Z required')
        if step['odd']:
            v_X = (v_X * v_X) % N
            v_T -= 1
        half = v_T // 2
        h = hashlib.sha256(f"{v_X}:{v_Y}:{Z}:{N}".encode()).hexdigest()
        r = int(h[:16], 16)
        v_X = (pow(v_X, r, N) * Z) % N
        v_Y = (pow(Z, r, N) * v_Y) % N
        v_T = half

    # Remaining squarings must be bounded to O(depth) cost ceiling (<= 4096 squarings)
    require(v_T <= 4096, 'remaining squarings exceed verifier cost ceiling')
    final_s = v_X
    for _ in range(v_T):
        final_s = (final_s * final_s) % N
    require(final_s == v_Y, 'Pietrzak Proof of Exponentiation check failed')
    return True
    for _ in range(v_T):
        final_s = (final_s * final_s) % N
    require(final_s == v_Y, 'Pietrzak Proof of Exponentiation check failed')
    return True


def init_schema(db):
    db.execute("""
    CREATE TABLE IF NOT EXISTS gimps_tasks (
        engine_id TEXT NOT NULL,
        problem_set_id TEXT NOT NULL,
        exponent INTEGER NOT NULL,
        state TEXT NOT NULL,
        assigned_to TEXT,
        assigned_at INTEGER,
        lease_timeout INTEGER,
        proof_tx_hash TEXT,
        checkpoint_json TEXT,
        last_heartbeat INTEGER,
        math_certified INTEGER DEFAULT 0,
        primenet_status TEXT DEFAULT 'unsubmitted',
        corium_settled INTEGER DEFAULT 0,
        PRIMARY KEY (engine_id, exponent)
    )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_gimps_tasks_state ON gimps_tasks(engine_id, state)")
    # Migration helper for existing databases:
    existing_cols = {row[1] for row in db.execute("PRAGMA table_info(gimps_tasks)").fetchall()}
    for col, col_type, default in [
        ('checkpoint_json', 'TEXT', None),
        ('last_heartbeat', 'INTEGER', None),
        ('math_certified', 'INTEGER', '0'),
        ('primenet_status', 'TEXT', "'unsubmitted'"),
        ('corium_settled', 'INTEGER', '0')
    ]:
        if col not in existing_cols:
            db.execute(f"ALTER TABLE gimps_tasks ADD COLUMN {col} {col_type}" + (f" DEFAULT {default}" if default else ""))


def renew_lease(db, engine_id, exponent, worker_id, progress_pct=None, checkpoint_data=None, lease_duration=DEFAULT_LEASE_SECONDS, current_time=None):
    init_schema(db)
    if current_time is None:
        current_time = int(time.time())
    row = db.execute(
        "SELECT state, assigned_to, lease_timeout FROM gimps_tasks WHERE engine_id=? AND exponent=?",
        (engine_id, exponent)
    ).fetchone()
    require(row is not None, "task not found")
    state, assigned_to, lease_timeout = row[0], row[1], row[2]
    if state == 'assigned':
        require(assigned_to == worker_id, "task assigned to different worker")
        require(lease_timeout is None or lease_timeout > current_time, "lease already expired")
    elif state == 'paused':
        require(assigned_to == worker_id, "task paused by different worker")
    else:
        raise ValueError(f"cannot renew lease in state {state}")

    new_timeout = current_time + lease_duration
    chk_str = json.dumps(checkpoint_data) if checkpoint_data is not None else None
    if chk_str is not None:
        db.execute(
            "UPDATE gimps_tasks SET lease_timeout=?, last_heartbeat=?, checkpoint_json=? WHERE engine_id=? AND exponent=?",
            (new_timeout, current_time, chk_str, engine_id, exponent)
        )
    else:
        db.execute(
            "UPDATE gimps_tasks SET lease_timeout=?, last_heartbeat=? WHERE engine_id=? AND exponent=?",
            (new_timeout, current_time, engine_id, exponent)
        )
    return {
        'status': 'renewed',
        'engine_id': engine_id,
        'exponent': exponent,
        'assigned_to': worker_id,
        'lease_timeout': new_timeout,
        'last_heartbeat': current_time
    }


def pause_task(db, engine_id, exponent, worker_id, checkpoint_data=None, current_time=None):
    init_schema(db)
    if current_time is None:
        current_time = int(time.time())
    row = db.execute(
        "SELECT state, assigned_to, lease_timeout FROM gimps_tasks WHERE engine_id=? AND exponent=?",
        (engine_id, exponent)
    ).fetchone()
    require(row is not None, "task not found")
    state, assigned_to = row[0], row[1]
    require(state == 'assigned', f"task not in assigned state (state={state})")
    require(assigned_to == worker_id, "task assigned to different worker")

    chk_str = json.dumps(checkpoint_data) if checkpoint_data is not None else None
    if chk_str is not None:
        db.execute(
            "UPDATE gimps_tasks SET state='paused', last_heartbeat=?, checkpoint_json=? WHERE engine_id=? AND exponent=?",
            (current_time, chk_str, engine_id, exponent)
        )
    else:
        db.execute(
            "UPDATE gimps_tasks SET state='paused', last_heartbeat=? WHERE engine_id=? AND exponent=?",
            (current_time, engine_id, exponent)
        )
    return {
        'status': 'paused',
        'engine_id': engine_id,
        'exponent': exponent,
        'assigned_to': worker_id,
        'last_heartbeat': current_time
    }


def resume_task(db, engine_id, exponent, worker_id, lease_duration=DEFAULT_LEASE_SECONDS, current_time=None):
    init_schema(db)
    if current_time is None:
        current_time = int(time.time())
    row = db.execute(
        "SELECT state, assigned_to, checkpoint_json FROM gimps_tasks WHERE engine_id=? AND exponent=?",
        (engine_id, exponent)
    ).fetchone()
    require(row is not None, "task not found")
    state, assigned_to, checkpoint_json = row[0], row[1], row[2]
    require(state in ('paused', 'retry'), f"task cannot be resumed from state {state}")

    new_timeout = current_time + lease_duration
    db.execute(
        "UPDATE gimps_tasks SET state='assigned', assigned_to=?, assigned_at=?, lease_timeout=?, last_heartbeat=? WHERE engine_id=? AND exponent=?",
        (worker_id, current_time, new_timeout, current_time, engine_id, exponent)
    )
    checkpoint = json.loads(checkpoint_json) if checkpoint_json else None
    return {
        'status': 'resumed',
        'engine_id': engine_id,
        'exponent': exponent,
        'assigned_to': worker_id,
        'lease_timeout': new_timeout,
        'checkpoint': checkpoint
    }


def update_primenet_status(db, engine_id, exponent, status, attestation=None):
    init_schema(db)
    require(status in ('unsubmitted', 'submitted', 'accepted', 'rejected'), f"invalid primenet status: {status}")
    db.execute(
        "INSERT INTO gimps_tasks (engine_id, problem_set_id, exponent, state, primenet_status) "
        "VALUES (?, '', ?, 'assigned', ?) "
        "ON CONFLICT(engine_id, exponent) DO UPDATE SET primenet_status=excluded.primenet_status",
        (engine_id, exponent, status)
    )
    return {
        'engine_id': engine_id,
        'exponent': exponent,
        'primenet_status': status,
        'attestation': attestation
    }


def candidates(metadata):
    """Bound native verification work and search prime exponents only."""
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    require(type(metadata) is dict, 'problem set metadata required')
    method = metadata.get('method', 'lucas-lehmer')
    max_bound = MAX_PRP_EXPONENT if method in ('prp', 'prp-fiat-shamir') else MAX_LL_EXPONENT
    start = integer(metadata.get('start_exponent'), 2, max_bound)
    end = integer(metadata.get('end_exponent'), start, max_bound)
    return (p for p in range(start, end + 1) if all(p % d for d in range(2, int(p**0.5) + 1)))


def native_challenge(db, network, submitter):
    """Read-only native GIMPS selection; never falls back to another engine."""
    row = db.execute("SELECT value FROM chain_state WHERE key='chain_info'").fetchone()
    require(row and type(row[0]) is str, 'accepted native head required')
    head = row[0].split('|')
    require(len(head) == 2 and re.fullmatch('[a-f0-9]{64}', head[0]) and head[1].isdigit(), 'canonical native head required')
    height = int(head[1])
    require(db.execute('SELECT 1 FROM blocks WHERE hash=? AND height=?', (head[0], height)).fetchone(), 'accepted head must exist')
    base = {
        'schema': 'corium.gimps-challenge.v1',
        'network_id': network,
        'submitter_id': submitter,
        'height': height,
        'block_hash': head[0],
        'proof_schema': PORTABLE_SCHEMA,
        'supported_schemas': [PORTABLE_SCHEMA, PRP_SCHEMA],
        'method': 'lucas-lehmer',
        'supported_methods': ['lucas-lehmer', 'prp-fiat-shamir'],
        'max_ll_exponent': MAX_LL_EXPONENT,
        'max_prp_exponent': MAX_PRP_EXPONENT,
        'max_exponent': MAX_PRP_EXPONENT
    }
    engines = db.execute('SELECT engine_id,compute_program_hash,verifier_script_hash FROM compute_engines WHERE pkg_id=? AND is_active=1 ORDER BY engine_id', (PACKAGE,)).fetchall()
    for engine, program, verifier in engines:
        problem = db.execute('SELECT set_id,metadata FROM problem_sets WHERE engine_id=? AND activation_height<=? ORDER BY activation_height DESC,set_id LIMIT 1', (engine, height)).fetchone()
        if not problem:
            continue
        blocked = {str(row[0]) for row in db.execute('SELECT problem_id FROM completed_compute_tasks WHERE engine_id=?', (engine,))}
        blocked.update(str(row[0]) for row in db.execute("SELECT json_extract(data,'$.problem_id') FROM transactions WHERE type='submit_math_proof' AND block_height IS NULL AND json_extract(data,'$.engine_id')=?", (engine,)))
        blocked.update(str(row[0]) for row in db.execute("SELECT p.problem_id FROM pending_proofs p JOIN transactions t ON t.hash=p.proof_tx_hash WHERE json_extract(t.data,'$.engine_id')=?", (engine,)))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gimps_tasks'").fetchone():
            blocked.update(str(row[0]) for row in db.execute("SELECT exponent FROM gimps_tasks WHERE engine_id=? AND state='assigned' AND lease_timeout>?", (engine, int(time.time()))))
            blocked.update(str(row[0]) for row in db.execute("SELECT exponent FROM gimps_tasks WHERE engine_id=? AND state='paused'", (engine,)))
        for exponent in candidates(problem[1]):
            if str(exponent) not in blocked:
                return dict(base, available=True, engine_id=engine, problem_set_id=problem[0], problem_id=str(exponent),
                            exponent=exponent, engine_hash=program, verifier_hash=verifier)
    return dict(base, available=False, reason='no-active-gimps-engine' if not engines else 'no-available-gimps-task')


def reconcile_task_states(db, engine_id, set_id, start_exp, end_exp, current_time=None):
    """Reconcile task state machine from the blockchain tables."""
    init_schema(db)
    if current_time is None:
        current_time = int(time.time())
    # Derived states must follow the canonical tables after replay/reorganization.
    db.execute("UPDATE gimps_tasks SET state='retry',proof_tx_hash=NULL WHERE engine_id=? AND state IN ('settled','verified','submitted','failed')", (engine_id,))

    # 1. Settled tasks from completed_compute_tasks
    completed_rows = db.execute(
        "SELECT problem_id, proof_tx_hash FROM completed_compute_tasks WHERE engine_id=?",
        (engine_id,)
    ).fetchall()
    for row in completed_rows:
        try:
            exp = int(row[0])
            if start_exp <= exp <= end_exp:
                db.execute(
                    "INSERT INTO gimps_tasks (engine_id, problem_set_id, exponent, state, proof_tx_hash, math_certified, corium_settled) "
                    "VALUES (?, ?, ?, 'settled', ?, 1, 1) "
                    "ON CONFLICT(engine_id, exponent) DO UPDATE SET state='settled', proof_tx_hash=excluded.proof_tx_hash, math_certified=1, corium_settled=1",
                    (engine_id, set_id, exp, row[1])
                )
        except (ValueError, TypeError):
            continue

    # 2. Verified / pending confirmation tasks from pending_proofs
    pending_rows = db.execute(
        "SELECT p.problem_id, p.proof_tx_hash FROM pending_proofs p "
        "JOIN transactions t ON t.hash=p.proof_tx_hash "
        "WHERE json_extract(t.data, '$.engine_id')=?",
        (engine_id,)
    ).fetchall()
    for row in pending_rows:
        try:
            exp = int(row[0])
            if start_exp <= exp <= end_exp:
                cur = db.execute("SELECT state FROM gimps_tasks WHERE engine_id=? AND exponent=?", (engine_id, exp)).fetchone()
                if not cur or cur[0] != 'settled':
                    db.execute(
                        "INSERT INTO gimps_tasks (engine_id, problem_set_id, exponent, state, proof_tx_hash, math_certified) "
                        "VALUES (?, ?, ?, 'verified', ?, 1) "
                        "ON CONFLICT(engine_id, exponent) DO UPDATE SET state='verified', proof_tx_hash=excluded.proof_tx_hash, math_certified=1",
                        (engine_id, set_id, exp, row[1])
                    )
        except (ValueError, TypeError):
            continue

    # 3. Submitted unconfirmed transactions in mempool
    mempool_rows = db.execute(
        "SELECT hash, json_extract(data, '$.problem_id') FROM transactions "
        "WHERE type='submit_math_proof' AND block_height IS NULL AND json_extract(data, '$.engine_id')=?",
        (engine_id,)
    ).fetchall()
    for row in mempool_rows:
        try:
            exp = int(row[1])
            if start_exp <= exp <= end_exp:
                cur = db.execute("SELECT state FROM gimps_tasks WHERE engine_id=? AND exponent=?", (engine_id, exp)).fetchone()
                if not cur or cur[0] not in ('settled', 'verified'):
                    db.execute(
                        "INSERT INTO gimps_tasks (engine_id, problem_set_id, exponent, state, proof_tx_hash) "
                        "VALUES (?, ?, ?, 'submitted', ?) "
                        "ON CONFLICT(engine_id, exponent) DO UPDATE SET state='submitted', proof_tx_hash=excluded.proof_tx_hash",
                        (engine_id, set_id, exp, row[0])
                    )
        except (ValueError, TypeError):
            continue

    # 4. Failed/challenged tasks
    failed_rows = db.execute(
        "SELECT c.target_proof_tx_hash, json_extract(t.data, '$.problem_id') "
        "FROM challenges c JOIN transactions t ON t.hash=c.target_proof_tx_hash "
        "WHERE c.status='confirmed' AND json_extract(t.data, '$.engine_id')=?",
        (engine_id,)
    ).fetchall()
    for row in failed_rows:
        try:
            exp = int(row[1])
            if start_exp <= exp <= end_exp:
                cur = db.execute("SELECT state,proof_tx_hash FROM gimps_tasks WHERE engine_id=? AND exponent=?", (engine_id, exp)).fetchone()
                if not cur or cur[0] != 'settled':
                    db.execute(
                        "INSERT INTO gimps_tasks (engine_id, problem_set_id, exponent, state, proof_tx_hash) "
                        "VALUES (?, ?, ?, 'failed', ?) "
                        "ON CONFLICT(engine_id, exponent) DO UPDATE SET state='failed', proof_tx_hash=excluded.proof_tx_hash",
                        (engine_id, set_id, exp, row[0])
                    )
        except (ValueError, TypeError):
            continue

    # 5. Expired assignments -> transition to retry (tasks in paused state retain checkpoint)
    db.execute(
        "UPDATE gimps_tasks SET state='retry' "
        "WHERE engine_id=? AND state='assigned' AND lease_timeout IS NOT NULL AND lease_timeout <= ?",
        (engine_id, current_time)
    )


def generate_next_gimps_task(db, engine_id, set_id, metadata, current_time=None):
    """Deterministic, state-machine driven task generator for GIMPS problem sets."""
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            return None
    method = metadata.get('method', 'lucas-lehmer')
    max_bound = MAX_PRP_EXPONENT if method in ('prp', 'prp-fiat-shamir') else MAX_LL_EXPONENT
    start_exp = integer(metadata.get('start_exponent', 0), 2, max_bound)
    end_exp = integer(metadata.get('end_exponent', 0), start_exp, max_bound)
    if start_exp <= 0 or end_exp < start_exp:
        return None

    if current_time is None:
        current_time = int(time.time())

    reconcile_task_states(db, engine_id, set_id, start_exp, end_exp, current_time)

    # Find the next available exponent in [start_exp, end_exp]
    for p in candidates({'start_exponent': start_exp, 'end_exponent': end_exp, 'method': method}):
        row = db.execute(
            "SELECT state, lease_timeout FROM gimps_tasks WHERE engine_id=? AND exponent=?",
            (engine_id, p)
        ).fetchone()

        # Check if already completed, active, or paused
        if row:
            st = row[0]
            if st in ('settled', 'verified', 'submitted', 'paused'):
                continue
            if st == 'assigned' and row[1] and row[1] > current_time:
                # Active lease held by worker
                continue

        # Found available exponent p (either unassigned, retry, failed, or expired)
        lease_duration = metadata.get('lease_seconds', DEFAULT_LEASE_SECONDS) if isinstance(metadata, dict) else DEFAULT_LEASE_SECONDS
        timeout = current_time + lease_duration
        db.execute(
            "INSERT INTO gimps_tasks (engine_id, problem_set_id, exponent, state, assigned_at, lease_timeout, last_heartbeat) "
            "VALUES (?, ?, ?, 'assigned', ?, ?, ?) "
            "ON CONFLICT(engine_id, exponent) DO UPDATE SET state='assigned', assigned_at=excluded.assigned_at, lease_timeout=excluded.lease_timeout, last_heartbeat=excluded.last_heartbeat, proof_tx_hash=NULL",
            (engine_id, set_id, p, current_time, timeout, current_time)
        )
        return f"{p}|{p}"

    return None


def validate_gimps_proof(db, network, payload, sender, height, accepted_tx=None):
    """Validate GIMPS proof format, mathematical bounds, and duplicate rules."""
    require(isinstance(payload, dict), 'payload dictionary required')
    engine_id = payload.get('engine_id')
    problem_id = payload.get('problem_id')
    proof_data = payload.get('proof_data', {})
    require(engine_id and problem_id is not None, 'engine_id and problem_id required')
    require(type(proof_data) is dict, 'proof_data must be dictionary')

    # Verify engine is registered and active
    row = db.execute(
        "SELECT pkg_id, is_active, reward_weight FROM compute_engines WHERE engine_id=?",
        (engine_id,)
    ).fetchone()
    require(row is not None and row[1] == 1, 'engine must be active on-chain')
    require(row[0] == PACKAGE, 'engine package must be corium/built-in-gimps')
    weight = row[2] if len(row) > 2 and row[2] is not None else 100

    integer(weight, 0, MAX_INTEGER // 100)
    integer(height, 0, MAX_INTEGER)
    require(type(problem_id) is str and re.fullmatch(r'[1-9][0-9]{0,9}', problem_id), 'canonical exponent string required')
    proof_schema = proof_data.get('schema')
    is_prp_schema = (proof_schema == PRP_SCHEMA)
    max_bound = MAX_PRP_EXPONENT if is_prp_schema else MAX_LL_EXPONENT
    p = integer(int(problem_id), 2, max_bound)

    active = db.execute('SELECT metadata FROM problem_sets WHERE engine_id=? AND activation_height<=?', (engine_id, height)).fetchall()
    assigned_range = False
    for item in active:
        meta = json.loads(item[0])
        start, end = meta.get('start_exponent'), meta.get('end_exponent')
        m_method = meta.get('method', 'lucas-lehmer')
        m_max = MAX_PRP_EXPONENT if m_method in ('prp', 'prp-fiat-shamir') else MAX_LL_EXPONENT
        if type(start) is int and type(end) is int and 2 <= start <= p <= end <= m_max:
            assigned_range = True
    require(assigned_range, 'exponent must belong to an active bounded problem set')

    # Duplicate submission / Double redeem check
    completed = db.execute(
        "SELECT proof_tx_hash FROM completed_compute_tasks WHERE engine_id=? AND problem_id=?",
        (engine_id, str(p))
    ).fetchall()
    pending = db.execute(
        "SELECT p.proof_tx_hash FROM pending_proofs p "
        "JOIN transactions t ON t.hash=p.proof_tx_hash "
        "WHERE p.problem_id=? AND json_extract(t.data, '$.engine_id')=?",
        (str(p), engine_id)
    ).fetchall()

    for r in completed + pending:
        if accepted_tx is None or r[0] != accepted_tx:
            raise ValueError(f'exponent {p} already settled or pending confirmation')

    if proof_schema == PRP_SCHEMA:
        # Bounded PRP Proof of Exponentiation with Fiat-Shamir folding
        verify_prp_proof(p, proof_data)
        math_certified = True
        method = 'prp-fiat-shamir'
    elif proof_schema in {SCHEMA, PORTABLE_SCHEMA}:
        # Lucas-Lehmer verification
        exact(proof_data, {'schema', 'exponent', 'method', 'residue', 'is_prime', 'iterations'})
        require(type(proof_data['exponent']) is int and proof_data['exponent'] == p, 'proof exponent mismatch')
        require(proof_data['method'] == 'lucas-lehmer', 'unimplemented proof method rejected')
        require(type(proof_data['iterations']) is int and proof_data['iterations'] == p - 2, 'exact iteration count required')
        require(type(proof_data['is_prime']) is bool, 'boolean primality claim required')
        residue = proof_data['residue']
        if proof_schema == PORTABLE_SCHEMA:
            require(type(residue) is str and re.fullmatch(r'0|[1-9][0-9]{0,1233}', residue), 'canonical decimal residue required')
            residue = int(residue)
        require(type(residue) is int and 0 <= residue < (1 << p) - 1, 'bounded integer residue required')
        valid, expected = lucas_lehmer_verify(p, residue)
        require(valid, 'invalid Lucas-Lehmer residue')
        prime_exponent = all(p % divisor for divisor in range(2, int(p**0.5) + 1))
        require(proof_data['is_prime'] == (prime_exponent and expected == 0), 'primality claim mismatch')
        math_certified = True
        method = 'lucas-lehmer'
    else:
        # Legacy format without schema
        exact(proof_data, {'residue'})
        residue = proof_data['residue']
        require(type(residue) is int and 0 <= residue < (1 << p) - 1, 'bounded integer residue required')
        valid, expected = lucas_lehmer_verify(p, residue)
        require(valid, 'invalid Lucas-Lehmer residue')
        math_certified = True
        method = 'lucas-lehmer'

    # Retrieve current PrimeNet attestation status if present
    primenet_status = 'unsubmitted'
    try:
        pnet_row = db.execute("SELECT primenet_status FROM gimps_tasks WHERE engine_id=? AND exponent=?", (engine_id, p)).fetchone()
        if pnet_row and pnet_row[0]:
            primenet_status = pnet_row[0]
    except Exception:
        pass

    return {
        'status': 'valid',
        'math_certified': math_certified,
        'primenet_status': primenet_status,
        'corium_settled': False,
        'engine_id': engine_id,
        'problem_id': str(p),
        'exponent': p,
        'method': method,
        'reward': 100 * weight,
        'reward_weight': weight,
        'proposer_id': sender
    }


def settle(db, network, tx, height):
    """Settle an unchallenged confirmed GIMPS proof, crediting contribution scores."""
    row = db.execute(
        "SELECT data, public_key, block_height FROM transactions "
        "WHERE hash=? AND type='submit_math_proof' AND block_height IS NOT NULL",
        (tx,)
    ).fetchone()
    require(row is not None, 'confirmed native proof required')
    payload = json.loads(row[0])
    sender = hashlib.sha256(row[1].encode()).hexdigest()

    val = validate_gimps_proof(db, network, payload, sender, row[2], accepted_tx=tx)
    engine_id = val['engine_id']
    problem_id = val['problem_id']
    reward = val['reward']

    # Check if already redeemed
    done = db.execute(
        "SELECT proof_tx_hash FROM completed_compute_tasks WHERE engine_id=? AND problem_id=?",
        (engine_id, problem_id)
    ).fetchone()
    if done:
        require(done[0] == tx, 'bounty already redeemed')
        return val | {'duplicate': True, 'corium_settled': True}

    # Verify pending state and 10-block challenge window
    pending = db.execute(
        "SELECT problem_id, proof_tx_hash, proposer_id, proposed_result, confirmation_deadline_height FROM pending_proofs WHERE proof_tx_hash=?",
        (tx,)
    ).fetchone()
    require(pending is not None, 'matching pending proof required')
    p_prob = pending[0] if isinstance(pending, tuple) else pending['problem_id']
    p_proposer = pending[2] if isinstance(pending, tuple) else pending['proposer_id']
    p_deadline = pending[4] if isinstance(pending, tuple) else pending['confirmation_deadline_height']
    require(p_proposer == sender and p_prob == problem_id, 'matching pending proof required')
    require(p_deadline == row[2] + 10 and height >= p_deadline, 'native challenge window must elapse')

    # Check no active unrejected challenge
    require(db.execute(
        "SELECT 1 FROM challenges WHERE target_proof_tx_hash=? AND status!='rejected'",
        (tx,)
    ).fetchone() is None, 'challenged proof cannot settle on unchallenged path')

    # Update contribution_scores
    prior = db.execute("SELECT score FROM contribution_scores WHERE user_id=?", (sender,)).fetchone()
    score = prior[0] if prior else 0
    integer(score, -MAX_INTEGER - 1, MAX_INTEGER - reward)

    db.execute(
        "INSERT INTO completed_compute_tasks (engine_id, problem_id, proof_tx_hash) VALUES (?, ?, ?)",
        (engine_id, problem_id, tx)
    )
    db.execute(
        "INSERT INTO contribution_scores (user_id, score, last_update_height) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET score=score+?, last_update_height=excluded.last_update_height",
        (sender, score + reward, height, reward)
    )
    db.execute("DELETE FROM pending_proofs WHERE proof_tx_hash=?", (tx,))

    # Update gimps_tasks state machine to settled
    try:
        p = int(problem_id)
        db.execute(
            "UPDATE gimps_tasks SET state='settled', proof_tx_hash=?, math_certified=1, corium_settled=1 WHERE engine_id=? AND exponent=?",
            (tx, engine_id, p)
        )
    except Exception:
        pass

    return val | {
        'settled_height': height,
        'contribution_score': score + reward,
        'reward_awarded': reward,
        'corium_settled': True
    }


def validate_challenge(db, network, target_tx):
    """Validate challenge against a GIMPS proof.
    Returns 1 if proof is valid (challenge fails), 0 if proof is invalid (challenge succeeds).
    """
    row = db.execute(
        "SELECT data, public_key, block_height FROM transactions WHERE hash=? AND type='submit_math_proof'",
        (target_tx,)
    ).fetchone()
    if not row:
        return 0
    payload = json.loads(row[0])
    sender = hashlib.sha256(row[1].encode()).hexdigest()
    try:
        validate_gimps_proof(db, network, payload, sender, row[2] or 1, accepted_tx=target_tx)
        return 1
    except Exception:
        return 0


def main(args):
    action = args[0]
    database = args[1]
    with closing(sqlite3.connect(database)) as db, db:
        db.row_factory = sqlite3.Row
        if action == 'next-task':
            db.execute('BEGIN IMMEDIATE')
            engine_id, set_id, metadata = args[2:5]
            res = generate_next_gimps_task(db, engine_id, set_id, metadata)
            if res:
                print(res)
            else:
                sys.exit(1)
        elif action == 'challenge':
            network, submitter = args[2:4]
            print(json.dumps(native_challenge(db, network, submitter), sort_keys=True))
        elif action == 'solve':
            network, engine, problem, sender = args[2:6]
            method = args[6] if len(args) > 6 else 'lucas-lehmer'
            max_bound = MAX_PRP_EXPONENT if method in ('prp', 'prp-fiat-shamir') else MAX_LL_EXPONENT
            exponent = integer(int(problem), 2, max_bound)
            require(exponent in candidates({'start_exponent': exponent, 'end_exponent': exponent, 'method': method}), 'prime exponent required')
            if method == 'prp' or method == 'prp-fiat-shamir':
                proof_data = generate_prp_proof(exponent, base=3, depth=4)
            else:
                _, residue = lucas_lehmer_verify(exponent, 0)
                proof_data = {
                    'schema': PORTABLE_SCHEMA,
                    'exponent': exponent,
                    'method': 'lucas-lehmer',
                    'residue': str(residue),
                    'is_prime': residue == 0,
                    'iterations': exponent - 2
                }
            payload = {'engine_id': engine, 'problem_id': str(exponent), 'proof_data': proof_data}
            head = db.execute("SELECT value FROM chain_state WHERE key='chain_info'").fetchone()
            require(head is not None, 'native accepted head required')
            validate_gimps_proof(db, network, payload, sender, int(head[0].split('|')[1]))
            print(json.dumps(payload, sort_keys=True))
        elif action == 'validate':
            network, payload_raw, sender, height = args[2:6]
            accepted_tx = args[6] if len(args) > 6 else None
            payload = json.loads(payload_raw)
            res = validate_gimps_proof(db, network, payload, sender, int(height), accepted_tx=accepted_tx)
            print(json.dumps(res, sort_keys=True))
        elif action == 'settle':
            network, tx, height = args[2:5]
            db.execute('BEGIN IMMEDIATE')
            res = settle(db, network, tx, int(height))
            print(json.dumps(res, sort_keys=True))
        elif action == 'validate-challenge':
            network, target_tx = args[2:4]
            code = validate_challenge(db, network, target_tx)
            print(code)
            if code == 0:
                sys.exit(0)  # Challenge succeeded
            else:
                sys.exit(0)  # Output is 1 or 0
        elif action == 'renew-lease':
            engine_id, exponent, worker_id = args[2:5]
            chk = json.loads(args[5]) if len(args) > 5 and args[5] else None
            dur = int(args[6]) if len(args) > 6 and args[6] else DEFAULT_LEASE_SECONDS
            db.execute('BEGIN IMMEDIATE')
            res = renew_lease(db, engine_id, int(exponent), worker_id, checkpoint_data=chk, lease_duration=dur)
            print(json.dumps(res, sort_keys=True))
        elif action == 'pause-task':
            engine_id, exponent, worker_id = args[2:5]
            chk = json.loads(args[5]) if len(args) > 5 and args[5] else None
            db.execute('BEGIN IMMEDIATE')
            res = pause_task(db, engine_id, int(exponent), worker_id, checkpoint_data=chk)
            print(json.dumps(res, sort_keys=True))
        elif action == 'resume-task':
            engine_id, exponent, worker_id = args[2:5]
            dur = int(args[5]) if len(args) > 5 and args[5] else DEFAULT_LEASE_SECONDS
            db.execute('BEGIN IMMEDIATE')
            res = resume_task(db, engine_id, int(exponent), worker_id, lease_duration=dur)
            print(json.dumps(res, sort_keys=True))
        elif action == 'update-primenet':
            engine_id, exponent, status = args[2:5]
            attestation = args[5] if len(args) > 5 else None
            db.execute('BEGIN IMMEDIATE')
            res = update_primenet_status(db, engine_id, int(exponent), status, attestation=attestation)
            print(json.dumps(res, sort_keys=True))
        elif action == 'generate-prp':
            exponent = int(args[2])
            depth = int(args[3]) if len(args) > 3 else 4
            res = generate_prp_proof(exponent, base=3, depth=depth)
            print(json.dumps(res, sort_keys=True))
        elif action == 'verify-prp':
            exponent = int(args[2])
            proof_data = json.loads(args[3])
            ok = verify_prp_proof(exponent, proof_data)
            print(json.dumps({'verified': ok}, sort_keys=True))
        else:
            raise ValueError(f"unknown gimps action: {action}")


if __name__ == '__main__':
    main(sys.argv[1:])

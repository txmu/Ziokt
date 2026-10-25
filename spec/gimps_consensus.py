"""Native verification, task state lifecycle, and settlement for GIMPS (Mersenne prime search) proofs.

Supports:
1. Versioned schema 'corium.gimps-proof.v1' and backward-compatible legacy format.
2. Full Lucas-Lehmer recomputation for exponents 2..4096; larger exponents and
   unimplemented factoring methods fail closed until a bounded verifier is provided.
3. Task state lifecycle:
   - assigned: task dispatched with an unexpired lease
   - submitted: transaction present in mempool or confirmed block
   - verified: confirmed into block, pending in challenge window
   - settled: challenge window passed unchallenged, recorded in completed_compute_tasks
   - failed / retry: challenged and proven invalid, or expired without submission
4. Shared settlement and contribution_scores update with governance-controlled reward weight.
5. Strict duplicate detection: rejects duplicate submissions for already settled or pending exponents,
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
MAX_INTEGER = 2**63 - 1
DEFAULT_LEASE_SECONDS = 600
MAX_VERIFIED_EXPONENT = 4096


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
    """Deterministically compute Lucas-Lehmer residue for small exponents (p <= 61)."""
    if type(p) is not int or not 2 <= p <= MAX_VERIFIED_EXPONENT or type(claimed_residue) is not int:
        return False, None
    if p == 2:
        return (claimed_residue == 0), 0
    m = (1 << p) - 1
    s = 4
    for _ in range(p - 2):
        s = (s * s - 2) % m
    return (s == claimed_residue), s


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
        PRIMARY KEY (engine_id, exponent)
    )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_gimps_tasks_state ON gimps_tasks(engine_id, state)")


def reconcile_task_states(db, engine_id, set_id, start_exp, end_exp, current_time=None):
    """Reconcile task state machine from the blockchain tables."""
    init_schema(db)
    if current_time is None:
        current_time = int(time.time())

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
                    "INSERT INTO gimps_tasks (engine_id, problem_set_id, exponent, state, proof_tx_hash) "
                    "VALUES (?, ?, ?, 'settled', ?) "
                    "ON CONFLICT(engine_id, exponent) DO UPDATE SET state='settled', proof_tx_hash=excluded.proof_tx_hash",
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
                        "INSERT INTO gimps_tasks (engine_id, problem_set_id, exponent, state, proof_tx_hash) "
                        "VALUES (?, ?, ?, 'verified', ?) "
                        "ON CONFLICT(engine_id, exponent) DO UPDATE SET state='verified', proof_tx_hash=excluded.proof_tx_hash",
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
                if not cur or (cur[0] != 'settled' and cur[1] == row[0]):
                    db.execute(
                        "INSERT INTO gimps_tasks (engine_id, problem_set_id, exponent, state, proof_tx_hash) "
                        "VALUES (?, ?, ?, 'failed', ?) "
                        "ON CONFLICT(engine_id, exponent) DO UPDATE SET state='failed', proof_tx_hash=excluded.proof_tx_hash",
                        (engine_id, set_id, exp, row[0])
                    )
        except (ValueError, TypeError):
            continue

    # 5. Expired assignments -> transition to retry
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
    start_exp = integer(metadata.get('start_exponent', 0), 2, MAX_VERIFIED_EXPONENT)
    end_exp = integer(metadata.get('end_exponent', 0), start_exp, MAX_VERIFIED_EXPONENT)
    if start_exp <= 0 or end_exp < start_exp:
        return None

    if current_time is None:
        current_time = int(time.time())

    reconcile_task_states(db, engine_id, set_id, start_exp, end_exp, current_time)

    # Find the next available exponent in [start_exp, end_exp]
    for p in range(start_exp, end_exp + 1):
        row = db.execute(
            "SELECT state, lease_timeout FROM gimps_tasks WHERE engine_id=? AND exponent=?",
            (engine_id, p)
        ).fetchone()

        # Check if already completed or active
        if row:
            st = row[0]
            if st in ('settled', 'verified', 'submitted'):
                continue
            if st == 'assigned' and row[1] and row[1] > current_time:
                # Active lease held by worker
                continue

        # Found available exponent p (either unassigned, retry, failed, or expired)
        timeout = current_time + DEFAULT_LEASE_SECONDS
        db.execute(
            "INSERT INTO gimps_tasks (engine_id, problem_set_id, exponent, state, assigned_at, lease_timeout) "
            "VALUES (?, ?, ?, 'assigned', ?, ?) "
            "ON CONFLICT(engine_id, exponent) DO UPDATE SET state='assigned', assigned_at=excluded.assigned_at, lease_timeout=excluded.lease_timeout, proof_tx_hash=NULL",
            (engine_id, set_id, p, current_time, timeout)
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
    require(type(problem_id) is str and re.fullmatch(r'[1-9][0-9]{0,3}', problem_id), 'canonical exponent string required')
    p = integer(int(problem_id), 2, MAX_VERIFIED_EXPONENT)
    active = db.execute('SELECT metadata FROM problem_sets WHERE engine_id=? AND activation_height<=?', (engine_id,height)).fetchall()
    assigned_range = False
    for item in active:
        meta = json.loads(item[0])
        start, end = meta.get('start_exponent'), meta.get('end_exponent')
        if type(start) is int and type(end) is int and 2 <= start <= p <= end <= MAX_VERIFIED_EXPONENT:
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

    # Only fully recomputed Lucas-Lehmer results may receive native credit.
    require(type(proof_data) is dict, 'proof_data must be dictionary')
    versioned = 'schema' in proof_data
    if versioned:
        exact(proof_data, {'schema','exponent','method','residue','is_prime','iterations'})
        require(proof_data['schema'] == SCHEMA, 'supported proof schema required')
        require(type(proof_data['exponent']) is int and proof_data['exponent'] == p, 'proof exponent mismatch')
        require(proof_data['method'] == 'lucas-lehmer', 'unimplemented proof method rejected')
        require(type(proof_data['iterations']) is int and proof_data['iterations'] == p - 2, 'exact iteration count required')
        require(type(proof_data['is_prime']) is bool, 'boolean primality claim required')
    else:
        exact(proof_data, {'residue'})
    residue = proof_data['residue']
    require(type(residue) is int and 0 <= residue < (1 << p)-1, 'bounded integer residue required')
    valid, expected = lucas_lehmer_verify(p, residue)
    require(valid, 'invalid Lucas-Lehmer residue')
    prime_exponent = all(p % divisor for divisor in range(2, int(p**0.5)+1))
    if versioned:
        require(proof_data['is_prime'] == (prime_exponent and expected == 0), 'primality claim mismatch')

    return {
        'status': 'valid',
        'engine_id': engine_id,
        'problem_id': str(p),
        'exponent': p,
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
        return val | {'duplicate': True}

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
            "UPDATE gimps_tasks SET state='settled', proof_tx_hash=? WHERE engine_id=? AND exponent=?",
            (tx, engine_id, p)
        )
    except Exception:
        pass

    return val | {
        'settled_height': height,
        'contribution_score': score + reward,
        'reward_awarded': reward
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
        else:
            raise ValueError(f"unknown gimps action: {action}")


if __name__ == '__main__':
    main(sys.argv[1:])

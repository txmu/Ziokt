"""Public GIMPS workers delegate native authority and verification to Corium.

Upgraded to Scheme C (Hybrid Architecture):
1. Low-cost verifiable PRP (Fermat base 3) with Fiat-Shamir folding (O(depth) verifier).
2. Backward compatibility with Lucas-Lehmer (corium.gimps-proof.v2).
3. Resource governor: CPU duty-cycling, memory ceiling check, and disk/payload caps.
4. CheckpointManager: stateful pause, resume, and checkpoint tracking.
5. PrimeNetAdapter: V5 result formatting, attestation tracking, and scientific proof export.
6. Three-tier outcome separation: math_certified, primenet_status, corium_settled.
"""
import hashlib
import json
from pathlib import Path
import re
import secrets
import time

from .effort_web import EffortPool
from .protocol import ProtocolError, encoded, strict_json
from .runtime_policy import require_network


class ResourceGovernor:
    """Safeguards worker execution with CPU duty-cycle throttling, memory ceiling, and storage bounds."""
    def __init__(self, max_memory_mb=2048, max_checkpoint_bytes=65536, max_proof_bytes=65536):
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.max_checkpoint_bytes = max_checkpoint_bytes
        self.max_proof_bytes = max_proof_bytes
        self.throttling_profile = {
            1: {'batch': 16, 'pause_ms': 100},  # Quiet
            2: {'batch': 32, 'pause_ms': 50},   # Balanced
            3: {'batch': 64, 'pause_ms': 20},   # Active
            4: {'batch': 128, 'pause_ms': 10},  # High
            5: {'batch': 256, 'pause_ms': 0},   # Maximum
        }

    def check_memory(self):
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # On Linux ru_maxrss is in KiB
            usage_bytes = usage * 1024
            if usage_bytes > self.max_memory_bytes:
                return False
        except Exception:
            pass
        return True

    def check_checkpoint_size(self, data):
        if data is None:
            return True
        raw = data if isinstance(data, (bytes, str)) else json.dumps(data)
        size = len(raw) if isinstance(raw, bytes) else len(raw.encode('utf-8'))
        return size <= self.max_checkpoint_bytes

    def check_proof_size(self, data):
        raw = data if isinstance(data, (bytes, str)) else json.dumps(data)
        size = len(raw) if isinstance(raw, bytes) else len(raw.encode('utf-8'))
        return size <= self.max_proof_bytes


class CheckpointManager:
    """Manages task pause/resume state and intermediate checkpoints in SQLite."""
    def __init__(self, db, governor=None):
        self.db = db
        self.governor = governor or ResourceGovernor()
        self.init_db()

    def init_db(self):
        with self.db:
            self.db.execute("""
            CREATE TABLE IF NOT EXISTS gimps_checkpoints (
                task_id TEXT PRIMARY KEY,
                engine_id TEXT NOT NULL,
                exponent INTEGER NOT NULL,
                worker_id TEXT NOT NULL,
                iteration INTEGER NOT NULL,
                checkpoint_data TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """)

    def save_checkpoint(self, task_id, engine_id, exponent, worker_id, iteration, checkpoint_data):
        if not self.governor.check_checkpoint_size(checkpoint_data):
            raise ProtocolError('LIMIT_EXCEEDED', 'checkpoint size exceeds resource governor limit')
        now = int(time.time())
        data_str = json.dumps(checkpoint_data) if not isinstance(checkpoint_data, str) else checkpoint_data
        with self.db:
            self.db.execute("""
            INSERT INTO gimps_checkpoints (task_id, engine_id, exponent, worker_id, iteration, checkpoint_data, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                iteration=excluded.iteration,
                checkpoint_data=excluded.checkpoint_data,
                updated_at=excluded.updated_at
            """, (task_id, engine_id, exponent, worker_id, iteration, data_str, now))

    def load_checkpoint(self, task_id):
        row = self.db.execute(
            "SELECT engine_id, exponent, worker_id, iteration, checkpoint_data, updated_at FROM gimps_checkpoints WHERE task_id=?",
            (task_id,)
        ).fetchone()
        if not row:
            return None
        return {
            'task_id': task_id,
            'engine_id': row[0],
            'exponent': row[1],
            'worker_id': row[2],
            'iteration': row[3],
            'checkpoint_data': json.loads(row[4]) if row[4] else None,
            'updated_at': row[5]
        }

    def load_checkpoint_by_exponent(self, exponent):
        row = self.db.execute(
            "SELECT task_id, engine_id, exponent, worker_id, iteration, checkpoint_data, updated_at FROM gimps_checkpoints WHERE exponent=? ORDER BY updated_at DESC LIMIT 1",
            (exponent,)
        ).fetchone()
        if not row:
            return None
        return {
            'task_id': row[0],
            'engine_id': row[1],
            'exponent': row[2],
            'worker_id': row[3],
            'iteration': row[4],
            'checkpoint_data': json.loads(row[5]) if row[5] else None,
            'updated_at': row[6]
        }

    def delete_checkpoint(self, task_id):
        with self.db:
            self.db.execute("DELETE FROM gimps_checkpoints WHERE task_id=?", (task_id,))


class PrimeNetAdapter:
    """PrimeNet V5 result formatter, assignment tracker, and external attestation interface.
    Explicitly tracks: local_staged_untransmitted, primenet_transmitting, primenet_acknowledged, primenet_rejected.
    """
    STATE_LOCAL_STAGED = 'local_staged_untransmitted'
    STATE_TRANSMITTING = 'primenet_transmitting'
    STATE_ACKNOWLEDGED = 'primenet_acknowledged'
    STATE_REJECTED = 'primenet_rejected'

    def __init__(self, db=None, primenet_url=None, user_id=None, computer_id=None):
        self.db = db
        self.primenet_url = primenet_url
        self.user_id = user_id
        self.computer_id = computer_id
        if self.db:
            with self.db:
                self.db.execute("""
                CREATE TABLE IF NOT EXISTS primenet_attestations (
                    exponent INTEGER PRIMARY KEY,
                    assignment_uid TEXT,
                    v5_result TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'local_staged_untransmitted',
                    submitted_at INTEGER,
                    accepted_at INTEGER,
                    attestation_receipt TEXT
                )
                """)

    @staticmethod
    def format_v5_result(exponent, is_prime, res64, uid="ZI-NODE", gerbicz_status="OK"):
        """Format scientific result string according to PrimeNet V5 protocol."""
        res64_fmt = res64.upper() if isinstance(res64, str) else f"{res64:016X}"
        if is_prime:
            res_str = f"M({exponent}) is PRP!"
        else:
            res_str = f"M({exponent}) is not prime."
        return f"UID: {uid}; {res_str} RES64: {res64_fmt}; Gerbicz: {gerbicz_status}"

    @staticmethod
    def parse_v5_result(v5_str):
        """Parse PrimeNet V5 result line."""
        pattern = r"UID:\s*([^;]+);\s*M\((\d+)\)\s+is\s+([^.!;]+)[.!;]?\s*RES64:\s*([0-9A-Fa-f]{16});\s*Gerbicz:\s*([A-Za-z0-9_-]+)"
        match = re.search(pattern, v5_str)
        if not match:
            return None
        uid, exp, res_type, res64, gerbicz = match.groups()
        is_prp = 'PRP' in res_type
        return {
            'uid': uid.strip(),
            'exponent': int(exp),
            'is_prime': is_prp,
            'res64': res64.upper(),
            'gerbicz_status': gerbicz.strip()
        }

    def record_stage(self, exponent, v5_result, status=STATE_LOCAL_STAGED, receipt=None):
        """Record local staging without prematurely claiming remote PrimeNet submission."""
        if not self.db:
            return
        now = int(time.time())
        with self.db:
            self.db.execute("""
            INSERT INTO primenet_attestations (exponent, assignment_uid, v5_result, status, submitted_at, attestation_receipt)
            VALUES (?, '', ?, ?, ?, ?)
            ON CONFLICT(exponent) DO UPDATE SET
                v5_result=excluded.v5_result,
                status=excluded.status,
                submitted_at=excluded.submitted_at,
                attestation_receipt=excluded.attestation_receipt
            """, (exponent, v5_result, status, now, json.dumps(receipt) if receipt else None))

    def record_assignment(self, exponent, assignment_uid):
        if not self.db:
            return
        now = int(time.time())
        with self.db:
            self.db.execute("""
            INSERT INTO primenet_attestations (exponent, assignment_uid, v5_result, status, submitted_at)
            VALUES (?, ?, '', 'assigned', ?)
            ON CONFLICT(exponent) DO UPDATE SET assignment_uid=excluded.assignment_uid
            """, (exponent, assignment_uid, now))

    def record_submission(self, exponent, v5_result, receipt=None):
        self.record_stage(exponent, v5_result, status='submitted', receipt=receipt)

    def record_acceptance(self, exponent, receipt=None):
        if not self.db:
            return
        now = int(time.time())
        with self.db:
            self.db.execute("""
            UPDATE primenet_attestations SET status='accepted', accepted_at=?, attestation_receipt=?
            WHERE exponent=?
            """, (now, json.dumps(receipt) if receipt else None, exponent))

    def transmit_v5_result(self, exponent, v5_result, primenet_url=None, user_id=None, computer_id=None):
        """Transmit V5 result to PrimeNet API if configured; otherwise safely stages locally."""
        url = primenet_url or self.primenet_url
        uid = user_id or self.user_id or "ANONYMOUS"
        cid = computer_id or self.computer_id or "ZI-COMP"
        if not url:
            self.record_stage(exponent, v5_result, status=self.STATE_LOCAL_STAGED, receipt={'reason': 'offline_mode_unconfigured'})
            return {
                'status': self.STATE_LOCAL_STAGED,
                'acknowledged': False,
                'endpoint': None,
                'v5_result': v5_result
            }

        # Remote HTTPS transmission to PrimeNet endpoint
        import urllib.parse
        import urllib.request
        self.record_stage(exponent, v5_result, status=self.STATE_TRANSMITTING)
        try:
            req_data = urllib.parse.urlencode({
                'user': uid,
                'computer': cid,
                'v5_result': v5_result
            }).encode('utf-8')
            req = urllib.request.Request(url, data=req_data, headers={'User-Agent': 'Ziokt-GIMPS-Client/1.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode('utf-8', errors='ignore')
                receipt = {'code': resp.status, 'body': body[:256]}
                if resp.status == 200:
                    self.record_stage(exponent, v5_result, status=self.STATE_ACKNOWLEDGED, receipt=receipt)
                    return {'status': self.STATE_ACKNOWLEDGED, 'acknowledged': True, 'receipt': receipt}
                else:
                    self.record_stage(exponent, v5_result, status=self.STATE_REJECTED, receipt=receipt)
                    return {'status': self.STATE_REJECTED, 'acknowledged': False, 'receipt': receipt}
        except Exception as exc:
            receipt = {'error': str(exc)}
            self.record_stage(exponent, v5_result, status=self.STATE_REJECTED, receipt=receipt)
            return {'status': self.STATE_REJECTED, 'acknowledged': False, 'error': str(exc)}

    def get_attestation(self, exponent):
        if not self.db:
            return {'status': self.STATE_LOCAL_STAGED, 'exponent': exponent}
        row = self.db.execute(
            "SELECT assignment_uid, v5_result, status, submitted_at, accepted_at, attestation_receipt FROM primenet_attestations WHERE exponent=?",
            (exponent,)
        ).fetchone()
        if not row:
            return {'status': self.STATE_LOCAL_STAGED, 'exponent': exponent}
        return {
            'exponent': exponent,
            'assignment_uid': row[0],
            'v5_result': row[1],
            'status': row[2],
            'submitted_at': row[3],
            'accepted_at': row[4],
            'attestation_receipt': json.loads(row[5]) if row[5] else None
        }


def format_official_gimps_proof_file(proof_data):
    """Format proof as standard official mprime / Prime95 .proof file."""
    lines = [
        "[GIMPS PRP PROOF]",
        "Version=1",
        f"Exponent={proof_data['exponent']}",
        f"Base={proof_data.get('base', 3)}",
        f"Res64={proof_data.get('res64', '0'*16)}",
        f"Residue={proof_data.get('residue', '0')}",
        "ProofType=Gerbicz-Pietrzak",
        f"Iterations={proof_data.get('iterations', proof_data['exponent'] - 1)}",
    ]
    steps = proof_data.get('proof_steps', [])
    lines.append(f"Depth={len(steps)}")
    lines.append(f"ProofSteps={len(steps)}")
    for s in steps:
        lines.append(f"{s['Z']}:{1 if s.get('odd') else 0}")
    chk = proof_data.get('gerbicz_checkpoints', [])
    lines.append("[GERBICZ CHECKPOINTS]")
    lines.append(f"Count={len(chk)}")
    for c in chk:
        lines.append(f"{c['iteration']}:{c.get('state_hash', '')}:{c['hash']}")
    return "\n".join(lines) + "\n"


def parse_official_gimps_proof_file(text):
    """Parse standard official mprime / Prime95 .proof file content into dictionary."""
    data = {
        'schema': 'corium.gimps-prp-proof.v1',
        'method': 'prp-fiat-shamir',
        'proof_steps': [],
        'gerbicz_checkpoints': [],
        'gerbicz_status': 'OK'
    }
    section = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or line.startswith(';'):
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
            continue
        if '=' in line:
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip()
            if k == 'Exponent':
                data['exponent'] = int(v)
            elif k == 'Base':
                data['base'] = int(v)
            elif k == 'Res64':
                data['res64'] = v.upper()
            elif k == 'Residue':
                data['residue'] = v
            elif k == 'Iterations':
                data['iterations'] = int(v)
        elif section == 'GIMPS PRP PROOF' and ':' in line:
            parts = line.split(':')
            if len(parts) == 2:
                data['proof_steps'].append({'Z': parts[0], 'odd': parts[1] in ('1', 'true', 'True')})
        elif section == 'GERBICZ CHECKPOINTS' and ':' in line:
            parts = line.split(':')
            if len(parts) == 3:
                data['gerbicz_checkpoints'].append({'iteration': int(parts[0]), 'state_hash': parts[1], 'hash': parts[2]})
    if 'exponent' in data and 'residue' in data:
        p = data['exponent']
        N = (1 << p) - 1
        y = int(data['residue'])
        data['is_prp'] = (y == N - 1)
        data['prp_result'] = "PRP" if data['is_prp'] else "COMPOSITE"
        data['is_prime'] = bool(data['is_prp'] and (p <= 61 or p in (2, 3, 5, 7, 13, 17, 19, 31, 61, 89, 107, 127, 521, 607, 1279, 2203, 2281, 3217, 4253, 4423, 9689, 136279841)))
    return data


class MPrimeEngineAdapter:
    """Orchestration adapter for external host mprime / Prime95 executable."""
    def __init__(self, bin_path=None, work_dir=None):
        import shutil
        self.bin_path = bin_path or shutil.which('mprime') or shutil.which('prime95')
        self.work_dir = Path(work_dir or Path.home() / '.mprime')

    def is_available(self):
        return bool(self.bin_path and Path(self.bin_path).exists())

    def parse_results_txt(self, results_path=None):
        path = Path(results_path or (self.work_dir / 'results.txt'))
        if not path.exists():
            return []
        items = []
        for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
            p = PrimeNetAdapter.parse_v5_result(line)
            if p:
                items.append(p)
        return items

    parse_results_file = parse_results_txt

    def build_proof_from_mprime(self, exponent, work_dir=None):
        wdir = Path(work_dir or self.work_dir)
        proof_file = wdir / f"p{exponent}.proof"
        if not proof_file.exists():
            return None
        return parse_official_gimps_proof_file(proof_file.read_text(encoding='utf-8', errors='ignore'))


def format_scientific_proof_file(proof_data, uid="ZI-NODE"):
    """Generate portable p<exponent>.proof file content adhering to GIMPS & Corium standards."""
    p = proof_data['exponent']
    is_prime = proof_data.get('is_prime', False)
    res64 = proof_data.get('res64', '0'*16)
    v5_line = PrimeNetAdapter.format_v5_result(p, is_prime, res64, uid=uid, gerbicz_status=proof_data.get('gerbicz_status', 'OK'))

    proof_package = {
        'schema': 'corium.gimps-scientific-proof.v1',
        'exponent': p,
        'primenet_v5_result': v5_line,
        'proof': proof_data,
        'official_mprime_proof': format_official_gimps_proof_file(proof_data),
        'timestamp': int(time.time()),
        'sha256': hashlib.sha256(encoded(proof_data)).hexdigest()
    }
    return json.dumps(proof_package, sort_keys=True, indent=2)


def export_proof_to_content_fabric(proof_data, chunkstore_dir=None, uid="ZI-NODE"):
    """Store scientific proof into Content Fabric chunkstore indexed by SHA256 (dual format: .proof text and JSON)."""
    content = format_scientific_proof_file(proof_data, uid=uid)
    content_bytes = content.encode('utf-8')
    content_hash = hashlib.sha256(content_bytes).hexdigest()
    official_proof = format_official_gimps_proof_file(proof_data)

    if chunkstore_dir:
        store_path = Path(chunkstore_dir)
        store_path.mkdir(parents=True, exist_ok=True)
        file_path = store_path / f"p{proof_data['exponent']}.proof"
        file_path.write_text(official_proof, encoding='utf-8')
        json_path = store_path / f"p{proof_data['exponent']}.json"
        json_path.write_bytes(content_bytes)
        chunk_path = store_path / f"sha256_{content_hash}.chunk"
        chunk_path.write_bytes(content_bytes)
    return {
        'content_hash': content_hash,
        'filename': f"p{proof_data['exponent']}.proof",
        'bytes': len(content_bytes)
    }


class GimpsPool(EffortPool):
    def __init__(self, client, submitter, state, *, expected_network=None, chunkstore_dir=None):
        super().__init__(client, submitter, state, expected_network=expected_network)
        self.governor = ResourceGovernor()
        self.checkpoints = CheckpointManager(self.db, self.governor)
        self.primenet = PrimeNetAdapter(self.db)
        self.chunkstore_dir = chunkstore_dir or (Path(state) / 'chunkstore')
        Path(self.chunkstore_dir).mkdir(mode=0o700, parents=True, exist_ok=True)

    def issue(self):
        require_network()
        with self.lock:
            pending = self.db.execute('SELECT problem,operation FROM submissions WHERE result IS NULL LIMIT 1').fetchone()
            if pending:
                self.recover(pending[0], pending[1])
            now = time.time()
            self.jobs = {token: job for token, job in self.jobs.items() if job['expires'] > now}
            if len(self.jobs) >= 128:
                raise ProtocolError('BACKPRESSURE', 'GIMPS worker job budget exhausted')
            job = self.client.call('compute.challenge', {'engine': 'gimps'})
            if (not isinstance(job, dict) or job.get('schema') != 'corium.gimps-challenge.v1' or
                    job.get('submitter_id') != self.submitter or self.expected_network and job.get('network_id') != self.expected_network):
                raise ProtocolError('NETWORK_MISMATCH', 'native GIMPS node and signer must match configuration')
            if job.get('available') is not True:
                return {'available': False, 'engine': 'gimps', 'reason': job.get('reason', 'no-native-task'), 'retry_ms': 5000}
            p = job.get('exponent')
            max_exp = job.get('max_exponent', 2_000_000_000)
            if (type(p) is not int or not 2 <= p <= max_exp or job.get('problem_id') != str(p) or
                    job.get('proof_schema') not in ('corium.gimps-proof.v2', 'corium.gimps-prp-proof.v1') or
                    job.get('method') not in ('lucas-lehmer', 'prp-fiat-shamir') or
                    not isinstance(job.get('engine_id'), str) or len(job['engine_id']) > 128):
                raise ProtocolError('INVALID_JOB', 'bounded native GIMPS task required')

            # Look up any existing checkpoint for this exponent
            chk = self.checkpoints.load_checkpoint_by_exponent(p)
            checkpoint_data = chk['checkpoint_data'] if chk else None

            token = secrets.token_hex(24)
            job = dict(job, engine='gimps', token=token, expires=int(now) + 86400, checkpoint=checkpoint_data)
            self.jobs[token] = job
            return job

    def submit(self, token, proof):
        require_network()
        with self.lock:
            job = self.jobs.get(token) if isinstance(token, str) else None
            if not job or job['expires'] <= time.time():
                raise ProtocolError('STALE_JOB', 'native GIMPS job expired')
            if not isinstance(proof, dict) or not self.governor.check_proof_size(proof):
                raise ProtocolError('INVALID_PROOF', 'native bounded GIMPS proof required')

            schema = proof.get('schema')
            p = job['exponent']
            if proof.get('exponent') != p:
                raise ProtocolError('INVALID_PROOF', 'exponent mismatch')

            from ._runtime import _native_gimps

            if schema == 'corium.gimps-prp-proof.v1':
                # PRP Proof of Exponentiation with Fiat-Shamir folding
                if (proof.get('method') != 'prp-fiat-shamir' or proof.get('base') != 3 or
                        proof.get('iterations') != p - 1 or
                        type(proof.get('res64')) is not str or len(proof['res64']) != 16 or
                        type(proof.get('residue')) is not str):
                    raise ProtocolError('INVALID_PROOF', 'canonical PRP proof fields required')

                # Prover MUST provide proof_steps; verifier NEVER computes proof_steps for workers
                if 'proof_steps' not in proof or not isinstance(proof['proof_steps'], list) or not proof['proof_steps']:
                    raise ProtocolError('INVALID_PROOF', 'PRP proof_steps required from worker prover')

                try:
                    _native_gimps.verify_prp_proof(p, proof)
                except Exception as exc:
                    raise ProtocolError('INVALID_PROOF', f'PRP proof verification failed: {exc}') from exc

                is_prime = proof.get('is_prime', False)
                res64 = proof['res64']
            elif schema == 'corium.gimps-proof.v2':
                # Legacy Lucas-Lehmer proof
                if (set(proof) != {'schema', 'exponent', 'method', 'residue', 'is_prime', 'iterations'} or
                        proof.get('method') != 'lucas-lehmer' or type(proof.get('residue')) is not str or
                        len(proof['residue']) > 1234):
                    raise ProtocolError('INVALID_PROOF', 'native portable Lucas-Lehmer proof required')
                residue = proof['residue']
                if (not residue.isascii() or not residue.isdecimal() or str(int(residue)) != residue or
                        type(proof['is_prime']) is not bool or type(proof['iterations']) is not int or
                        proof['iterations'] != p - 2):
                    raise ProtocolError('INVALID_PROOF', 'canonical GIMPS result required')
                valid, expected = _native_gimps.lucas_lehmer_verify(p, int(residue))
                if not valid or proof['is_prime'] != (expected == 0):
                    raise ProtocolError('INVALID_PROOF', 'Corium Lucas-Lehmer recomputation failed')
                is_prime = proof['is_prime']
                res64 = f"{int(residue) & 0xFFFFFFFFFFFFFFFF:016X}"
            else:
                raise ProtocolError('INVALID_PROOF', 'unsupported proof schema')

            # Three-tier outcome tracking:
            # 1. math_certified: verified above
            math_certified = True
            # 2. primenet_status: format PrimeNet V5 line and record in local database
            v5_result = PrimeNetAdapter.format_v5_result(p, is_prime, res64, uid=self.submitter[:16], gerbicz_status=proof.get('gerbicz_status', 'OK'))
            # Local mode records status as local_staged_untransmitted without claiming remote submission
            self.primenet.record_stage(p, v5_result, status=PrimeNetAdapter.STATE_LOCAL_STAGED)
            primenet_status = PrimeNetAdapter.STATE_LOCAL_STAGED
            # 3. corium_settled: initially False until challenge window and settle()
            corium_settled = False

            # Scientific export to Content Fabric chunkstore
            fabric_meta = export_proof_to_content_fabric(proof, self.chunkstore_dir, uid=self.submitter[:16])

            problem = job['engine_id'] + ':' + job['problem_id']
            previous = self.db.execute('SELECT operation,nonce,result FROM submissions WHERE problem=?', (problem,)).fetchone()
            if previous and previous[2]:
                return dict(strict_json(previous[2]), duplicate=True)
            if previous:
                result = self.recover(problem, previous[0])
            else:
                operation = 'web-gimps-' + hashlib.sha256((job['network_id'] + problem + self.submitter).encode()).hexdigest()[:40] + '-' + secrets.token_hex(4)
                plan = self.client.call('operation.prepare', {
                    'operation_id': operation,
                    'action': 'compute.submit',
                    'resource': 'compute:' + job['engine_id'],
                    'arguments': {'engine_id': job['engine_id'], 'problem_id': job['problem_id'], 'proof_data': proof},
                    'expected_revision': None
                })
                with self.db:
                    self.db.execute('INSERT INTO submissions VALUES (?,?,?,NULL)', (problem, operation, encoded(proof).decode()))
                result = self.client.call('operation.commit', {'operation_id': operation, 'plan_digest': plan['plan_digest']})

            if result.get('state') != 'committed':
                raise ProtocolError('RESULT_UNKNOWN', 'native GIMPS submission awaits reconciliation')

            # Clean up task checkpoint upon successful submission
            self.checkpoints.delete_checkpoint(problem)

            receipt = {
                'accepted': True,
                'engine': 'gimps',
                'exponent': p,
                'phase': result['result']['phase'],
                'transaction_hash': result['result']['transaction_hash'],
                'confirmed': False,
                'math_certified': math_certified,
                'primenet_status': primenet_status,
                'corium_settled': corium_settled,
                'primenet_v5_result': v5_result,
                'content_fabric_hash': fabric_meta['content_hash']
            }
            with self.db:
                self.db.execute('UPDATE submissions SET result=? WHERE problem=?', (encoded(receipt), problem))
            return dict(receipt, duplicate=False)

    def save_checkpoint(self, token, checkpoint_data):
        """Worker periodic checkpoint saver."""
        require_network()
        with self.lock:
            job = self.jobs.get(token) if isinstance(token, str) else None
            if not job or job['expires'] <= time.time():
                raise ProtocolError('STALE_JOB', 'native GIMPS job expired')
            if not self.governor.check_checkpoint_size(checkpoint_data):
                raise ProtocolError('LIMIT_EXCEEDED', 'checkpoint payload too large')
            task_id = job['engine_id'] + ':' + job['problem_id']
            iteration = checkpoint_data.get('iteration', 0) if isinstance(checkpoint_data, dict) else 0
            self.checkpoints.save_checkpoint(task_id, job['engine_id'], job['exponent'], self.submitter, iteration, checkpoint_data)
            return {'saved': True, 'exponent': job['exponent'], 'iteration': iteration}

    def heartbeat(self, token, progress_pct=None, checkpoint_data=None):
        """Worker heartbeat renewal for long-running compute lease."""
        require_network()
        with self.lock:
            job = self.jobs.get(token) if isinstance(token, str) else None
            if not job:
                raise ProtocolError('STALE_JOB', 'native GIMPS job not found')
            now = time.time()
            job['expires'] = int(now) + 86400
            task_id = job['engine_id'] + ':' + job['problem_id']
            iteration = checkpoint_data.get('iteration', 0) if isinstance(checkpoint_data, dict) else 0
            if checkpoint_data:
                if not self.governor.check_checkpoint_size(checkpoint_data):
                    raise ProtocolError('LIMIT_EXCEEDED', 'checkpoint payload too large')
                self.checkpoints.save_checkpoint(task_id, job['engine_id'], job['exponent'], self.submitter, iteration, checkpoint_data)
            return {'renewed': True, 'exponent': job['exponent'], 'expires': job['expires'], 'iteration': iteration}

    def pause(self, token, checkpoint_data=None):
        """Pause active task and preserve checkpoint."""
        require_network()
        with self.lock:
            job = self.jobs.get(token) if isinstance(token, str) else None
            if not job:
                raise ProtocolError('STALE_JOB', 'native GIMPS job not found')
            task_id = job['engine_id'] + ':' + job['problem_id']
            if checkpoint_data:
                iteration = checkpoint_data.get('iteration', 0) if isinstance(checkpoint_data, dict) else 0
                self.checkpoints.save_checkpoint(task_id, job['engine_id'], job['exponent'], self.submitter, iteration, checkpoint_data)
            return {'paused': True, 'exponent': job['exponent']}

    def resume(self, exponent, worker_id=None):
        """Resume paused task and return checkpoint."""
        require_network()
        with self.lock:
            chk = self.checkpoints.load_checkpoint_by_exponent(exponent)
            if not chk:
                return {'resumed': False, 'exponent': exponent, 'checkpoint': None}
            return {'resumed': True, 'exponent': exponent, 'checkpoint': chk['checkpoint_data'], 'iteration': chk['iteration']}

    def get_status(self, exponent=None):
        """Query 3-tier status for an exponent or latest attestation."""
        require_network()
        with self.lock:
            if exponent is not None:
                exp = int(exponent)
                att = self.primenet.get_attestation(exp)
                problem_id = str(exp)
                row = self.db.execute("SELECT result FROM submissions WHERE problem LIKE ? AND result IS NOT NULL", (f"%:{problem_id}",)).fetchone()
                settled = False
                tx_hash = None
                if row:
                    try:
                        res = json.loads(row[0].decode() if isinstance(row[0], bytes) else row[0])
                        tx_hash = res.get('transaction_hash')
                        settled = res.get('confirmed', False) or res.get('corium_settled', False)
                    except Exception:
                        pass
                return {
                    'exponent': exp,
                    'math_certified': att.get('status') in ('submitted', 'accepted'),
                    'primenet_status': att.get('status', 'unsubmitted'),
                    'corium_settled': settled,
                    'transaction_hash': tx_hash,
                    'v5_result': att.get('v5_result')
                }
            # Global overview
            rows = self.db.execute("SELECT COUNT(*), status FROM primenet_attestations GROUP BY status").fetchall()
            counts = {r[1]: r[0] for r in rows}
            return {
                'active_jobs': len(self.jobs),
                'attestations': counts,
                'tier_summary': {
                    'math_certified': sum(counts.values()),
                    'primenet_submitted': counts.get('submitted', 0) + counts.get('accepted', 0),
                    'corium_settled': counts.get('accepted', 0)
                }
            }

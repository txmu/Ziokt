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
    """Safeguards worker execution with CPU duty-cycle throttling, memory ceiling, and storage bounds.
    Configurable per local host capacity to protect hardware while supporting external engines.
    """
    DEFAULT_MAX_NATIVE_EXPONENT = 100_000

    def __init__(self, max_memory_mb=256, max_checkpoint_bytes=65536, max_proof_bytes=65536, max_native_exponent=None):
        import os
        self.max_memory_mb = int(max_memory_mb) if max_memory_mb is not None else 256
        self.max_memory_bytes = self.max_memory_mb * 1024 * 1024
        self.max_checkpoint_bytes = max_checkpoint_bytes
        self.max_proof_bytes = max_proof_bytes
        if max_native_exponent is not None:
            self.max_native_exponent = int(max_native_exponent)
        else:
            env_val = os.environ.get('ZIOKT_GIMPS_MAX_EXPONENT')
            self.max_native_exponent = int(env_val) if env_val and env_val.isdigit() else self.DEFAULT_MAX_NATIVE_EXPONENT

        if not 2 <= self.max_native_exponent <= 2_000_000_000 or not 1 <= self.max_memory_mb <= 65536:
            raise ValueError('positive bounded local GIMPS resource limits required')

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

    def check_exponent_capacity(self, exponent, is_external_engine=False):
        """Check whether exponent can be safely computed/verified on this node."""
        # External engine labels are untrusted and do not relax verifier limits.
        if type(exponent) is not int or exponent < 2:
            return False
        if exponent > self.max_native_exponent:
            return False
        est_mem_bytes = (exponent // 8) * 32
        return est_mem_bytes <= self.max_memory_bytes

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
        if type(iteration) is not int or not 0 <= iteration <= exponent:
            raise ProtocolError('INVALID_CHECKPOINT', 'bounded checkpoint iteration required')
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
        """Format a local Corium summary, not an official PrimeNet wire result."""
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
                accepted_at=NULL,
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
        if not isinstance(receipt, dict) or receipt.get('endpoint') != 'https://v5.mersenne.org/v5server/' or receipt.get('pnErrorResult') != 0 or receipt.get('transaction') != 'ar' or receipt.get('exponent') != exponent:
            raise ValueError('trusted assignment-bound PrimeNet receipt required')
        current = self.get_attestation(exponent)
        if current.get('status') != self.STATE_ACKNOWLEDGED or current.get('attestation_receipt') != receipt:
            raise ValueError('locally observed PrimeNet acknowledgement required')
        if not self.db:
            return
        now = int(time.time())
        with self.db:
            self.db.execute("""
            UPDATE primenet_attestations SET status='accepted', accepted_at=?, attestation_receipt=?
            WHERE exponent=?
            """, (now, json.dumps(receipt) if receipt else None, exponent))

    @staticmethod
    def parse_primenet_response(body_str, http_status=200):
        """Decode protocol status only; endpoint and assignment binding are separate."""
        receipt = {'http_status': http_status, 'raw_body': body_str[:512], 'status': 'unrecognized'}
        if http_status != 200:
            return False, True, dict(receipt, status='rejected', reason=f'HTTP {http_status}')
        if type(body_str) is not str or len(body_str) > 65536:
            return False, False, receipt
        try:
            data = strict_json(body_str.encode())
        except (ValueError, ProtocolError):
            data = {}
            for line in body_str.splitlines():
                key, sep, value = line.partition('=')
                if sep and key in {'pnErrorResult', 'pnErrorDetail'}:
                    if key in data:
                        return False, False, receipt
                    data[key] = value
        if type(data) is not dict or type(data.get('pnErrorDetail')) is not str:
            return False, False, receipt
        code = data.get('pnErrorResult')
        if type(code) is int:
            pass
        elif type(code) is str and re.fullmatch(r'0|[1-9][0-9]{0,5}', code):
            code = int(code)
        else:
            return False, False, receipt
        receipt.update(pnErrorResult=code, pnErrorDetail=data['pnErrorDetail'])
        if code:
            return False, True, dict(receipt, status='rejected', reason=data['pnErrorDetail'])
        return True, False, dict(receipt, status='protocol_success')

    def transmit_v5_result(self, exponent, v5_result, primenet_url=None, user_id=None, computer_id=None):
        """Submit an original Prime95 JSON result using the PrimeNet ar transaction.

        Native Corium display lines are staged only. Official acceptance requires
        a locally recorded assignment, registered computer GUID, canonical TLS
        endpoint, no redirects, and a successful business response.
        """
        import urllib.parse
        import urllib.request
        url = primenet_url or self.primenet_url
        def staged(reason):
            self.record_stage(exponent, v5_result, receipt={'reason': reason})
            return {'status': self.STATE_LOCAL_STAGED, 'acknowledged': False, 'reason': reason}
        if not url:
            return staged('offline_mode_unconfigured')
        if url != 'https://v5.mersenne.org/v5server/':
            return staged('trusted_primenet_endpoint_required')
        cid = computer_id or self.computer_id
        attestation = self.get_attestation(exponent)
        assignment = attestation.get('assignment_uid')
        if not isinstance(cid, str) or not re.fullmatch(r'[0-9a-fA-F]{32}', cid):
            return staged('registered_computer_guid_required')
        if not isinstance(assignment, str) or not re.fullmatch(r'[0-9a-fA-F]{32}', assignment):
            return staged('recorded_official_assignment_required')
        try:
            result = strict_json(v5_result.encode())
        except (ValueError, TypeError, AttributeError, ProtocolError):
            return staged('original_prime95_json_result_required')
        if (type(result) is not dict or type(result.get('program')) is not dict or result.get('program', {}).get('name') not in ('Prime95', 'mprime')
                or type(result.get('exponent')) is not int or result['exponent'] != exponent
                or result.get('worktype') != 'PRP-3' or result.get('status') not in ('P', 'C')
                or not re.fullmatch(r'[0-9a-fA-F]{8}', result.get('error-code', ''))):
            return staged('invalid_official_result_identity')
        fields = {'v': '5.00', 'px': 'GIMPS', 't': 'ar', 'g': cid, 'k': assignment,
                  'm': v5_result, 'r': 151 if result['status'] == 'P' else 150,
                  'd': 1, 'A': 1, 'b': 2, 'n': exponent, 'c': -1,
                  'base': 3, 'ec': result['error-code']}
        if result['status'] == 'C':
            residue = result.get('res64')
            if not isinstance(residue, str) or not re.fullmatch(r'[0-9a-fA-F]{16}', residue):
                return staged('official_composite_residue_required')
            fields.update(rd=residue, rt=1)
        proof = result.get('proof')
        if proof:
            if (type(proof) is not dict or type(proof.get('power')) is not int
                    or not 1 <= proof['power'] <= 12
                    or not re.fullmatch(r'[0-9a-fA-F]{32}', proof.get('md5', ''))):
                return staged('invalid_official_proof_identity')
            fields.update(pp=proof['power'], ph=proof['md5'])
        if type(result.get('errors')) is dict and result['errors'].get('gerbicz') == 0:
            fields['gbz'] = 1
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise ValueError('PrimeNet redirects forbidden')
        self.record_stage(exponent, v5_result, status=self.STATE_TRANSMITTING)
        try:
            request_url = url + '?' + urllib.parse.urlencode(fields)
            request = urllib.request.Request(request_url, headers={'User-Agent': 'Ziokt-GIMPS-Client/1.0'})
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=10) as response:
                body = response.read(65537)
                if len(body) > 65536:
                    raise ValueError('PrimeNet response budget')
                ack, rejected, receipt = self.parse_primenet_response(body.decode('utf-8'), response.status)
            receipt.update(endpoint=url, assignment_uid=assignment, exponent=exponent,
                           computer_guid=cid, transaction='ar', result_sha256=hashlib.sha256(v5_result.encode()).hexdigest())
            status = self.STATE_ACKNOWLEDGED if ack else self.STATE_REJECTED if rejected else self.STATE_LOCAL_STAGED
            self.record_stage(exponent, v5_result, status=status, receipt=receipt)
            return {'status': status, 'acknowledged': ack, 'receipt': receipt}
        except Exception as exc:
            # Transport failures are indeterminate; they are not business rejections.
            return staged('transport_unconfirmed:' + type(exc).__name__)

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


def format_official_gimps_proof_file(raw):
    """Preserve a genuine binary proof. Native Corium transcripts use JSON."""
    from .gimps_files import verify_proof
    verify_proof(raw)
    return raw


def parse_official_gimps_proof_file(raw):
    """Read actual ASCII-header + binary-residue GIMPS files, without decoding loss."""
    from .gimps_files import parse_proof
    return parse_proof(raw)


class MPrimeEngineAdapter:
    """Orchestration adapter for external host mprime / Prime95 executable and official results."""
    def __init__(self, bin_path=None, work_dir=None):
        import shutil
        self.bin_path = bin_path or shutil.which('mprime') or shutil.which('prime95')
        self.work_dir = Path(work_dir or Path.home() / '.mprime')

    def is_available(self):
        return bool(self.bin_path and Path(self.bin_path).exists())

    @staticmethod
    def parse_official_prime95_line(line):
        """Parse official Prime95 results.txt line (both timestamped Prime95 and V5 format)."""
        line = line.strip()
        if not line or line.startswith('#'):
            return None
        if line.startswith('{'):
            try:
                result = json.loads(line)
                p = result.get('exponent')
                if (type(p) is not int or not 2 <= p <= 2_000_000_000
                        or result.get('program', {}).get('name') not in ('Prime95', 'mprime')
                        or result.get('worktype') != 'PRP-3' or result.get('status') not in ('P', 'C')):
                    return None
                return {'exponent': p, 'is_prp': result['status'] == 'P',
                        'is_prime': False, 'res64': result.get('res64'),
                        'timestamp': result.get('timestamp'), 'raw_result': result,
                        'gerbicz_status': 'REPORTED_OK' if result.get('errors', {}).get('gerbicz') == 0 else 'UNKNOWN'}
            except (ValueError, AttributeError):
                return None
        v5 = PrimeNetAdapter.parse_v5_result(line)
        if v5:
            return v5
        ts_match = re.match(r'^\[([^\]]+)\]\s*(.*)$', line)
        ts_str = ts_match.group(1) if ts_match else None
        rest = ts_match.group(2) if ts_match else line
        uid = "OFFICIAL"
        if 'UID:' in rest:
            parts = re.split(r'[,;]', rest, maxsplit=1)
            uid = parts[0].replace('UID:', '').strip()
            rest = parts[1] if len(parts) > 1 else rest

        pattern = r'M\(?(\d+)\)?\s+is\s+([^.!]+)[.!]\s*Res64:\s*([0-9A-Fa-f]{16})'
        match = re.search(pattern, rest, re.IGNORECASE)
        if not match:
            return None
        exp_str, verdict, res64 = match.groups()
        is_prime = 'not' not in verdict.lower()
        return {
            'uid': uid,
            'exponent': int(exp_str),
            'is_prime': is_prime,
            'res64': res64.upper(),
            'timestamp': ts_str,
            'gerbicz_status': 'OK' if is_prime else 'N/A'
        }

    def parse_results_txt(self, results_path=None):
        path = Path(results_path or (self.work_dir / 'results.txt'))
        if not path.exists():
            return []
        if path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('bounded regular result file required')
        items = []
        for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
            p = self.parse_official_prime95_line(line)
            if p:
                items.append(p)
        return items

    parse_results_file = parse_results_txt

    @staticmethod
    def generate_worktodo_ini(work_dir, exponent, prp=True, base=3):
        """Generate official Prime95 worktodo.ini directive to drive mprime/prime95 tasks."""
        wdir = Path(work_dir)
        wdir.mkdir(parents=True, exist_ok=True)
        ini_path = wdir / 'worktodo.ini'
        if type(exponent) is not int or not 3 <= exponent <= ResourceGovernor.DEFAULT_MAX_NATIVE_EXPONENT or base != 3:
            raise ValueError('bounded base-3 Mersenne task required')
        line = f"PRP=1,2,{exponent},-1,99,0,3,1\n" if prp else f"Test={exponent},99,0\n"
        with ini_path.open('x', encoding='utf-8') as stream:
            stream.write(line)
        return ini_path

    def build_proof_from_mprime(self, exponent, work_dir=None):
        if type(exponent) is not int or not 3 <= exponent <= ResourceGovernor.DEFAULT_MAX_NATIVE_EXPONENT:
            raise ValueError('bounded official proof exponent required')
        wdir = Path(work_dir or self.work_dir)
        proof_file = wdir / f"p{exponent:07d}.proof"
        if not proof_file.exists():
            proof_file = wdir / f"p{exponent}.proof"
        if not proof_file.exists():
            return None
        from .gimps_files import verify_proof
        from ._runtime import _native_gimps
        if proof_file.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('bounded official proof file required')
        raw = proof_file.read_bytes()
        verified = verify_proof(raw)
        if verified['exponent'] != exponent:
            raise ValueError('official proof exponent mismatch')
        # Corium and GIMPS use different transcripts. Re-prove within local limits;
        # do not relabel official bytes as a Corium Fiat-Shamir proof.
        proof = _native_gimps.generate_prp_proof(exponent)
        proof['source_proof_sha256'] = verified['sha256']
        return proof


def format_scientific_proof_file(proof_data, uid="ZI-NODE"):
    """Serialize a native Corium transcript; this is not a GIMPS binary proof."""
    p = proof_data['exponent']
    is_prime = proof_data.get('is_prime', False)
    res64 = proof_data.get('res64', '0'*16)
    v5_line = PrimeNetAdapter.format_v5_result(p, is_prime, res64, uid=uid, gerbicz_status=proof_data.get('gerbicz_status', 'OK'))

    proof_package = {
        'schema': 'corium.gimps-scientific-proof.v1',
        'exponent': p,
        'primenet_v5_result': v5_line,
        'proof': proof_data,
        'format': 'corium-json',
        'primenet_accepted': False,
        'timestamp': int(time.time()),
        'sha256': hashlib.sha256(encoded(proof_data)).hexdigest()
    }
    return json.dumps(proof_package, sort_keys=True, indent=2)


def export_proof_to_content_fabric(proof_data, chunkstore_dir=None, uid="ZI-NODE"):
    """Store scientific proof into Content Fabric chunkstore indexed by SHA256 (dual format: .proof text and JSON)."""
    content = format_scientific_proof_file(proof_data, uid=uid)
    content_bytes = content.encode('utf-8')
    content_hash = hashlib.sha256(content_bytes).hexdigest()

    if chunkstore_dir:
        store_path = Path(chunkstore_dir)
        store_path.mkdir(parents=True, exist_ok=True)
        json_path = store_path / f"p{proof_data['exponent']}.corium-proof.json"
        json_path.write_bytes(content_bytes)
        chunk_path = store_path / f"sha256_{content_hash}.chunk"
        chunk_path.write_bytes(content_bytes)
    return {
        'content_hash': content_hash,
        'filename': f"p{proof_data['exponent']}.corium-proof.json",
        'bytes': len(content_bytes)
    }


class GimpsPool(EffortPool):
    def __init__(self, client, submitter, state, *, expected_network=None, chunkstore_dir=None, governor=None):
        super().__init__(client, submitter, state, expected_network=expected_network)
        self.governor = governor or ResourceGovernor()
        self.checkpoints = CheckpointManager(self.db, self.governor)
        self.primenet = PrimeNetAdapter(self.db)
        self.chunkstore_dir = chunkstore_dir or (Path(state) / 'chunkstore')
        Path(self.chunkstore_dir).mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.db:
            self.db.execute("""
            CREATE TABLE IF NOT EXISTS gimps_leases (
                token TEXT PRIMARY KEY,
                engine_id TEXT NOT NULL,
                problem_id TEXT NOT NULL,
                exponent INTEGER NOT NULL,
                submitter TEXT NOT NULL,
                network_id TEXT NOT NULL,
                proof_schema TEXT NOT NULL,
                method TEXT NOT NULL,
                max_exponent INTEGER NOT NULL,
                expires INTEGER NOT NULL,
                checkpoint TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """)
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS gimps_lease_receipts (
                token TEXT PRIMARY KEY, submitter TEXT NOT NULL, network_id TEXT NOT NULL,
                proof_digest TEXT NOT NULL, receipt BLOB NOT NULL, expires INTEGER NOT NULL)""")
        if 'worker_id' not in {row[1] for row in self.db.execute('PRAGMA table_info(gimps_leases)')}:
            with self.db:self.db.execute("ALTER TABLE gimps_leases ADD COLUMN worker_id TEXT")
        self._load_active_leases()

    def _load_active_leases(self):
        now = int(time.time())
        rows = self.db.execute(
            "SELECT token, engine_id, problem_id, exponent, submitter, network_id, proof_schema, method, max_exponent, expires, checkpoint FROM gimps_leases WHERE expires > ? AND submitter=? AND (? IS NULL OR network_id=?)",
            (now, self.submitter, self.expected_network, self.expected_network)
        ).fetchall()
        for r in rows:
            self.jobs[r[0]] = {
                'token': r[0],
                'engine': 'gimps',
                'available': True,
                'engine_id': r[1],
                'problem_id': r[2],
                'exponent': r[3],
                'submitter_id': r[4],
                'network_id': r[5],
                'proof_schema': r[6],
                'method': r[7],
                'max_exponent': r[8],
                'expires': r[9],
                'checkpoint': json.loads(r[10]) if r[10] else None
            }

    def _get_active_job(self, token):
        if not isinstance(token, str):
            return None
        now = int(time.time())
        row = self.db.execute(
            "SELECT engine_id, problem_id, exponent, submitter, network_id, proof_schema, method, max_exponent, expires, checkpoint FROM gimps_leases WHERE token=? AND expires > ? AND submitter=? AND (? IS NULL OR network_id=?)",
            (token, now, self.submitter, self.expected_network, self.expected_network)
        ).fetchone()
        if not row:
            return None
        job = {
            'token': token,
            'engine': 'gimps',
            'available': True,
            'engine_id': row[0],
            'problem_id': row[1],
            'exponent': row[2],
            'submitter_id': row[3],
            'network_id': row[4],
            'proof_schema': row[5],
            'method': row[6],
            'max_exponent': row[7],
            'expires': row[8],
            'checkpoint': json.loads(row[9]) if row[9] else None
        }
        self.jobs[token] = job
        return job

    def issue(self, worker_id=None):
        require_network()
        if worker_id is None:worker_id=secrets.token_hex(24)
        if not isinstance(worker_id,str) or len(worker_id)!=48 or any(c not in '0123456789abcdef' for c in worker_id):
            raise ProtocolError('INVALID_JOB','private random worker identifier required')
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                result=self._issue_locked(worker_id)
                self.db.commit()
                return result
            except BaseException:self.db.rollback();raise

    def _issue_locked(self, worker_id):
        now = time.time()
        self.jobs = {token: job for token, job in self.jobs.items() if job['expires'] > now}
        if len(self.jobs) >= 128:
            raise ProtocolError('BACKPRESSURE', 'GIMPS worker job budget exhausted')
        owned=self.db.execute('SELECT token FROM gimps_leases WHERE worker_id=? AND submitter=? AND (? IS NULL OR network_id=?) AND expires>? ORDER BY created_at LIMIT 1',
                              (worker_id,self.submitter,self.expected_network,self.expected_network,int(now))).fetchone()
        if owned:return self._get_active_job(owned[0])
        reserved=self.db.execute('SELECT DISTINCT exponent FROM gimps_leases WHERE submitter=? AND (? IS NULL OR network_id=?) AND expires>?',
                                 (self.submitter,self.expected_network,self.expected_network,int(now))).fetchall()
        params={'engine':'gimps'}
        if reserved:params['exclude_exponents']=[row[0] for row in reserved]
        job = self.client.call('compute.challenge', params)
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

        if not self.governor.check_exponent_capacity(p):
            return {'available': False, 'engine': 'gimps', 'reason': f'exponent-{p}-exceeds-node-capacity', 'retry_ms': 10000}

        # Look up any existing checkpoint for this exponent
        task_key = job['network_id'] + ':' + self.submitter + ':' + job['engine_id'] + ':' + str(p)
        chk = self.checkpoints.load_checkpoint(task_key)
        checkpoint_data = chk['checkpoint_data'] if chk else None

        existing = self.db.execute('SELECT token FROM gimps_leases WHERE network_id=? AND submitter=? AND engine_id=? AND exponent=? AND expires>? ORDER BY created_at LIMIT 1',
                                   (job['network_id'], self.submitter, job['engine_id'], p, int(now))).fetchone()
        if existing:
            return {'available':False,'engine':'gimps','reason':'task-leased','retry_ms':5000}
        token = secrets.token_hex(24)
        job = dict(job, engine='gimps', token=token, expires=int(now) + 120, checkpoint=checkpoint_data)
        self.jobs[token] = job
        self.db.execute("""
        INSERT INTO gimps_leases (token, engine_id, problem_id, exponent, submitter, network_id, proof_schema, method, max_exponent, expires, checkpoint, created_at, updated_at)
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (SELECT 1 FROM gimps_leases WHERE network_id=? AND submitter=? AND engine_id=? AND exponent=? AND expires>?)
        """, (token, job['engine_id'], job['problem_id'], p, self.submitter, job['network_id'], job['proof_schema'], job['method'], job.get('max_exponent', 2_000_000_000), job['expires'], json.dumps(checkpoint_data) if checkpoint_data else None, int(now), int(now), job['network_id'], self.submitter, job['engine_id'], p, int(now)))
        row = self.db.execute('SELECT token FROM gimps_leases WHERE network_id=? AND submitter=? AND engine_id=? AND exponent=? AND expires>? ORDER BY created_at LIMIT 1',
                              (job['network_id'], self.submitter, job['engine_id'], p, int(now))).fetchone()
        self.db.execute('UPDATE gimps_leases SET worker_id=? WHERE token=?',(worker_id,token))
        self.db.execute('DELETE FROM gimps_leases WHERE expires<=?', (int(now),))
        self.db.execute('DELETE FROM gimps_lease_receipts WHERE expires<=?', (int(now),))
        if row[0] != token:
            self.jobs.pop(token, None)
            return {'available':False,'engine':'gimps','reason':'task-leased','retry_ms':5000}
        return job

    def submit(self, token, proof):
        require_network()
        with self.lock:
            completed = self.db.execute("SELECT proof_digest,receipt FROM gimps_lease_receipts WHERE token=? AND submitter=? AND (? IS NULL OR network_id=?) AND expires>?",
                                        (token, self.submitter, self.expected_network, self.expected_network, int(time.time()))).fetchone() if isinstance(token, str) else None
            if completed:
                if not isinstance(proof, dict) or not self.governor.check_proof_size(proof) or hashlib.sha256(encoded(proof)).hexdigest() != completed[0]:
                    raise ProtocolError('INVALID_PROOF', 'completed lease proof mismatch')
                return dict(strict_json(completed[1]), duplicate=True)
            job = self._get_active_job(token)
            if not job or job['expires'] <= time.time():
                raise ProtocolError('STALE_JOB', 'native GIMPS job expired')
            if not isinstance(proof, dict) or not self.governor.check_proof_size(proof):
                raise ProtocolError('INVALID_PROOF', 'native bounded GIMPS proof required')

            schema = proof.get('schema')
            p = job['exponent']
            if proof.get('exponent') != p:
                raise ProtocolError('INVALID_PROOF', 'exponent mismatch')

            if not self.governor.check_exponent_capacity(p):
                raise ProtocolError('LIMIT_EXCEEDED', f'exponent {p} exceeds node native memory capacity ({self.governor.max_native_exponent})')

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

            problem = job['network_id'] + ':' + self.submitter + ':' + job['engine_id'] + ':' + job['problem_id']
            previous = self.db.execute('SELECT operation,nonce,result FROM submissions WHERE problem=?', (problem,)).fetchone()
            if previous and previous[2] and strict_json(previous[2]).get('accepted') is True:
                return dict(strict_json(previous[2]), duplicate=True)
            if previous:
                result = strict_json(previous[2]) if previous[2] else self.recover(problem, previous[0])
            else:
                operation = 'web-gimps-' + hashlib.sha256((job['network_id'] + problem + self.submitter).encode()).hexdigest()[:32] + '-' + hashlib.sha256(encoded(proof)).hexdigest()[:16]
                plan = self.client.call('operation.prepare', {
                    'operation_id': operation,
                    'action': 'compute.submit',
                    'resource': 'compute:' + job['engine_id'],
                    'arguments': {'engine_id': job['engine_id'], 'problem_id': job['problem_id'], 'proof_data': proof},
                    'expected_revision': None
                })
                with self.db:
                    self.db.execute('INSERT OR IGNORE INTO submissions VALUES (?,?,?,NULL)', (problem, operation, encoded(proof).decode()))
                result = self.client.call('operation.commit', {'operation_id': operation, 'plan_digest': plan['plan_digest']})

            if result.get('state') != 'committed':
                raise ProtocolError('RESULT_UNKNOWN', 'native GIMPS submission awaits reconciliation')


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
                self.db.execute('INSERT OR REPLACE INTO gimps_lease_receipts VALUES (?,?,?,?,?,?)',
                                (token, self.submitter, job['network_id'], hashlib.sha256(encoded(proof)).hexdigest(), encoded(receipt), job['expires']))
                self.db.execute('DELETE FROM gimps_leases WHERE token=?', (token,))
                self.db.execute('DELETE FROM gimps_checkpoints WHERE task_id=?', (problem,))
            self.jobs.pop(token, None)
            return dict(receipt, duplicate=False)

    def save_checkpoint(self, token, checkpoint_data):
        """Worker periodic checkpoint saver."""
        require_network()
        with self.lock:
            job = self._get_active_job(token)
            if not job or job['expires'] <= time.time():
                raise ProtocolError('STALE_JOB', 'native GIMPS job expired')
            if not self.governor.check_checkpoint_size(checkpoint_data):
                raise ProtocolError('LIMIT_EXCEEDED', 'checkpoint payload too large')
            task_id = job['network_id'] + ':' + self.submitter + ':' + job['engine_id'] + ':' + job['problem_id']
            iteration = checkpoint_data.get('iteration', 0) if isinstance(checkpoint_data, dict) else 0
            if type(iteration) is not int or not 0 <= iteration <= job['exponent']:
                raise ProtocolError('INVALID_CHECKPOINT', 'bounded checkpoint iteration required')
            self.checkpoints.save_checkpoint(task_id, job['engine_id'], job['exponent'], self.submitter, iteration, checkpoint_data)
            with self.db:
                self.db.execute("UPDATE gimps_leases SET checkpoint=?, updated_at=? WHERE token=?",
                               (json.dumps(checkpoint_data), int(time.time()), token))
            return {'saved': True, 'exponent': job['exponent'], 'iteration': iteration}

    def heartbeat(self, token, progress_pct=None, checkpoint_data=None):
        """Worker heartbeat renewal for long-running compute lease."""
        require_network()
        with self.lock:
            job = self._get_active_job(token)
            if not job:
                raise ProtocolError('STALE_JOB', 'native GIMPS job not found')
            now = time.time()
            new_expires = int(now) + 120
            task_id = job['network_id'] + ':' + self.submitter + ':' + job['engine_id'] + ':' + job['problem_id']
            iteration = checkpoint_data.get('iteration', 0) if isinstance(checkpoint_data, dict) else 0
            if checkpoint_data:
                if not self.governor.check_checkpoint_size(checkpoint_data):
                    raise ProtocolError('LIMIT_EXCEEDED', 'checkpoint payload too large')
                self.checkpoints.save_checkpoint(task_id, job['engine_id'], job['exponent'], self.submitter, iteration, checkpoint_data)
            with self.db:
                self.db.execute("UPDATE gimps_leases SET expires=?, checkpoint=?, updated_at=? WHERE token=?",
                               (new_expires, json.dumps(checkpoint_data) if checkpoint_data is not None else json.dumps(job['checkpoint']) if job.get('checkpoint') is not None else None, int(now), token))
            job['expires'] = new_expires
            return {'renewed': True, 'exponent': job['exponent'], 'expires': new_expires, 'iteration': iteration}

    def pause(self, token, checkpoint_data=None):
        """Pause active task and preserve checkpoint."""
        require_network()
        with self.lock:
            job = self._get_active_job(token)
            if not job:
                raise ProtocolError('STALE_JOB', 'native GIMPS job not found')
            task_id = job['network_id'] + ':' + self.submitter + ':' + job['engine_id'] + ':' + job['problem_id']
            if checkpoint_data:
                iteration = checkpoint_data.get('iteration', 0) if isinstance(checkpoint_data, dict) else 0
                self.checkpoints.save_checkpoint(task_id, job['engine_id'], job['exponent'], self.submitter, iteration, checkpoint_data)
                with self.db:
                    self.db.execute("UPDATE gimps_leases SET checkpoint=?, updated_at=? WHERE token=?",
                                   (json.dumps(checkpoint_data), int(time.time()), token))
            return {'paused': True, 'exponent': job['exponent']}

    def resume(self, exponent, worker_id=None):
        """Resume paused task and return checkpoint."""
        require_network()
        with self.lock:
            if type(exponent) is not int or not 2 <= exponent <= self.governor.max_native_exponent:
                raise ProtocolError('INVALID_JOB', 'bounded resume exponent required')
            row = self.db.execute('SELECT network_id,engine_id FROM gimps_leases WHERE exponent=? AND submitter=? AND (? IS NULL OR network_id=?) AND expires>? ORDER BY updated_at DESC LIMIT 1',
                                  (exponent, self.submitter, self.expected_network, self.expected_network, int(time.time()))).fetchone()
            chk = self.checkpoints.load_checkpoint(row[0] + ':' + self.submitter + ':' + row[1] + ':' + str(exponent)) if row else None
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

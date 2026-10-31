"""Durable Saga coordinator. Native Providers retain final execution authority."""
import sqlite3
import time
import secrets
from pathlib import Path

from .client import NativeClient
from .protocol import ProtocolError, encoded, identifier, strict_json, make_private
from ._runtime import OPERATIONS


class WorkflowJournal:
    def __init__(self, path, read_only=False):
        path = Path(path).absolute()
        self.read_only = read_only
        if path.is_symlink():
            raise ProtocolError("UNSAFE_FILE", "workflow journal cannot be a symlink")
        if not read_only: path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        existed = path.exists()
        if existed:
            from .protocol import secure_read
            secure_read(path, 64 * 1024 * 1024)
        if read_only:
            if not existed: raise ProtocolError("WORKFLOW_NOT_FOUND", "workflow journal does not exist")
            self.db = sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=5)
            return
        self.db = sqlite3.connect(path, timeout=5)
        if not existed: make_private(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS workflows (id TEXT PRIMARY KEY, digest TEXT NOT NULL, manifest TEXT NOT NULL, state TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS steps (workflow_id TEXT NOT NULL, step_id TEXT NOT NULL, state TEXT NOT NULL, native_plan TEXT, result TEXT, PRIMARY KEY(workflow_id,step_id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS attempts (workflow_id TEXT PRIMARY KEY,owner TEXT NOT NULL,expires INTEGER NOT NULL)")
        self.db.commit()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def plan(self, manifest, federation):
        if self.read_only: raise ProtocolError("MUTATION_DISABLED", "workflow journal is read-only")
        if (not isinstance(manifest, dict) or set(manifest) != {"schema", "workflow_id", "steps"} or
                manifest["schema"] != "ziokt.workflow.v1" or
                not isinstance(manifest["steps"], list) or not 1 <= len(manifest["steps"]) <= 32):
            raise ProtocolError("INVALID_WORKFLOW", "bounded fixed-operation workflow required")
        identifier(manifest["workflow_id"], "workflow_id")
        providers = {p["provider_id"]: p for p in federation["providers"]}
        seen = set()
        for step in manifest["steps"]:
            if not isinstance(step, dict) or set(step) != {"step_id", "provider_id", "action", "resource", "arguments", "expected_revision", "depends_on"}:
                raise ProtocolError("INVALID_WORKFLOW", "exact workflow step required")
            identifier(step["step_id"], "step_id")
            if not isinstance(step["provider_id"], str) or step["step_id"] in seen or step["provider_id"] not in providers:
                raise ProtocolError("INVALID_WORKFLOW", "unique step and known provider required")
            if (not isinstance(step["depends_on"], list) or len(step["depends_on"]) > 32 or
                    not all(isinstance(v, str) for v in step["depends_on"]) or len(set(step["depends_on"])) != len(step["depends_on"]) or any(v not in seen for v in step["depends_on"])):
                raise ProtocolError("INVALID_WORKFLOW", "steps must be in dependency order")
            project = providers[step["provider_id"]]["native_project"]
            if (not isinstance(step["action"], str) or step["action"] not in OPERATIONS[project] or
                    not isinstance(step["resource"], str) or not isinstance(step["arguments"], dict)):
                raise ProtocolError("INVALID_WORKFLOW", "native action does not belong to provider")
            seen.add(step["step_id"])
        from hashlib import sha256
        payload = encoded({"manifest": manifest, "federation_id": federation["federation_id"]})
        digest = "sha256:" + sha256(payload).hexdigest()
        previous = self.db.execute("SELECT digest FROM workflows WHERE id=?", (manifest["workflow_id"],)).fetchone()
        if previous:
            if previous[0] != digest:
                raise ProtocolError("IDEMPOTENCY_CONFLICT", "workflow identity cannot change its plan")
            return self.status(manifest["workflow_id"])
        with self.db:
            self.db.execute("INSERT INTO workflows VALUES (?,?,?,'planned')", (manifest["workflow_id"], digest, payload.decode()))
            self.db.executemany("INSERT INTO steps VALUES (?,?,'planned',NULL,NULL)", [(manifest["workflow_id"], s["step_id"]) for s in manifest["steps"]])
        return self.status(manifest["workflow_id"])

    def status(self, workflow_id):
        row = self.db.execute("SELECT digest,state FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        if row is None:
            raise ProtocolError("WORKFLOW_NOT_FOUND", "workflow not found")
        rows = self.db.execute("SELECT step_id,state,native_plan,result FROM steps WHERE workflow_id=? ORDER BY rowid", (workflow_id,)).fetchall()
        return {"workflow_id": workflow_id, "plan_digest": row[0], "state": row[1],
                "execution_semantics": "recoverable-steps", "global_atomicity": False,
                "steps": [{"step_id": r[0], "state": r[1], "native_plan": strict_json(r[2].encode()) if r[2] else None,
                           "result": strict_json(r[3].encode()) if r[3] else None} for r in rows]}

    def apply(self, workflow_id, federation, expected_digest, confirmed=False, leadership=None, guard=None):
        if self.read_only: raise ProtocolError("MUTATION_DISABLED", "workflow journal is read-only")
        if not confirmed or not federation["enabled"]:
            raise ProtocolError("APPROVAL_REQUIRED", "enabled federation and explicit reviewed-plan approval required")
        owner = secrets.token_hex(16)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            now = time.time_ns()//1_000_000
            active = self.db.execute("SELECT expires FROM attempts WHERE workflow_id=?", (workflow_id,)).fetchone()
            if active and active[0] > now: raise ProtocolError("WORKFLOW_BUSY", "another bounded coordinator attempt remains active")
            self.db.execute("INSERT OR REPLACE INTO attempts VALUES (?,?,?)", (workflow_id, owner, now+60000))
            self.db.commit()
        except BaseException:
            self.db.rollback(); raise
        try: return self._apply(workflow_id, federation, expected_digest, confirmed, leadership, owner, guard)
        finally:
            with self.db: self.db.execute("DELETE FROM attempts WHERE workflow_id=? AND owner=?", (workflow_id, owner))

    def _apply(self, workflow_id, federation, expected_digest, confirmed, leadership, owner, guard):
        row = self.db.execute("SELECT digest,manifest FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        if row is None or row[0] != expected_digest:
            raise ProtocolError("STALE_PLAN", "workflow digest mismatch")
        value = strict_json(row[1].encode())
        if value["federation_id"] != federation["federation_id"]:
            raise ProtocolError("SCOPE_MISMATCH", "workflow belongs to another federation")
        providers = {p["provider_id"]: p for p in federation["providers"]}
        with self.db:
            self.db.execute("UPDATE workflows SET state='applying' WHERE id=?", (workflow_id,))
        for step in value["manifest"]["steps"]:
            with self.db:
                updated = self.db.execute("UPDATE attempts SET expires=? WHERE workflow_id=? AND owner=? AND expires>?",
                    (time.time_ns()//1_000_000+60000, workflow_id, owner, time.time_ns()//1_000_000)).rowcount
                if updated != 1: raise ProtocolError("STALE_FENCE", "coordinator workflow attempt expired")
            step_id = step["step_id"]
            stored = self.db.execute("SELECT state,native_plan FROM steps WHERE workflow_id=? AND step_id=?", (workflow_id, step_id)).fetchone()
            if stored[0] == "committed":
                continue
            if any(self.db.execute("SELECT state FROM steps WHERE workflow_id=? AND step_id=?", (workflow_id, dep)).fetchone()[0] != "committed" for dep in step["depends_on"]):
                raise ProtocolError("DEPENDENCY_PENDING", "workflow dependencies not committed")
            from hashlib import sha256
            op_id = "wf-" + sha256((federation["federation_id"] + "\0" + workflow_id + "\0" + step_id + "\0" + step["provider_id"] + "\0" + row[0]).encode()).hexdigest()[:40]
            client = NativeClient(federation["federation_id"], providers[step["provider_id"]])
            try:
                if guard: guard()
                # Query first even when the coordinator died before persisting
                # its prepare response. The native operation ID is deterministic.
                try:
                    native = client.call("operation.status", {"operation_id": op_id})
                except ProtocolError as exc:
                    if exc.code != "OPERATION_NOT_FOUND":
                        raise
                    params = {"operation_id": op_id, **{k: step[k] for k in ("action", "resource", "arguments", "expected_revision")}}
                    if leadership:
                        authority, leader_owner, key = leadership
                        authority.acquire(federation["federation_id"], leader_owner)
                        params["fence"] = authority.token(federation["federation_id"], leader_owner, step["provider_id"], params, key)
                    native = client.call("operation.prepare", params)
                if native["state"] == "unknown":
                    native = client.call("operation.reconcile", {"operation_id": op_id})
                with self.db:
                    self.db.execute("UPDATE steps SET state=?,native_plan=? WHERE workflow_id=? AND step_id=?", (native["state"], encoded(native).decode(), workflow_id, step_id))
                if native["state"] == "prepared":
                    if guard: guard()
                    native = client.call("operation.commit", {"operation_id": op_id, "plan_digest": native["plan_digest"]})
                if native["state"] != "committed":
                    raise ProtocolError("RESULT_UNKNOWN", "native step did not commit")
                with self.db:
                    self.db.execute("UPDATE steps SET state='committed',result=? WHERE workflow_id=? AND step_id=?", (encoded(native).decode(), workflow_id, step_id))
            except ProtocolError as exc:
                state = "unknown" if exc.code in {"RESULT_UNKNOWN", "PROVIDER_TIMEOUT", "OPERATION_IN_PROGRESS"} else "manual_required"
                with self.db:
                    self.db.execute("UPDATE workflows SET state=? WHERE id=?", (state, workflow_id))
                    self.db.execute("UPDATE steps SET state=?,result=? WHERE workflow_id=? AND step_id=?", (state, encoded({"error": exc.code}).decode(), workflow_id, step_id))
                raise
        with self.db:
            self.db.execute("UPDATE workflows SET state='committed' WHERE id=?", (workflow_id,))
        return self.status(workflow_id)

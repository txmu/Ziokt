"""Durable Saga coordinator. Native Providers retain final execution authority."""
import sqlite3
import time
from pathlib import Path

from .client import NativeClient
from .protocol import ProtocolError, encoded, identifier, strict_json


class WorkflowJournal:
    def __init__(self, path):
        path = Path(path)
        if path.is_symlink():
            raise ProtocolError("UNSAFE_FILE", "workflow journal cannot be a symlink")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists():
            from .protocol import secure_read
            secure_read(path, 64 * 1024 * 1024)
        self.db = sqlite3.connect(path, timeout=5)
        path.chmod(0o600)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS workflows (id TEXT PRIMARY KEY, digest TEXT NOT NULL, manifest TEXT NOT NULL, state TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS steps (workflow_id TEXT NOT NULL, step_id TEXT NOT NULL, state TEXT NOT NULL, native_plan TEXT, result TEXT, PRIMARY KEY(workflow_id,step_id))")
        self.db.commit()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def plan(self, manifest, federation):
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
            if step["step_id"] in seen or step["provider_id"] not in providers:
                raise ProtocolError("INVALID_WORKFLOW", "unique step and known provider required")
            if not isinstance(step["depends_on"], list) or any(v not in seen for v in step["depends_on"]):
                raise ProtocolError("INVALID_WORKFLOW", "steps must be in dependency order")
            project = providers[step["provider_id"]]["native_project"]
            if step["action"] not in ({"service.stop"} if project == "shadow6" else {"artifact.stage"}):
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
                "steps": [{"step_id": r[0], "state": r[1], "native_plan": strict_json(r[2].encode()) if r[2] else None,
                           "result": strict_json(r[3].encode()) if r[3] else None} for r in rows]}

    def apply(self, workflow_id, federation, expected_digest, confirmed=False):
        if not confirmed or not federation["enabled"]:
            raise ProtocolError("APPROVAL_REQUIRED", "enabled federation and explicit reviewed-plan approval required")
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
            step_id = step["step_id"]
            stored = self.db.execute("SELECT state,native_plan FROM steps WHERE workflow_id=? AND step_id=?", (workflow_id, step_id)).fetchone()
            if stored[0] == "committed":
                continue
            if any(self.db.execute("SELECT state FROM steps WHERE workflow_id=? AND step_id=?", (workflow_id, dep)).fetchone()[0] != "committed" for dep in step["depends_on"]):
                raise ProtocolError("DEPENDENCY_PENDING", "workflow dependencies not committed")
            from hashlib import sha256
            op_id = "wf-" + sha256((workflow_id + "\0" + step_id).encode()).hexdigest()[:40]
            client = NativeClient(federation["federation_id"], providers[step["provider_id"]])
            try:
                # Query first even when the coordinator died before persisting
                # its prepare response. The native operation ID is deterministic.
                try:
                    native = client.call("operation.status", {"operation_id": op_id})
                except ProtocolError as exc:
                    if exc.code != "OPERATION_NOT_FOUND":
                        raise
                    native = client.call("operation.prepare", {"operation_id": op_id, **{k: step[k] for k in ("action", "resource", "arguments", "expected_revision")}})
                if native["state"] == "unknown":
                    native = client.call("operation.reconcile", {"operation_id": op_id})
                with self.db:
                    self.db.execute("UPDATE steps SET state=?,native_plan=? WHERE workflow_id=? AND step_id=?", (native["state"], encoded(native).decode(), workflow_id, step_id))
                if native["state"] == "prepared":
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

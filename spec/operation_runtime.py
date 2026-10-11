"""Local native operation journal. Exact actions, durable intents, no shell.

This is not distributed ACID. A crash after native mutation leaves unknown;
status reconciles supported postconditions before any retry.
"""
import base64
import sqlite3

OPERATIONS = {"shadow6": {"service.stop"}, "corium": {"artifact.stage"}}


def operation_directory(provider, root, network):
    if provider == "shadow6":
        return Path.home() / ".config/shadow6/ziokt-state"
    return root / "var/lib/corix/networks" / network / "ziokt"


def private_mkdir(path):
    path = Path(path)
    if not path.exists():
        path.mkdir(mode=0o700, parents=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077):
        fail("UNSAFE_FILE", "private native operation directory required")
    return path


def operation_db(provider, root, network, create=False, write=False):
    directory = operation_directory(provider, root, network)
    path = directory / "operations.sqlite"
    if not create and not path.exists():
        fail("OPERATION_NOT_FOUND", "operation journal does not exist")
    if create:
        private_mkdir(directory)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
    secure_read(path, 64 * 1024 * 1024)
    db = sqlite3.connect(path if create or write else path.as_uri() + "?mode=ro", uri=not (create or write), timeout=5)
    if create or write:
        db.execute("PRAGMA synchronous=FULL")
    if create:
        db.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, request_digest TEXT NOT NULL, plan TEXT NOT NULL, state TEXT NOT NULL, result TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS outbox (seq INTEGER PRIMARY KEY AUTOINCREMENT, operation_id TEXT NOT NULL, state TEXT NOT NULL, evidence TEXT NOT NULL, UNIQUE(operation_id,state))")
        db.commit()
    return db


def operation_view(row):
    plan = strict_json(row[2].encode())
    return {"operation_id": row[0], "plan_digest": "sha256:" + digest(plan),
            "action": plan["action"], "resource": plan["resource"],
            "state": row[3], "expires_at_ms": plan["expires_at_ms"],
            "result": strict_json(row[4].encode()) if row[4] else None}


def native_registry(root):
    sys.path.insert(0, str(root / "Deployment"))
    from service_registry import ServiceRegistry
    from core_catalog import CoreCatalog
    return ServiceRegistry(catalog=CoreCatalog(root))


def operation_preflight(provider, root, network, params, config):
    action, resource, args = params["action"], params["resource"], params["arguments"]
    if action not in OPERATIONS[provider] or action not in config["allowed_operations"]:
        fail("POLICY_DENIED", "native action is not allowed")
    if resource not in config["allowed_resources"] and "*" not in config["allowed_resources"]:
        fail("POLICY_DENIED", "native resource is not allowed")
    if action == "service.stop":
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._-]{0,63}", resource) or args:
            fail("INVALID_PARAMS", "fixed named-service stop required")
        registry = native_registry(root)
        if resource not in registry.services:
            fail("NATIVE_STATE_UNAVAILABLE", "named service does not exist")
        from service_registry import digest as native_digest, encoded as native_encode
        revision = native_digest(native_encode(registry.services[resource]))
        if revision != params["expected_revision"]:
            fail("STALE_PLAN", "native service revision changed")
        item = registry.services[resource]
        return {"core_binding": digest(item.get("coreBinding")), "profile_binding": digest(item.get("profileBinding")),
                "context": digest(item.get("protocolContext")), "lock": (item.get("deploymentLock") or {}).get("digest")}
    else:
        if set(args) != {"data_base64"} or not re.fullmatch(r"sha256:[a-f0-9]{64}", resource):
            fail("INVALID_PARAMS", "content-addressed native artifact required")
        try:
            data = base64.b64decode(args["data_base64"], validate=True)
        except (ValueError, TypeError):
            fail("INVALID_PARAMS", "bounded base64 content required")
        if len(data) > 6144 or "sha256:" + hashlib.sha256(data).hexdigest() != resource:
            fail("ARTIFACT_DIGEST_MISMATCH", "content digest or control budget mismatch")
        if params["expected_revision"] is not None:
            fail("INVALID_PARAMS", "artifact staging requires null expected_revision")
        dht = root / "var/lib/corix/p2p/dht.db"
        if not dht.is_file() or dht.is_symlink():
            fail("NATIVE_STATE_UNAVAILABLE", "native Corium content database not initialized")
        with sqlite3.connect(dht.as_uri() + "?mode=ro", uri=True) as db:
            db.execute("SELECT hash,file_path,offset,size FROM local_chunks LIMIT 1").fetchall()
        return {"artifact_digest": resource}


def operation_execute(provider, root, network, plan):
    resource = plan["resource"]
    if plan["action"] == "service.stop":
        registry = native_registry(root)
        registry.ziokt_stop(resource, expected_revision=plan["expected_revision"])
        return {"native_id": resource, "postcondition": "stopped"}
    content = base64.b64decode(plan["arguments"]["data_base64"], validate=True)
    directory = root / "var/lib/corix/p2p/objects/ziokt"
    private_mkdir(directory)
    target = directory / resource.removeprefix("sha256:")
    existed = target.exists()
    if existed:
        if hashlib.sha256(secure_read(target, 6144, private=None)).hexdigest() != resource[7:]:
            fail("ARTIFACT_DIGEST_MISMATCH", "existing native object was changed")
    else:
        temporary = directory / (".stage-" + plan["operation_id"])
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content); stream.flush(); os.fsync(stream.fileno())
            # Never replace a concurrently published native object.
            os.link(temporary, target)
        except FileExistsError:
            if hashlib.sha256(secure_read(target, 6144, private=None)).hexdigest() != resource[7:]:
                fail("ARTIFACT_DIGEST_MISMATCH", "concurrent native object conflict")
        finally:
            temporary.unlink(missing_ok=True)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    dht = root / "var/lib/corix/p2p/dht.db"
    with sqlite3.connect(dht) as db:
        previous = db.execute("SELECT file_path,offset,size FROM local_chunks WHERE hash=?", (resource[7:],)).fetchone()
        if previous and tuple(previous) != (str(target), 0, len(content)):
            # Do not steal another native provider's existing same-content record.
            path = Path(previous[0])
            if previous[1] != 0 or previous[2] != len(content) or hashlib.sha256(secure_read(path, 6144, private=None)).hexdigest() != resource[7:]:
                fail("NATIVE_STATE_CONFLICT", "native content registration conflicts")
        else:
            db.execute("INSERT OR REPLACE INTO local_chunks VALUES (?,?,0,?)", (resource[7:], str(target), len(content)))
    return {"digest": resource, "native_registered": True, "created": not existed,
            "compensation": "manual-content-retention-review"}


def operation_reconcile(provider, root, network, plan):
    if plan["action"] == "service.stop":
        registry = native_registry(root)
        item = registry.services.get(plan["resource"])
        if item and item["state"] == "stopped":
            evidence = {"core_binding": digest(item.get("coreBinding")), "profile_binding": digest(item.get("profileBinding")),
                        "context": digest(item.get("protocolContext")), "lock": (item.get("deploymentLock") or {}).get("digest")}
            if evidence != plan["binding_evidence"]:
                fail("STALE_PLAN", "native binding changed during interrupted operation")
            return {"native_id": plan["resource"], "postcondition": "stopped", "reconciled": True}
        return None
    target = root / "var/lib/corix/p2p/objects/ziokt" / plan["resource"][7:]
    if target.is_file() and not target.is_symlink() and hashlib.sha256(secure_read(target, 6144, private=None)).hexdigest() == plan["resource"][7:]:
        # Resume the fixed content registration only; hashing prevents a changed
        # payload from being mistaken for the interrupted operation.
        return {**operation_execute(provider, root, network, plan), "reconciled": True}
    return None


def operation_dispatch(provider, root, network, config, method, params):
    if method in {"operation.prepare", "operation.commit", "operation.abort", "operation.reconcile"} and not config["allow_mutations"]:
        fail("MUTATION_DISABLED", "native mutations are disabled")
    if method == "events.list":
        try:
            db = operation_db(provider, root, network)
        except ProtocolError as exc:
            if exc.code == "OPERATION_NOT_FOUND":
                return {"events": [], "next_seq": params.get("after_seq", 0)}
            raise
        try:
            rows = db.execute("SELECT seq,operation_id,state,evidence FROM outbox WHERE seq>? ORDER BY seq LIMIT ?",
                              (params.get("after_seq", 0), params.get("limit", 50))).fetchall()
            return {"events": [{"seq": r[0], "operation_id": r[1], "state": r[2], "evidence": strict_json(r[3].encode())} for r in rows],
                    "next_seq": rows[-1][0] if rows else params.get("after_seq", 0)}
        finally:
            db.close()
    identifier(params.get("operation_id"), "operation_id")
    db = operation_db(provider, root, network, create=method == "operation.prepare", write=method in {"operation.commit", "operation.abort", "operation.reconcile"})
    try:
        if method != "operation.status":
            db.execute("BEGIN IMMEDIATE")
        if method == "operation.prepare":
            if set(params) != {"operation_id", "action", "resource", "arguments", "expected_revision"}:
                fail("INVALID_PARAMS", "exact native operation plan required")
            if not isinstance(params["action"], str) or not isinstance(params["resource"], str) or not isinstance(params["arguments"], dict):
                fail("INVALID_PARAMS", "typed native action required")
            if params["expected_revision"] is not None and not re.fullmatch(r"sha256:[a-f0-9]{64}", str(params["expected_revision"])):
                fail("INVALID_PARAMS", "native revision digest required")
            request_digest = digest(params)
            row = db.execute("SELECT * FROM operations WHERE id=?", (params["operation_id"],)).fetchone()
            if row:
                if row[1] != request_digest:
                    fail("IDEMPOTENCY_CONFLICT", "operation ID cannot change its request")
                return operation_view(row)
            evidence = operation_preflight(provider, root, network, params, config)
            if db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] >= 4096:
                fail("JOURNAL_LIMIT", "native operation journal requires explicit archival")
            plan = {**params, "federation_id": config["federation_id"], "provider_id": config["provider_id"],
                    "expires_at_ms": time.time_ns() // 1_000_000 + 30_000, "binding_evidence": evidence}
            with db:
                db.execute("INSERT INTO operations VALUES (?,?,?,'prepared',NULL)", (params["operation_id"], request_digest, encoded(plan).decode()))
            return operation_view(db.execute("SELECT * FROM operations WHERE id=?", (params["operation_id"],)).fetchone())
        row = db.execute("SELECT * FROM operations WHERE id=?", (params["operation_id"],)).fetchone()
        if row is None:
            fail("OPERATION_NOT_FOUND", "native operation not found")
        plan = strict_json(row[2].encode())
        if plan["federation_id"] != config["federation_id"] or plan["provider_id"] != config["provider_id"]:
            fail("SCOPE_MISMATCH", "operation belongs to another provider scope")
        if method in {"operation.status", "operation.reconcile"}:
            if row[3] == "unknown" and method == "operation.reconcile":
                if (plan["action"] not in config["allowed_operations"] or
                        (plan["resource"] not in config["allowed_resources"] and "*" not in config["allowed_resources"])):
                    fail("POLICY_DENIED", "current native policy no longer allows reconciliation")
                if time.time_ns() // 1_000_000 < plan["expires_at_ms"]:
                    fail("OPERATION_IN_PROGRESS", "wait for execution lease before reconciliation")
                if provider == "corium":
                    operation_preflight(provider, root, network, plan, config)
                result = operation_reconcile(provider, root, network, plan)
                if result:
                    with db:
                        db.execute("UPDATE operations SET state='committed',result=? WHERE id=? AND state='unknown'", (encoded(result).decode(), row[0]))
                        db.execute("INSERT OR IGNORE INTO outbox(operation_id,state,evidence) VALUES (?,'committed',?)", (row[0], encoded(result).decode()))
            return operation_view(db.execute("SELECT * FROM operations WHERE id=?", (row[0],)).fetchone())
        if params.get("plan_digest") != "sha256:" + digest(plan):
            fail("STALE_PLAN", "native plan digest mismatch")
        if method == "operation.abort":
            if row[3] != "prepared":
                fail("OPERATION_CONFLICT", "only a prepared operation can be aborted")
            with db:
                db.execute("UPDATE operations SET state='aborted' WHERE id=?", (row[0],))
            return operation_view(db.execute("SELECT * FROM operations WHERE id=?", (row[0],)).fetchone())
        if row[3] == "committed":
            return operation_view(row)
        if row[3] != "prepared":
            fail("RESULT_UNKNOWN", "query native status before deciding whether to retry")
        if time.time_ns() // 1_000_000 >= plan["expires_at_ms"]:
            fail("STALE_PLAN", "native prepare lease expired")
        operation_preflight(provider, root, network, plan, config)
        with db:
            changed = db.execute("UPDATE operations SET state='unknown' WHERE id=? AND state='prepared'", (row[0],)).rowcount
            if changed != 1:
                fail("OPERATION_CONFLICT", "operation already claimed")
        result = operation_execute(provider, root, network, plan)
        with db:
            db.execute("UPDATE operations SET state='committed',result=? WHERE id=?", (encoded(result).decode(), row[0]))
            db.execute("INSERT OR IGNORE INTO outbox(operation_id,state,evidence) VALUES (?,'committed',?)", (row[0], encoded(result).decode()))
        return operation_view(db.execute("SELECT * FROM operations WHERE id=?", (row[0],)).fetchone())
    except sqlite3.Error:
        fail("JOURNAL_UNAVAILABLE", "native operation journal is busy or invalid")
    finally:
        db.close()

"""Local native operation journal. Exact actions, durable intents, no shell.

This is not distributed ACID. A crash after native mutation leaves unknown;
explicit reconcile checks supported postconditions before any retry.
"""
import base64
import sqlite3
from contextlib import closing

OPERATIONS = {"shadow6": {"service.stop", "service.run", "package.install", "package.activate", "recovery.checkpoint", "recovery.restore"},
              "corium": {"artifact.stage", "wiki.create", "snapshot.create", "strata.create", "chain.mine", "compute.run", "identity.register", "content.publish", "zkn.transfer", "zkn.gift", "zkc.issue", "recovery.checkpoint", "recovery.restore"}}


def operation_directory(provider, root, network):
    if provider == "shadow6":
        return Path.home() / ".config/shadow6/ziokt-state"
    return root / "var/lib/corix/networks" / network / "ziokt"


def native_descriptor_main(args):
    """Only the recorded in-progress native action can reach Bash business code."""
    root, network, op_id = Path(args[0]).absolute(), args[1], args[2]
    identifier(network, "network"); identifier(op_id, "operation_id")
    config = load_config("corium", root/"etc/corix/networks"/network/"corix.conf")
    if not config["enabled"] or not config["allow_mutations"]:
        fail("MUTATION_DISABLED", "native Corium mutations are disabled")
    db = operation_db("corium", root, network)
    try:
        row = db.execute("SELECT * FROM operations WHERE id=?", (op_id,)).fetchone()
        if row is None or row[3] != "unknown":
            fail("POLICY_DENIED", "recorded native execution intent required")
        plan = strict_json(row[2].encode())
        fence_admit(db, config, plan, existing=True)
        if (plan["federation_id"] != config["federation_id"] or plan["provider_id"] != config["provider_id"] or
                time.time_ns()//1_000_000 >= plan["expires_at_ms"]):
            fail("STALE_PLAN", "native execution scope or lease changed")
        if operation_preflight("corium", root, network, plan, config) != plan["binding_evidence"]:
            fail("STALE_PLAN", "native business evidence changed before dispatch")
        print(encoded(plan).decode())
        return 0
    finally:
        db.close()


def private_mkdir(path):
    path = Path(path)
    if not path.exists():
        path.mkdir(mode=0o700, parents=True)
        make_private(path)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        fail("UNSAFE_FILE", "private native operation directory required")
    if os.name == "nt":
        fail("NATIVE_PLATFORM_UNSUPPORTED", "native operation journal requires native POSIX authority")
    if (info.st_uid != os.geteuid() or info.st_mode & 0o077):
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
        db.execute("CREATE TABLE IF NOT EXISTS coordinator (id INTEGER PRIMARY KEY CHECK(id=1), term INTEGER NOT NULL, busy_until INTEGER NOT NULL, operation_id TEXT)")
        db.commit()
    return db


def operation_view(row):
    plan = strict_json(row[2].encode())
    return {"operation_id": row[0], "plan_digest": "sha256:" + digest(plan),
            "action": plan["action"], "resource": plan["resource"],
            "state": row[3], "expires_at_ms": plan["expires_at_ms"],
            "result": strict_json(row[4].encode()) if row[4] else None}


def fence_admit(db, config, plan, existing=False):
    if "coordinator_public_key" not in config:
        if "fence" in plan: fail("POLICY_DENIED", "native coordinator trust must be explicitly configured")
        return
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    token = plan.get("fence")
    if not isinstance(token, dict) or set(token) != {"payload", "signature"}:
        fail("FENCE_REQUIRED", "signed native coordinator lease required")
    value = token["payload"]
    request = {k:v for k,v in plan.items() if k in {"operation_id", "action", "resource", "arguments", "expected_revision", "lease_ms"}}
    if (not isinstance(value, dict) or set(value) != {"federation_id", "provider_id", "operation_id", "request_digest", "term", "expires_at_ms"} or
            value["federation_id"] != config["federation_id"] or value["provider_id"] != config["provider_id"] or
            value["operation_id"] != plan["operation_id"] or value["request_digest"] != "sha256:"+digest(request) or
            type(value["term"]) is not int or not 1 <= value["term"] <= 2**53-1 or type(value["expires_at_ms"]) is not int or
            not time.time_ns()//1_000_000 < value["expires_at_ms"] <= time.time_ns()//1_000_000+30000):
        fail("STALE_FENCE", "native coordinator lease scope or validity rejected")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(config["coordinator_public_key"])).verify(
            bytes.fromhex(token["signature"]), b"Ziokt/fence/v1\n"+encoded(value))
    except (ValueError, TypeError, InvalidSignature): fail("STALE_FENCE", "native coordinator signature rejected")
    row = db.execute("SELECT term,busy_until,operation_id FROM coordinator WHERE id=1").fetchone()
    if row and (value["term"] < row[0] or (existing and value["term"] != row[0])):
        fail("STALE_FENCE", "native provider rejects superseded coordinator term")
    if row and row[1] > time.time_ns()//1_000_000 and row[2] != plan["operation_id"]:
        fail("OPERATION_IN_PROGRESS", "native provider execution lease remains active")
    if not existing:
        db.execute("INSERT OR REPLACE INTO coordinator VALUES (1,?,?,?)", (value["term"], row[1] if row else 0, row[2] if row else None))


def native_registry(root):
    sys.path.insert(0, str(root / "Deployment"))
    from service_registry import ServiceRegistry
    from core_catalog import CoreCatalog
    return ServiceRegistry(catalog=CoreCatalog(root))


def service_binding_fact(root,config,name):
    """Verify locked native materials; return no credentials or unscoped files."""
    sys.path.insert(0,str(root/'Deployment'))
    from service_registry import ServiceRegistry
    from core_catalog import CoreCatalog
    import service_runtime
    registry=ServiceRegistry(config.get('service_registry_file'),CoreCatalog(root))
    item=registry.inspect(name)
    if not item.get('deploymentLock'): fail('STALE_PLAN','locked named Broker required')
    material=registry._material(name)
    from service_registry import digest as native_digest,encoded as native_encoded
    if native_digest(native_encoded(material))!=item['deploymentLock']['digest']:fail('STALE_PLAN','native Broker material changed')
    role=item['protocolContext']['role']
    if role not in {'broker','all'}:fail('INVALID_PARAMS','Broker role required for Virtual Broker route')
    content=secure_read(item['coreBinding']['config']['config_path'])
    native=strict_json(content)
    endpoints=[]
    def scan(value):
        if isinstance(value,dict):
            for key,child in value.items():
                if key in {'listen_addr','listen_address','listen'} and isinstance(child,str): endpoints.append(child)
                if key=='listen_host' and type(value.get('listen_port')) is int:
                    endpoints.append(('['+child+']' if ':' in child else child)+':'+str(value['listen_port']))
                scan(child)
        elif isinstance(value,list):
            for child in value:scan(child)
    if item.get('privacy')=='envelope':
        fields=service_runtime.parse_envelope(secure_read(item['spec']['envelope_config']))
        endpoints=[fields['listen']]
    else:scan(native.get('broker',native))
    return {'schema':'ziokt.native-broker-binding.v1','service_name':name,'core':item['coreBinding']['core'],
        'profile':item['profileBinding']['profile'],'privacy':item['privacy'],'lock_digest':item['deploymentLock']['digest'],
        'entry_endpoints':endpoints,'runtime_ready':item.get('state') in {'running','degraded'} and service_runtime.alive(item.get('runtime',{})),
        'assurance':'native-locked-material','wire_translation':False}


def native_database(path):
    """Validate an owned native database without reading its whole history."""
    path = Path(path).absolute()
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or (os.name != "nt" and before.st_uid != os.geteuid()):
        fail("UNSAFE_FILE", "owned regular native database required")
    fd = os.open(path, os.O_RDONLY|getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino) or os.read(fd, 16) != b"SQLite format 3\x00":
            fail("NATIVE_STATE_UNAVAILABLE", "native database header or identity changed")
    finally: os.close(fd)
    return sqlite3.connect(path.as_uri()+"?mode=ro", uri=True)


def corium_db(root, network, name):
    return native_database(root / "var/lib/corix/networks" / network / name)


def corium_identity(root, network):
    public = secure_read(root/"etc/corix/networks"/network/"identity.key.pub", 16384, private=None).decode().rstrip("\n")
    return hashlib.sha256(public.encode()).hexdigest()


def wiki_receipt(root, network, plan):
    group, slug = plan["resource"].split("/", 1)
    content = hashlib.sha256(plan["arguments"]["content"].encode()).hexdigest()
    with closing(corium_db(root, network, "blockchain/chain.db")) as db:
        for tx_hash, public, payload, height in db.execute("SELECT hash,public_key,data,block_height FROM transactions WHERE type='wiki_page_create' ORDER BY timestamp DESC LIMIT 4096"):
            value = strict_json(payload.encode())
            manifest_hash = value.get("content_hash")
            if not isinstance(manifest_hash, str) or not re.fullmatch("[a-f0-9]{64}", manifest_hash): continue
            path = root/"var/lib/corix/p2p/objects"/manifest_hash
            if not path.is_file(): continue
            raw = secure_read(path, 65536, private=None)
            if hashlib.sha256(raw).hexdigest() != manifest_hash: continue
            manifest = strict_json(raw)
            if manifest.get("size") != len(plan["arguments"]["content"].encode()) or manifest.get("chunks") != [content]: continue
            if (hashlib.sha256(public.rstrip("\n").encode()).hexdigest() == plan["binding_evidence"].get("author") and value.get("group_id") == group and value.get("page_slug") == slug and
                    value.get("commit_message") == plan["arguments"]["message"]):
                return {"native_action": "wiki.create", "resource": plan["resource"], "transaction_hash": tx_hash,
                        "phase": "pending-native-consensus" if height is None else "on-chain", "application_ready": height is not None}
    return None


def operation_preflight(provider, root, network, params, config):
    action, resource, args = params["action"], params["resource"], params["arguments"]
    if action not in OPERATIONS[provider] or action not in config["allowed_operations"]:
        fail("POLICY_DENIED", "native action is not allowed")
    if resource not in config["allowed_resources"] and "*" not in config["allowed_resources"]:
        fail("POLICY_DENIED", "native resource is not allowed")
    if action.startswith("recovery."):
        return recovery_preflight(provider, root, network, params, config)
    if action == "compute.run":
        return compute_preflight(root, network, params, config)
    if action in {'identity.register','content.publish','zkn.transfer','zkn.gift','zkc.issue'}:
        return asset_preflight(root,network,params,config)
    if action in {"service.stop", "service.run"}:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._-]{0,63}", resource) or args:
            fail("INVALID_PARAMS", "fixed named-service lifecycle operation required")
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
    elif action in {"package.install", "package.activate"}:
        sys.path.insert(0, str(root / "Package-Manager"))
        from shadow6_pkg import verify_package
        match = re.fullmatch(r"(plugin|app|crosed-mod)/([a-z0-9][a-z0-9._-]{0,63})@([0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?)", resource)
        if match is None or not all(k in config for k in ("package_root", "package_trust_file", "artifact_root")):
            fail("INVALID_PARAMS", "fixed native package roots and exact selector required")
        if params["expected_revision"] is not None:
            fail("INVALID_PARAMS", "package admission uses immutable native signature evidence")
        kind, name, version = match.groups()
        if action == "package.install":
            if set(args) != {"artifact_digest"} or not re.fullmatch(r"sha256:[a-f0-9]{64}", str(args["artifact_digest"])):
                fail("INVALID_PARAMS", "exact native package artifact digest required")
            source = Path(config["artifact_root"])/args["artifact_digest"][7:]
            if hashlib.sha256(secure_read(source, 64*1024*1024, private=None)).hexdigest() != args["artifact_digest"][7:]:
                fail("ARTIFACT_DIGEST_MISMATCH", "native package artifact changed")
        else:
            if args: fail("INVALID_PARAMS", "native activation accepts no extra arguments")
            source = Path(config["package_root"])/kind/name/"versions"/version
        manifest, package = verify_package(source, Path(config["package_trust_file"]))
        try:
            if (manifest["kind"], manifest["id"], manifest["version"]) != (kind, name, version):
                fail("NATIVE_STATE_CONFLICT", "native signed package selector mismatch")
            return {"manifest_digest": "sha256:"+digest(manifest), "kind": kind, "id": name, "version": version}
        finally:
            package.close()
    elif action in {"wiki.create", "snapshot.create", "strata.create", "chain.mine"}:
        if params["expected_revision"] is not None:
            fail("INVALID_PARAMS", "native create/mine operation requires null expected_revision")
        if action == "wiki.create":
            if not re.fullmatch(r"[a-f0-9]{64}/[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", resource) or set(args) != {"content", "message"} or not all(isinstance(v, str) and 1 <= len(v.encode()) <= 8192 for v in args.values()):
                fail("INVALID_PARAMS", "bounded group/page and content/message required")
            author = corium_identity(root, network)
            group, slug = resource.split("/", 1)
            with closing(corium_db(root, network, "forum/forum.db")) as db:
                permissions = db.execute("SELECT permissions FROM acl_state WHERE acl_id=? AND grantee_id=?", (group, author)).fetchone()
                grants = strict_json(permissions[0].encode()) if permissions else None
                if not isinstance(grants, list) or not all(isinstance(v, str) for v in grants) or "member" not in grants:
                    fail("POLICY_DENIED", "native Wiki membership required")
                if db.execute("SELECT 1 FROM wiki_pages WHERE group_id=? AND slug=?", (group, slug)).fetchone():
                    fail("NATIVE_STATE_CONFLICT", "native Wiki page already exists")
            return {"native_action": action, "resource": resource, "network_id": network, "author": author}
        elif action == "snapshot.create":
            identifier(resource, "snapshot name")
            if args: fail("INVALID_PARAMS", "native snapshot accepts no extra arguments")
            target = root/"var/lib/corix/networks"/network/"snapshots"/resource
            if target.exists(): fail("NATIVE_STATE_CONFLICT", "native snapshot name already exists")
        elif action == "strata.create":
            identifier(resource, "Strata name")
            if set(args) != {"package_manager"} or args["package_manager"] not in {"apt", "pacman", "dnf", "portage"}:
                fail("INVALID_PARAMS", "known native package manager required")
            if os.geteuid() != 0: fail("ROOT_REQUIRED", "native Strata creation requires configured root authority")
        elif resource != "chain:" + network or args:
            fail("INVALID_PARAMS", "exact native chain mining scope required")
        if action == "chain.mine":
            with closing(corium_db(root, network, "blockchain/chain.db")) as db:
                tip = db.execute("SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1").fetchone()
            if not tip: fail("NATIVE_STATE_UNAVAILABLE", "native genesis required")
            return {"native_action": action, "resource": resource, "network_id": network, "height": tip[0], "block_hash": tip[1]}
        return {"native_action": action, "resource": resource, "network_id": network}
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
        with closing(sqlite3.connect(dht.as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("SELECT hash,file_path,offset,size FROM local_chunks LIMIT 1").fetchall()
        return {"artifact_digest": resource}


def operation_execute(provider, root, network, plan, config=None):
    resource = plan["resource"]
    if provider=='corium' and plan['action'] in {'zkn.gift','zkc.issue'}:
        if asset_preflight(root,network,plan,config)!=plan['binding_evidence']:
            fail('STALE_PLAN','private gift evidence changed')
        return asset_submit_gift(root,network,plan['arguments']['transaction'],'zkc_issue' if plan['action']=='zkc.issue' else 'zkn_private_transfer')
    if provider == "shadow6" and plan["action"].startswith("recovery."):
        return recovery_execute(provider, root, network, plan, config)
    if plan["action"] in {"service.stop", "service.run"}:
        registry = native_registry(root)
        if plan["action"] == "service.stop": registry.ziokt_stop(resource, expected_revision=plan["expected_revision"])
        else: registry.ziokt_run(resource, expected_revision=plan["expected_revision"])
        return {"native_id": resource, "postcondition": "stopped" if plan["action"] == "service.stop" else "running", "application_ready": False}
    if plan["action"] in {"package.install", "package.activate"}:
        sys.path.insert(0, str(root/"Package-Manager"))
        from shadow6_pkg import install_package, activate, verify_package
        evidence = plan["binding_evidence"]
        directory = Path(config["package_root"])/evidence["kind"]/evidence["id"]/"versions"/evidence["version"]
        if plan["action"] == "package.install":
            if not directory.exists():
                install_package(Path(config["artifact_root"])/plan["arguments"]["artifact_digest"][7:], Path(config["package_trust_file"]), Path(config["package_root"]), False)
            else:
                manifest, package = verify_package(directory, Path(config["package_trust_file"]))
                package.close()
                if "sha256:"+digest(manifest) != evidence["manifest_digest"]:
                    fail("NATIVE_STATE_CONFLICT", "installed version differs from signed plan")
        else:
            manifest, package = verify_package(directory, Path(config["package_trust_file"]))
            package.close()
            if "sha256:"+digest(manifest) != evidence["manifest_digest"]:
                fail("NATIVE_STATE_CONFLICT", "native package changed before activation")
            activate(Path(config["package_root"]), evidence["kind"], evidence["id"], evidence["version"])
        return {"native_selector": resource, "native_signature_verified": True, "activated": plan["action"] == "package.activate", "manifest_digest": evidence["manifest_digest"]}
    if plan["action"] in {"wiki.create", "snapshot.create", "strata.create", "chain.mine", "compute.run", "identity.register", "content.publish", "zkn.transfer", "zkn.gift", "zkc.issue", "recovery.checkpoint", "recovery.restore"}:
        import subprocess
        source = os.environ.get("_ZIOKT_CORIUM_SOURCE")
        if not source: fail("NATIVE_STATE_UNAVAILABLE", "production monolith unavailable for native action")
        environment = {**os.environ, "CORIUM_ROOT": str(root), "CORIUM_NETWORK_ID_OVERRIDE": network,
                       "CORIUM_TEST_NO_DAEMONS": "1"}
        process = subprocess.Popen(["bash", source, "_internal_ziokt_dispatch", plan["operation_id"]],
                                   env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            process.wait(timeout=25)
        except subprocess.TimeoutExpired:
            import signal
            os.killpg(process.pid, signal.SIGKILL); process.wait()
            fail("RESULT_UNKNOWN", "native Corium action exceeded its execution lease; reconcile its intent")
        if process.returncode: fail("RESULT_UNKNOWN", "native Corium action failed; reconcile its intent")
        if plan["action"].startswith("recovery."):
            return recovery_execute(provider, root, network, plan, config)
        if plan["action"] == "strata.create":
            return {"native_action": "strata.create", "resource": resource, "phase": "native-completed", "recovery": "interrupted-provisioning-requires-native-review"}
        result = operation_reconcile(provider, root, network, plan, config)
        if result is None:
            if plan["action"] == "chain.mine":
                return {"native_action": "chain.mine", "phase": "native-no-op", "block_created": False}
            fail("RESULT_UNKNOWN", "native postcondition has not been verified")
        return result
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
    with closing(sqlite3.connect(dht)) as db, db:
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


def operation_reconcile(provider, root, network, plan, config):
    action = plan["action"]
    if action.startswith("recovery."): return recovery_reconcile(provider, root, network, plan, config)
    if action in {"service.stop", "service.run"}:
        registry = native_registry(root)
        item = registry.services.get(plan["resource"])
        if item and item["state"] == ("stopped" if action == "service.stop" else "running"):
            evidence = {"core_binding": digest(item.get("coreBinding")), "profile_binding": digest(item.get("profileBinding")),
                        "context": digest(item.get("protocolContext")), "lock": (item.get("deploymentLock") or {}).get("digest")}
            if evidence != plan["binding_evidence"]:
                fail("STALE_PLAN", "native binding changed during interrupted operation")
            if action == "service.run":
                # The original authority checks process identity and readiness.
                if registry.status(plan["resource"])["state"] != "running": return None
            return {"native_id": plan["resource"], "postcondition": "stopped" if action == "service.stop" else "running", "reconciled": True, "application_ready": False}
        return None
    if action in {"package.install", "package.activate"}:
        sys.path.insert(0, str(root/"Package-Manager"))
        from shadow6_pkg import verify_package
        e = plan["binding_evidence"]
        base = Path(config["package_root"])/e["kind"]/e["id"]
        source = base/"versions"/e["version"]
        if not source.exists(): return None
        manifest, package = verify_package(source, Path(config["package_trust_file"]))
        package.close()
        if "sha256:"+digest(manifest) != e["manifest_digest"]:
            fail("NATIVE_STATE_CONFLICT", "native installed package differs from recovery evidence")
        if action == "package.activate":
            pointer = strict_json(secure_read(base/"active.json", 4096, private=None))
            if pointer != {"schema_version": 1, "version": e["version"]}: return None
        return {"native_selector": plan["resource"], "native_signature_verified": True, "activated": action == "package.activate", "reconciled": True}
    if action == "wiki.create": return wiki_receipt(root, network, plan)
    if action == "compute.run": return compute_receipt(root, network, plan)
    if action in {'identity.register','content.publish','zkn.transfer','zkn.gift','zkc.issue'}: return asset_receipt(root,network,plan)
    if action == "chain.mine":
        e = plan["binding_evidence"]
        with closing(corium_db(root, network, "blockchain/chain.db")) as db:
            tip = db.execute("SELECT height,hash,previous_hash FROM blocks WHERE height=?", (e["height"]+1,)).fetchone()
        if tip and tip[2] == e["block_hash"]:
            return {"native_action": action, "block_created": True, "height": tip[0], "block_hash": tip[1], "reconciled": True}
        return None
    if action == "snapshot.create":
        base = root/"var/lib/corix/networks"/network/"snapshots"/plan["resource"]
        if (base/"snapshot.meta").is_file():
            metadata = secure_read(base/"snapshot.meta", 4096, private=None).decode()
            if "name="+plan["resource"]+"\n" in metadata and (base/"etc").is_dir():
                return {"native_action": action, "resource": plan["resource"], "phase": "native-completed", "reconciled": True}
        return None
    if action == "strata.create":
        # A directory alone cannot prove successful provisioning after a crash.
        return None
    if action != "artifact.stage": return None
    target = root / "var/lib/corix/p2p/objects/ziokt" / plan["resource"][7:]
    if target.is_file() and not target.is_symlink() and hashlib.sha256(secure_read(target, 6144, private=None)).hexdigest() == plan["resource"][7:]:
        # Resume the fixed content registration only; hashing prevents a changed
        # payload from being mistaken for the interrupted operation.
        return {**operation_execute(provider, root, network, plan, config), "reconciled": True}
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
            rows = db.execute("SELECT o.seq,o.operation_id,o.state,o.evidence FROM outbox o JOIN operations p ON p.id=o.operation_id WHERE o.seq>? AND json_extract(p.plan,'$.federation_id')=? AND json_extract(p.plan,'$.provider_id')=? ORDER BY o.seq LIMIT ?",
                              (params.get("after_seq", 0), config["federation_id"], config["provider_id"], params.get("limit", 50))).fetchall()
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
            required = {"operation_id", "action", "resource", "arguments", "expected_revision"}
            if not required <= set(params) or set(params) - required - {"lease_ms", "fence"}:
                fail("INVALID_PARAMS", "exact native operation plan required")
            if not isinstance(params["action"], str) or not isinstance(params["resource"], str) or not isinstance(params["arguments"], dict):
                fail("INVALID_PARAMS", "typed native action required")
            if params["expected_revision"] is not None and not re.fullmatch(r"sha256:[a-f0-9]{64}", str(params["expected_revision"])):
                fail("INVALID_PARAMS", "native revision digest required")
            request_digest = digest(params)
            row = db.execute("SELECT * FROM operations WHERE id=?", (params["operation_id"],)).fetchone()
            if row:
                previous = strict_json(row[2].encode())
                if previous["federation_id"] != config["federation_id"] or previous["provider_id"] != config["provider_id"]:
                    fail("SCOPE_MISMATCH", "native operation belongs to another provider scope")
                if row[1] != request_digest:
                    fail("IDEMPOTENCY_CONFLICT", "operation ID cannot change its request")
                return operation_view(row)
            evidence = operation_preflight(provider, root, network, params, config)
            fence_admit(db, config, params)
            if db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] >= 4096:
                fail("JOURNAL_LIMIT", "native operation journal requires explicit archival")
            plan = {**params, "federation_id": config["federation_id"], "provider_id": config["provider_id"],
                    "expires_at_ms": time.time_ns() // 1_000_000 + params.get("lease_ms", 30_000), "binding_evidence": evidence}
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
                result = operation_reconcile(provider, root, network, plan, config)
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
        fence_admit(db, config, plan, existing=True)
        if operation_preflight(provider, root, network, plan, config) != plan["binding_evidence"]:
            fail("STALE_PLAN", "native evidence changed after prepare")
        with db:
            changed = db.execute("UPDATE operations SET state='unknown' WHERE id=? AND state='prepared'", (row[0],)).rowcount
            if changed != 1:
                fail("OPERATION_CONFLICT", "operation already claimed")
            if "coordinator_public_key" in config:
                db.execute("UPDATE coordinator SET busy_until=?,operation_id=? WHERE id=1", (time.time_ns()//1_000_000+30000, row[0]))
        result = operation_execute(provider, root, network, plan, config)
        with db:
            db.execute("UPDATE operations SET state='committed',result=? WHERE id=?", (encoded(result).decode(), row[0]))
            db.execute("INSERT OR IGNORE INTO outbox(operation_id,state,evidence) VALUES (?,'committed',?)", (row[0], encoded(result).decode()))
            if "coordinator_public_key" in config:
                db.execute("UPDATE coordinator SET busy_until=0,operation_id=NULL WHERE id=1 AND operation_id=?", (row[0],))
        return operation_view(db.execute("SELECT * FROM operations WHERE id=?", (row[0],)).fetchone())
    except sqlite3.Error:
        fail("JOURNAL_UNAVAILABLE", "native operation journal is busy or invalid")
    finally:
        db.close()

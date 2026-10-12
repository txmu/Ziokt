"""Fixed native checkpoints; restore only cold state under native authority."""
import tempfile


def recovery_content(config, content=None, expected=None):
    if "artifact_root" not in config:
        fail("INVALID_CONFIG", "fixed private recovery artifact store required")
    directory = private_mkdir(config["artifact_root"])
    if content is None:
        if not isinstance(expected, str) or not re.fullmatch("sha256:[a-f0-9]{64}", expected):
            fail("INVALID_RECOVERY", "exact checkpoint digest required")
        raw = secure_read(directory/expected[7:], 64*1024*1024)
        if "sha256:"+hashlib.sha256(raw).hexdigest() != expected:
            fail("ARTIFACT_DIGEST_MISMATCH", "native checkpoint was changed")
        return raw
    key = "sha256:"+hashlib.sha256(content).hexdigest()
    target = directory/key[7:]
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".checkpoint-", delete=False) as output:
        temporary = Path(output.name)
        output.write(content); output.flush(); os.fsync(output.fileno())
    try:
        try: os.link(temporary, target)
        except FileExistsError: recovery_content(config, expected=key)
    finally: temporary.unlink(missing_ok=True)
    return key


def validate_phoenix(raw, root, network):
    value = strict_json(raw, 64*1024*1024, string_limit=65536)
    if not isinstance(value, dict) or value.get("format") != "CORIUM_PHOENIX_GENESIS_V2":
        fail("INVALID_RECOVERY", "native Phoenix checkpoint required")
    public = secure_read(root/"etc/corix/networks"/network/"identity.key.pub", 16384, private=None).decode().rstrip("\n")
    if not isinstance(value.get("snapshot_public_key"), str) or value["snapshot_public_key"].rstrip("\n") != public:
        fail("POLICY_DENIED", "native checkpoint signer must match configured recovery authority")
    unsigned = {k:v for k,v in value.items() if k not in {"state_root", "snapshot_signature"}}
    if value.get("state_root") != digest(unsigned): fail("INVALID_RECOVERY", "native signed state root differs")
    native_ec_verify(public, value.get("snapshot_signature"), value["state_root"].encode())
    return value


def shadow_checkpoint(root, services, include_secrets):
    registry = native_registry(root)
    from profile_registry import native_material_paths
    records, materials = [], {}
    for name in services:
        item = registry.services.get(name)
        if item is None or item.get("coreBinding") is None:
            fail("NATIVE_STATE_UNAVAILABLE", "configured native service required for recovery")
        admitted = registry._material(name)  # Original lock, binary and material validator.
        binding = item["coreBinding"]
        paths = {"config": binding["config"]["config_path"]}
        document = strict_json(secure_read(paths["config"]))
        paths.update(native_material_paths(item["profileBinding"], document))
        for field in ("nativeMaterials", "envelopeTlsMaterial", "componentMaterials"):
            paths.update(admitted.get(field, {}))
        for field in ("envelope_config", "gate_config", "guard_config", "credited_config"):
            if item["spec"].get(field): paths[field] = item["spec"][field]
        for path in paths.values():
            if not include_secrets:
                fail("SECRET_RECOVERY_DISABLED", "explicit include_secrets required to export native transport material")
            raw = secure_read(path, 65536)
            materials[path] = base64.b64encode(raw).decode()
        records.append({"name": name, "core": binding["core"], "profile": item["profileBinding"]["profile"],
            "privacy": item["privacy"], "context": item["protocolContext"], "spec": item["spec"], "config_path": paths["config"]})
    return {"schema": "ziokt.shadow6-checkpoint.v1", "services": records, "materials": materials,
            "contains_secrets": include_secrets, "running_state": "excluded"}


def recovery_preflight(provider, root, network, params, config):
    args, action = params["arguments"], params["action"]
    scope = network if provider == "corium" else "shadow6"
    if params["resource"] != ("checkpoint:" if action == "recovery.checkpoint" else "recovery:")+scope or params["expected_revision"] is not None:
        fail("INVALID_RECOVERY", "exact cold native recovery scope required")
    if "artifact_root" not in config: fail("INVALID_CONFIG", "fixed checkpoint store required")
    safe_directory(config["artifact_root"])
    if action == "recovery.checkpoint":
        if provider == "shadow6":
            if (set(args) != {"services", "include_secrets"} or type(args["include_secrets"]) is not bool or
                    not isinstance(args["services"], list) or not 1 <= len(args["services"]) <= 32 or
                    not all(isinstance(v, str) for v in args["services"]) or len(set(args["services"])) != len(args["services"])):
                fail("INVALID_RECOVERY", "bounded named services and explicit secret export choice required")
            value = shadow_checkpoint(root, args["services"], args["include_secrets"])
            return {"checkpoint_revision": "sha256:"+digest(value), "contains_secrets": args["include_secrets"]}
        if set(args) != {"height"} or type(args["height"]) is not int or not 0 <= args["height"] <= 2**31:
            fail("INVALID_RECOVERY", "exact native checkpoint height required")
        with closing(corium_db(root, network, "blockchain/chain.db")) as db:
            block = db.execute("SELECT hash FROM blocks WHERE height=?", (args["height"],)).fetchone()
        if block is None: fail("NATIVE_STATE_UNAVAILABLE", "checkpoint height not present in native chain")
        return {"height": args["height"], "block_hash": block[0]}
    if set(args) != {"checkpoint_digest"}: fail("INVALID_RECOVERY", "exact immutable restore source required")
    raw = recovery_content(config, expected=args["checkpoint_digest"])
    value = strict_json(raw, 64*1024*1024, string_limit=65536)
    if provider == "shadow6":
        if (not isinstance(value, dict) or set(value) != {"schema", "services", "materials", "contains_secrets", "running_state"} or
                value["schema"] != "ziokt.shadow6-checkpoint.v1" or value["running_state"] != "excluded" or
                not isinstance(value["services"], list) or not 1 <= len(value["services"]) <= 32 or not isinstance(value["materials"], dict) or len(value["materials"]) > 256):
            fail("INVALID_RECOVERY", "exact stopped-state native service checkpoint required")
        registry = native_registry(root)
        for item in value["services"]:
            if not isinstance(item, dict) or set(item) != {"name", "core", "profile", "privacy", "context", "spec", "config_path"}:
                fail("INVALID_RECOVERY", "exact native service reconstruction fields required")
            if item["name"] in registry.services: fail("NATIVE_STATE_CONFLICT", "restore cannot overwrite existing named services")
            if item["privacy"] not in {"native", "envelope"} or not isinstance(item["spec"], dict): fail("INVALID_RECOVERY", "native restoration cannot lower privacy")
        return {"checkpoint_digest": args["checkpoint_digest"], "service_count": len(value["services"])}
    value = validate_phoenix(raw, root, network)
    with closing(corium_db(root, network, "blockchain/chain.db")) as db:
        if db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]:
            fail("NATIVE_STATE_CONFLICT", "Phoenix restoration requires an empty native chain")
    return {"source": str(Path(config["artifact_root"])/args["checkpoint_digest"][7:]),
            "checkpoint_digest": args["checkpoint_digest"], "state_root": value["state_root"]}


def recovery_execute(provider, root, network, plan, config):
    if provider == "corium":
        if plan["action"] == "recovery.restore":
            return {"native_action": "recovery.restore", "state_root": plan["binding_evidence"]["state_root"], "native_signature_verified": True, "running_state_restored": False}
        path = operation_directory(provider, root, network)/"checkpoints"/(plan["operation_id"]+".json")
        raw = secure_read(path, 64*1024*1024)
        value = validate_phoenix(raw, root, network)
        return {"checkpoint_digest": recovery_content(config, raw), "state_root": value["state_root"],
                "native_signature_verified": True, "running_state_restored": False}
    if plan["action"] == "recovery.checkpoint":
        raw = encoded(shadow_checkpoint(root, plan["arguments"]["services"], plan["arguments"]["include_secrets"]))
        return {"checkpoint_digest": recovery_content(config, raw), "contains_secrets": plan["arguments"]["include_secrets"], "running_state_restored": False}
    value = strict_json(recovery_content(config, expected=plan["arguments"]["checkpoint_digest"]), 64*1024*1024, string_limit=65536)
    directory = private_mkdir(operation_directory(provider, root, network)/"restored-material")
    mapping = {}
    for source, data in value["materials"].items():
        raw = base64.b64decode(data, validate=True)
        if len(raw) > 65536: fail("INVALID_RECOVERY", "restored native material exceeds budget")
        target = directory/hashlib.sha256(source.encode()).hexdigest()
        if target.exists():
            if secure_read(target, 65536) != raw: fail("NATIVE_STATE_CONFLICT", "restored material already differs")
        else:
            fd = os.open(target, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as output: output.write(raw); output.flush(); os.fsync(output.fileno())
        mapping[source] = str(target)
    for item in value["services"]:
        for field in ("metrics_path",):
            if item["spec"].get(field):
                mapping[item["spec"][field]] = str(directory/(hashlib.sha256(item["spec"][field].encode()).hexdigest()+".metrics"))
    def remap(item):
        if isinstance(item, str): return mapping.get(item, item)
        if isinstance(item, list): return [remap(v) for v in item]
        if isinstance(item, dict): return {k: remap(v) for k,v in item.items()}
        return item
    # Rewrite material references inside JSON configuration as well.
    configs = {item["config_path"] for item in value["services"]}
    configs.update(item["spec"][field] for item in value["services"] for field in ("envelope_config", "gate_config", "guard_config", "credited_config") if item["spec"].get(field))
    for source in configs:
        target = mapping[source]
        raw = secure_read(target, 65536)
        try: rewritten = encoded(remap(strict_json(raw)))
        except ProtocolError:
            # Native S6EPE INI is validated by the native authority at export
            # and again on explicit apply. Preserve its policy and only remap
            # the admitted fixed material paths into the private restore root.
            text = raw.decode("utf-8")
            for old in sorted(mapping, key=len, reverse=True): text = text.replace(old, mapping[old])
            rewritten = text.encode()
        if rewritten != raw:
            from service_storage import atomic_write
            atomic_write(Path(target), rewritten)
    registry = native_registry(root)
    names = []
    for item in value["services"]:
        registry.create(item["name"], core=item["core"], profile=item["profile"], privacy=item["privacy"],
            config={"config_path": mapping[item["config_path"]]}, context=remap(item["context"]), spec=remap(item["spec"]))
        names.append(item["name"])
    return {"services": names, "running_state_restored": False, "native_apply_required": True}


def recovery_reconcile(provider, root, network, plan, config):
    if plan["action"] == "recovery.restore":
        if provider == "corium": return None  # Native partial import requires native review.
        value = strict_json(recovery_content(config, expected=plan["arguments"]["checkpoint_digest"]), 64*1024*1024, string_limit=65536)
        registry = native_registry(root)
        names = []
        directory = operation_directory(provider, root, network)/"restored-material"
        for desired in value["services"]:
            item = registry.services.get(desired["name"])
            expected_path = str(directory/hashlib.sha256(desired["config_path"].encode()).hexdigest())
            if (not item or item.get("runtime") or item.get("deploymentLock") or item.get("privacy") != desired["privacy"] or
                    (item.get("coreBinding") or {}).get("core") != desired["core"] or
                    item["coreBinding"]["config"]["config_path"] != expected_path): return None
            names.append(desired["name"])
        return {"services": names, "running_state_restored": False, "native_apply_required": True, "reconciled": True}
    if provider == "corium":
        path = operation_directory(provider, root, network)/"checkpoints"/(plan["operation_id"]+".json")
        if path.is_file(): return {**recovery_execute(provider, root, network, plan, config), "reconciled": True}
    else:
        expected = plan["binding_evidence"]["checkpoint_revision"]
        try: recovery_content(config, expected=expected)
        except FileNotFoundError: return None
        return {"checkpoint_digest": expected, "reconciled": True, "running_state_restored": False}
    return None

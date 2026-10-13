"""Ziokt local read-only federation CLI."""
import argparse
import json
import os
from pathlib import Path

from .client import NativeClient
from .config import ENTRYPOINTS, fingerprint, load
from .protocol import ProtocolError, encoded, identifier, make_private, secure_read, strict_json


def write_exclusive(path, value):
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        make_private(path)
        with os.fdopen(fd, "wb") as target:
            target.write(encoded(value) + b"\n")
            target.flush()
            os.fsync(target.fileno())
    except BaseException:
        path.unlink()
        raise


def write_binary_exclusive(path, data):
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        make_private(path)
        with os.fdopen(fd, "wb") as output: output.write(data); output.flush(); os.fsync(output.fileno())
    except BaseException:
        Path(path).unlink(missing_ok=True); raise


def initialize(args):
    identifier(args.federation, "federation_id")
    identifier(args.network, "network_id")
    providers = []
    for project, raw in (("shadow6", args.shadow6), ("corium", args.corium)):
        root = raw.absolute()
        config = (args.shadow6_config.absolute() if project == "shadow6" else
                  args.corium_state_root.absolute() / "etc/corix/networks" / args.network / "corix.conf")
        providers.append({"native_project": project, "provider_id": project + "-local",
                          "root": str(root), "native_config": str(config),
                          "entrypoint_digest": fingerprint(root / ENTRYPOINTS[project]),
                          "network_id": args.network if project == "corium" else None,
                          "state_root": str(args.corium_state_root.absolute()) if project == "corium" else None})
    value = {"schema": "ziokt.federation.v1", "enabled": False,
             "federation_id": args.federation, "providers": providers}
    write_exclusive(args.output, value)
    return {"schema": "ziokt.init.v1", "config": str(args.output.absolute()), "enabled": False}


def inspect(config, action, kind):
    report = {"schema": "ziokt." + action + ".v1", "enabled": config["enabled"],
              "federation_id": config["federation_id"], "healthy": True, "providers": []}
    if not config["enabled"]:
        report["healthy"] = False
        report["error"] = {"code": "ZIOKT_DISABLED", "message": "federation is disabled"}
        return report
    all_objects = []
    for provider in config["providers"]:
        item = {"provider_id": provider["provider_id"], "native_project": provider["native_project"]}
        try:
            client = NativeClient(config["federation_id"], provider)
            if action == "inventory":
                result = client.objects(kind)
                all_objects.extend(result)
                item["object_count"] = len(result)
            else:
                result = client.call("status.get" if action == "doctor" else "capabilities.get")
                if (not isinstance(result, dict) or result.get("provider_id") != provider["provider_id"] or
                        result.get("federation_id") != config["federation_id"] or result.get("enabled") is not True):
                    raise ProtocolError("INVALID_RESPONSE", "provider identity not confirmed")
                item["result"] = result
            item["healthy"] = True
        except (ProtocolError, OSError) as exc:
            item["healthy"] = False
            item["error"] = {"code": getattr(exc, "code", "PROVIDER_UNAVAILABLE"),
                             "message": str(exc) if isinstance(exc, ProtocolError) else "native provider unavailable"}
            report["healthy"] = False
        report["providers"].append(item)
    if action == "inventory":
        report["objects"] = sorted(all_objects, key=lambda r: r["object_id"])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ziokt")
    sub = parser.add_subparsers(dest="action", required=True)
    from .community_cli import register
    register(sub)
    profiles = sub.add_parser('profiles', help='review every native Profile for an application purpose')
    profiles.add_argument('--shadow6', required=True, type=Path)
    profiles.add_argument('--purpose', choices=('proxy-stream','discovery','content'), required=True)
    init = sub.add_parser("init", help="write a disabled federation config; native settings unchanged")
    init.add_argument("--shadow6", required=True, type=Path)
    init.add_argument("--corium", required=True, type=Path)
    init.add_argument("--corium-state-root", required=True, type=Path)
    init.add_argument("--shadow6-config", required=True, type=Path)
    init.add_argument("--federation", default="home")
    init.add_argument("--network", default="default")
    init.add_argument("--output", required=True, type=Path)
    for action in ("doctor", "capabilities", "inventory"):
        cmd = sub.add_parser(action)
        cmd.add_argument("--config", required=True, type=Path)
        cmd.add_argument("--kind", choices=("all", "service", "package", "environment", "application", "identity", "proposal", "recovery", "name"), default="all")
    flow = sub.add_parser("workflow", help="review and apply fixed native steps through a persistent journal")
    actions = flow.add_subparsers(dest="workflow_action", required=True)
    for action in ("plan", "status", "apply"):
        cmd = actions.add_parser(action)
        cmd.add_argument("--journal", type=Path, required=True)
        if action != "status": cmd.add_argument("--config", type=Path, required=True)
        if action == "plan": cmd.add_argument("--manifest", type=Path, required=True)
        else: cmd.add_argument("workflow_id")
        if action == "apply":
            cmd.add_argument("--expected-digest", required=True)
            cmd.add_argument("--confirm", action="store_true")
            cmd.add_argument("--leadership-state", type=Path)
            cmd.add_argument("--coordinator-key", type=Path)
            cmd.add_argument("--leader-id")
            cmd.add_argument("--governance-policy", type=Path)
            cmd.add_argument("--governance-provider")
            cmd.add_argument("--governance-transaction")
    space = sub.add_parser("workspace", help="review native object references without inventing readiness")
    space.add_argument("--manifest", type=Path, required=True)
    space.add_argument("--config", type=Path, required=True)
    space.add_argument("--steps", type=Path)
    space.add_argument("--journal", type=Path)
    space.add_argument("--apply", action="store_true")
    space.add_argument("--expected-digest")
    space.add_argument("--confirm", action="store_true")
    recovery = sub.add_parser("recovery", help="encrypted signed bundles for native checkpoints; explicit cold restore via workflows")
    recovery_actions = recovery.add_subparsers(dest="recovery_action", required=True)
    for action in ("pack", "unpack"):
        cmd = recovery_actions.add_parser(action)
        cmd.add_argument("--store", type=Path, required=True)
        cmd.add_argument("--encryption-key", type=Path, required=True)
        if action == "pack":
            cmd.add_argument("--manifest", type=Path, required=True)
            cmd.add_argument("--objects", type=Path, required=True)
            cmd.add_argument("--signing-key", type=Path, required=True)
            cmd.add_argument("--output", type=Path, required=True)
        else:
            cmd.add_argument("--bundle", type=Path, required=True)
            cmd.add_argument("--publisher", required=True)
            cmd.add_argument("--federation", required=True)
            cmd.add_argument("--minimum-epoch", type=int, required=True)
    identity = sub.add_parser("identity", help="dual native/Ziokt ownership proofs and durable revocation")
    identity_actions = identity.add_subparsers(dest="identity_action", required=True)
    for action in ("enroll", "list", "revoke"):
        cmd = identity_actions.add_parser(action)
        cmd.add_argument("--state", type=Path, required=True)
        cmd.add_argument("--federation", required=True)
        if action == "enroll":
            cmd.add_argument("--document", type=Path, required=True)
            cmd.add_argument("--native-names", type=Path)
        if action == "revoke":
            cmd.add_argument("--public-key", required=True)
            cmd.add_argument("--epoch", type=int, required=True)
            cmd.add_argument("--confirm", action="store_true")
    artifacts = sub.add_parser("artifact", help="integrity-checked local or native bound content sources")
    artifacts.add_argument("--store", type=Path, required=True)
    artifacts.add_argument("--digest", required=True)
    artifacts.add_argument("--source", type=Path, action="append")
    artifacts.add_argument("--config", type=Path)
    artifacts.add_argument("--provider")
    artifacts.add_argument("--peer")
    privacy = sub.add_parser("privacy", help="report satisfied and unmet privacy requirements")
    privacy.add_argument("--profile", choices=("standard", "private", "restricted"), required=True)
    privacy.add_argument("--observations", type=Path, required=True)
    remote = sub.add_parser("remote", help="explicit mutual TLS federation endpoint and scoped client")
    remote_actions = remote.add_subparsers(dest="remote_action", required=True)
    for action in ("serve", "call"):
        cmd = remote_actions.add_parser(action)
        cmd.add_argument("--tls-config", type=Path, required=True)
        if action == "serve": cmd.add_argument("--config", type=Path, required=True)
        else:
            cmd.add_argument("--request", type=Path, required=True)
            cmd.add_argument("--signing-key", type=Path, required=True)
            cmd.add_argument("--federation", required=True)
            cmd.add_argument("--epoch", type=int, default=0)
    coin = sub.add_parser("zkt", help="query native ZKT reputation status or account through the federation")
    coin.add_argument("--config", type=Path, required=True)
    coin.add_argument("--provider", required=True)
    coin.add_argument("--address")
    args = parser.parse_args(argv)
    try:
        if args.action == 'profiles':
            from .transport import plan_profiles
            result = {'schema':'ziokt.profile-plan.v1','profiles':plan_profiles(args.shadow6,args.purpose), 'runtime_verified':False}
        elif args.action == "community":
            from .community_cli import execute
            result = execute(args)
        elif args.action == "remote":
            from .remote import load_remote, remote_server, tls_context, request_remote, resource_for
            endpoint = load_remote(args.tls_config, serving=args.remote_action == "serve")
            context = tls_context(endpoint["certificate"], endpoint["private_key"], endpoint["ca"], server=args.remote_action == "serve")
            if args.remote_action == "serve":
                server = remote_server(load(args.config), context, endpoint["replay_state"], endpoint["trusted_clients"],
                    host=endpoint["host"], port=endpoint["port"], allow_mutations=endpoint["allow_mutations"])
                print(json.dumps({"event": "ziokt.remote-ready", "host": endpoint["host"], "port": server.server_port}), flush=True)
                try: server.serve_forever()
                except KeyboardInterrupt: pass
                finally: server.server_close()
                return 0
            import hashlib
            from .security import grant
            from .routes import resolve_endpoint
            endpoint = resolve_endpoint('standard', endpoint)
            request = strict_json(secure_read(args.request))
            if (not isinstance(request, dict) or set(request) != {"provider_id", "method", "params"} or
                    not isinstance(request["method"], str) or not isinstance(request["params"], dict)):
                raise ProtocolError("INVALID_REQUEST", "exact remote provider operation required")
            private = secure_read(args.signing_key, 32)
            token = lambda: grant(private, audience=request["provider_id"], action=request["method"],
                resource=resource_for(request["method"], request["params"]), federation=args.federation,
                request_digest="sha256:"+hashlib.sha256(encoded(request)).hexdigest(), epoch=args.epoch)
            result = request_remote(endpoint["host"], endpoint["port"], context, request, token, carrier=endpoint.get("carrier"))
        elif args.action == "workflow":
            from .workflow import WorkflowJournal
            with WorkflowJournal(args.journal, read_only=args.workflow_action == "status") as journal:
                if args.workflow_action == "plan": result = journal.plan(strict_json(secure_read(args.manifest)), load(args.config))
                elif args.workflow_action == "status": result = journal.status(args.workflow_id)
                else:
                    federation = load(args.config)
                    guarded = None
                    if any((args.governance_policy, args.governance_provider, args.governance_transaction)):
                        if not all((args.governance_policy, args.governance_provider, args.governance_transaction)):
                            raise ProtocolError("INVALID_CONFIG", "governance policy, native provider and transaction must be supplied together")
                        source = next((p for p in federation["providers"] if p["provider_id"] == args.governance_provider and p["native_project"] == "corium"), None)
                        if source is None: raise ProtocolError("INVALID_CONFIG", "known native governance provider required")
                        from .governance import guard
                        _, guarded = guard(NativeClient(federation["federation_id"], source), strict_json(secure_read(args.governance_policy)),
                                           args.governance_transaction, args.expected_digest)
                    if any((args.leadership_state, args.coordinator_key, args.leader_id)):
                        if not all((args.leadership_state, args.coordinator_key, args.leader_id)):
                            raise ProtocolError("INVALID_CONFIG", "leadership state, key and owner must be supplied together")
                        from .control import LeaderAuthority
                        with LeaderAuthority(args.leadership_state) as authority:
                            result = journal.apply(args.workflow_id, federation, args.expected_digest, args.confirm,
                                leadership=(authority, args.leader_id, secure_read(args.coordinator_key, 32)), guard=guarded)
                    else: result = journal.apply(args.workflow_id, federation, args.expected_digest, args.confirm, guard=guarded)
        elif args.action == "workspace":
            from .workspace import review, provision
            config = load(args.config)
            manifest = strict_json(secure_read(args.manifest))
            inventory = inspect(config, "inventory", "all")
            if args.steps:
                if args.journal is None: raise ProtocolError("INVALID_CONFIG", "workspace native steps require a durable journal")
                from .workflow import WorkflowJournal
                with WorkflowJournal(args.journal) as journal:
                    result = provision(manifest, strict_json(secure_read(args.steps)), config, inventory, journal,
                        apply=args.apply, expected_digest=args.expected_digest, confirmed=args.confirm)
                if args.apply: result["workspace"] = review(manifest, inspect(config, "inventory", "all"))
            else:
                if args.apply: raise ProtocolError("INVALID_CONFIG", "workspace apply requires reviewed native steps")
                result = review(manifest, inventory)
        elif args.action == "recovery":
            from .artifacts import ArtifactStore
            from .recovery import export_bundle, import_bundle
            store = ArtifactStore(args.store); key = secure_read(args.encryption_key, 32)
            if args.recovery_action == "pack":
                blob = export_bundle(strict_json(secure_read(args.manifest)), strict_json(secure_read(args.objects)), store,
                                     secure_read(args.signing_key, 32), key)
                write_binary_exclusive(args.output, blob)
                result = {"encrypted": True, "output": str(args.output), "native_apply_required": True}
            else:
                result = import_bundle(secure_read(args.bundle, 65*1024*1024), store, args.publisher, key,
                                       federation=args.federation, minimum_epoch=args.minimum_epoch)
        elif args.action == "identity":
            from .security import BindingRegistry
            state = BindingRegistry(args.state)
            try:
                if args.identity_action == "enroll":
                    names = strict_json(secure_read(args.native_names)) if args.native_names else None
                    result = state.enroll(strict_json(secure_read(args.document)), args.federation, names)
                elif args.identity_action == "revoke":
                    if not args.confirm: raise ProtocolError("APPROVAL_REQUIRED", "explicit binding revocation --confirm required")
                    state.revoke(args.public_key, args.epoch); result = {"revoked": True, "epoch": args.epoch}
                else: result = {"bindings": state.bindings(args.federation)}
            finally: state.close()
        elif args.action == "artifact":
            from .artifacts import ArtifactStore
            store = ArtifactStore(args.store)
            if args.source: digest = store.fetch(args.digest, args.source)
            else:
                if not all((args.config, args.provider, args.peer)): raise ProtocolError("INVALID_CONFIG", "native artifact requires federation/provider/peer")
                config = load(args.config)
                if not config["enabled"]: raise ProtocolError("ZIOKT_DISABLED", "federation is disabled")
                provider = next((p for p in config["providers"] if p["provider_id"] == args.provider and p["native_project"] == "corium"), None)
                if provider is None: raise ProtocolError("INVALID_CONFIG", "known Corium content provider required")
                digest = store.fetch_native(args.digest, [(NativeClient(config["federation_id"], provider), args.peer)])
            result = {"digest": digest, "native_package_admission_required": True}
        elif args.action == "privacy":
            from .policy import evaluate
            result = evaluate(args.profile, strict_json(secure_read(args.observations)))
        elif args.action == "zkt":
            config = load(args.config)
            if not config["enabled"]: raise ProtocolError("ZIOKT_DISABLED", "federation is disabled")
            provider = next((p for p in config["providers"] if p["provider_id"] == args.provider and p["native_project"] == "corium"), None)
            if provider is None: raise ProtocolError("INVALID_CONFIG", "known native Corium provider required")
            result = NativeClient(config["federation_id"], provider).call("zkt.account" if args.address else "zkt.status", {"address": args.address} if args.address else {})
        else:
            result = initialize(args) if args.action == "init" else inspect(load(args.config), args.action, args.kind)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("healthy", True) else 2
    except (ProtocolError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": {
            "code": getattr(exc, "code", "CONFIGURATION_ERROR"),
            "message": str(exc) if isinstance(exc, ProtocolError) else "configuration operation failed"}}))
        return 2

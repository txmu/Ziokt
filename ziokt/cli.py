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
    if getattr(args, "network_mode", "online") == "airgap":
        value["network_mode"] = "airgap"
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
            proof=client.health()
            item["health"]={"level":"native-provider-rpc","proof":proof,
                            "application_readiness":"not_assessed","peer_connectivity":"not_assessed"}
            if action == "inventory":
                result = client.objects(kind)
                all_objects.extend(result)
                item["object_count"] = len(result)
                item["health"]["inventory_read"]="passed"
            else:
                result = client.call("status.get" if action == "doctor" else "capabilities.get")
                if (not isinstance(result, dict) or result.get("provider_id") != provider["provider_id"] or
                        result.get("federation_id") != config["federation_id"] or result.get("enabled") is not True):
                    raise ProtocolError("INVALID_RESPONSE", "provider identity not confirmed")
                item["result"] = result
                item["health"]["provider_status"]="passed" if action=="doctor" else "capabilities_read"
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
    import sys
    arguments=list(sys.argv[1:] if argv is None else argv)
    command_arguments=arguments[1:] if arguments[:1]==['--airgap'] else arguments
    if command_arguments and command_arguments[0] in {'bundle','program','networks','doomsday','ipfs'}:
        from .runtime_policy import activate_airgap
        if arguments[:1]==['--airgap']:activate_airgap()
        try:
            if command_arguments[0]=='ipfs':
                from .ipfs import main as delegated
            elif command_arguments[0]=='doomsday':
                from .doomsday import main as delegated
            elif command_arguments[0]=='bundle':
                from .bundle import main as delegated
            elif command_arguments[0]=='program':
                from .programs import main as delegated
            else:
                from .networks import main as delegated
            return delegated(command_arguments[1:])
        except (ProtocolError,OSError,ValueError) as error:
            print(json.dumps({'error':getattr(error,'code','INVALID_REQUEST'),'message':str(error)},ensure_ascii=False),file=sys.stderr)
            return 2
    parser = argparse.ArgumentParser(prog="ziokt")
    parser.add_argument("--airgap", action="store_true", help="block network and external workers for this process")
    sub = parser.add_subparsers(dest="action", required=True)
    from .community_cli import register
    register(sub)
    from .collectibles_cli import register as register_collectibles
    register_collectibles(sub)
    from .companion_cli import register as register_companion
    register_companion(sub)
    from .gateway_bootstrap import register as register_gateway
    register_gateway(sub)
    from .mcp import register as register_mcp
    register_mcp(sub)
    from .dns_server import register as register_dns
    register_dns(sub)
    sub.add_parser("airgap", help="activate and report local offline policy")
    effort=sub.add_parser("effort-web", help="serve opt-in public Engine Zero browser workers")
    effort.add_argument("--config", type=Path, required=True)
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
    init.add_argument("--network-mode", choices=("online", "airgap"), default="online")
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
    mail_p = sub.add_parser("mail", help="unified multi-channel mail bridging Corium, ETP, and Community with ZDNS & Content Fabric")
    mail_actions = mail_p.add_subparsers(dest="mail_action", required=True)
    mail_p.add_argument('--config',type=Path,help='private persistent mail and SMTP/IMAP configuration')
    for internet_action in ('internet-flush','internet-poll','internet-status'):
        internet_parser=mail_actions.add_parser(internet_action,help='durable TLS internet mail bridge')
        if internet_action!='internet-status':internet_parser.add_argument('--limit',type=int,default=10)
    internet_resolve=mail_actions.add_parser('internet-resolve',help='explicitly resolve an uncertain SMTP DATA result')
    internet_resolve.add_argument('message_id')
    internet_resolve.add_argument('--decision',choices=['sent','retry'],required=True)
    m_res = mail_actions.add_parser("resolve", help="resolve ZDNS mail address")
    m_send=mail_actions.add_parser('send',help='sign and enqueue native or internet mail')
    m_send.add_argument('--key',type=Path,required=True)
    m_send.add_argument('--from-address',required=True)
    m_send.add_argument('--to',required=True)
    m_send.add_argument('--subject',required=True)
    m_send.add_argument('--body-file',type=Path,required=True)
    m_res.add_argument("address", help="<user>@<domain> address")
    m_inbox = mail_actions.add_parser("inbox", help="query mail inbox")
    m_inbox.add_argument("recipient", help="recipient identifier")
    m_inbox.add_argument("--channel", choices=["corium", "etp", "community", "internet"])
    m_read = mail_actions.add_parser("read", help="read mail by tx hash")
    m_read.add_argument("tx_hash", help="transaction hash")
    m_relay = mail_actions.add_parser("relay", help="forward a signed mail envelope through the public relay")
    m_relay.add_argument("--envelope", type=Path, required=True, help="signed envelope JSON file")
    m_retry = mail_actions.add_parser("retry", help="retry failed mail deliveries")
    m_retry.add_argument("--limit", type=int, default=10)
    m_receipt = mail_actions.add_parser("receipt", help="look up mail delivery receipt")
    m_receipt.add_argument("message_id", help="message identifier")

    pkg_p = sub.add_parser("package", help="unified package lifecycle management")
    pkg_actions = pkg_p.add_subparsers(dest="package_action", required=True)
    pkg_list = pkg_actions.add_parser("list", help="list installed packages")
    pkg_list.add_argument("--root", type=Path, default=Path.home()/".local/share/ziokt-production/packages")
    pkg_rb = pkg_actions.add_parser("rollback", help="rollback package to previous version")
    pkg_rb.add_argument("name", help="package name")
    pkg_rb.add_argument("--root", type=Path, default=Path.home()/".local/share/ziokt-production/packages")
    pkg_un = pkg_actions.add_parser("uninstall", help="uninstall package")
    pkg_un.add_argument("name", help="package name")
    pkg_un.add_argument("--root", type=Path, default=Path.home()/".local/share/ziokt-production/packages")

    site_p = sub.add_parser("site", help="unified static website publishing")
    site_actions = site_p.add_subparsers(dest="site_action", required=True)
    site_st = site_actions.add_parser("status", help="check domain publication status")
    site_st.add_argument("domain", help="website domain")
    site_st.add_argument("--root", type=Path, default=Path.home()/".local/share/ziokt-production/sites")
    site_rb = site_actions.add_parser("rollback", help="rollback website to previous version")
    site_rb.add_argument("domain", help="website domain")
    site_rb.add_argument("--owner", required=True, help="site owner key")
    site_rb.add_argument("--target-version", help="specific historical version")
    site_rb.add_argument("--root", type=Path, default=Path.home()/".local/share/ziokt-production/sites")
    site_hi = site_actions.add_parser("history", help="view website publication history")
    site_hi.add_argument("domain", help="website domain")
    site_hi.add_argument("--root", type=Path, default=Path.home()/".local/share/ziokt-production/sites")
    args = parser.parse_args(argv)
    try:
        from .runtime_policy import activate_airgap, status as network_status
        if args.airgap or args.action == 'airgap':
            activate_airgap()
        if args.action == 'airgap':
            result = network_status()
        elif args.action=='dns':
            from .dns_server import execute as execute_dns
            result=execute_dns(args)
        elif args.action=='mail':
            from .mail import execute_mail_cli
            res=execute_mail_cli(args)
            return 0 if res is None or res==0 else 1
        elif args.action=='package':
            from .package_lifecycle import PackageManager
            mgr=PackageManager(args.root)
            if args.package_action=='list':
                result={'packages':mgr.list_packages()}
            elif args.package_action=='rollback':
                result=mgr.rollback(args.name)
            elif args.package_action=='uninstall':
                result=mgr.uninstall(args.name)
        elif args.action=='site':
            from .site_publishing import SitePublisher
            pub=SitePublisher(args.root)
            if args.site_action=='status':
                result=pub.status(args.domain)
            elif args.site_action=='rollback':
                result=pub.rollback(args.domain,owner=args.owner,target_version=args.target_version)
            elif args.site_action=='history':
                result={'history':pub.history(args.domain)}
        elif args.action=='mcp':
            from .mcp import execute as execute_mcp
            result=execute_mcp(args)
            if result is None: return 0
        elif args.action=='gateway':
            from .gateway_bootstrap import execute as execute_gateway
            result=execute_gateway(args)
        elif args.action=='effort-web':
            from .effort_web import main as effort_main
            effort_main(['--config',str(args.config)])
            return 0
        elif args.action=='companion':
            from .companion_cli import execute as execute_companion
            result=execute_companion(args)
        elif args.action in {'extensions','zkn','zkc','node'}:
            from .collectibles_cli import execute as execute_collectibles
            result=execute_collectibles(args)
        elif args.action == 'profiles':
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
        if result is not None:print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result is None or result.get("healthy", True) else 2
    except (ProtocolError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": {
            "code": getattr(exc, "code", "CONFIGURATION_ERROR"),
            "message": str(exc) if isinstance(exc, ProtocolError) else "configuration operation failed"}}))
        return 2

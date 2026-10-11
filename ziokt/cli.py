"""Ziokt local read-only federation CLI."""
import argparse
import json
import os
from pathlib import Path

from .client import NativeClient
from .config import ENTRYPOINTS, fingerprint, load
from .protocol import ProtocolError, encoded, identifier


def write_exclusive(path, value):
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(encoded(value) + b"\n")
            target.flush()
            os.fsync(target.fileno())
    except BaseException:
        path.unlink()
        raise


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
        cmd.add_argument("--kind", choices=("all", "service", "package", "environment"), default="all")
    args = parser.parse_args(argv)
    try:
        result = initialize(args) if args.action == "init" else inspect(load(args.config), args.action, args.kind)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("healthy", True) else 2
    except (ProtocolError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": {
            "code": getattr(exc, "code", "CONFIGURATION_ERROR"),
            "message": str(exc) if isinstance(exc, ProtocolError) else "configuration operation failed"}}))
        return 2

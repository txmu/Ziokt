"""Owner-controlled, fixed native provider selection. No arbitrary argv."""
import hashlib
from pathlib import Path

from .protocol import ProtocolError, identifier, secure_read, strict_json

ENTRYPOINTS = {"shadow6": "CLI/shadow6.py", "corium": "corix_v108.sh"}


def absolute(value):
    if (not isinstance(value, str) or not value or not Path(value).is_absolute()
            or "\0" in value or ".." in Path(value).parts):
        raise ProtocolError("INVALID_CONFIG", "absolute native path required")
    return Path(value)


def entrypoint(provider):
    return absolute(provider["root"]) / ENTRYPOINTS[provider["native_project"]]


def source_bytes(path):
    # Development trees can be group-writable. Exact source digest is mandatory;
    # the client executes a private byte snapshot, never a replaceable path.
    return secure_read(path, 8 * 1024 * 1024, private=None)


def fingerprint(path):
    return "sha256:" + hashlib.sha256(source_bytes(path)).hexdigest()


def load(path):
    value = strict_json(secure_read(path))
    if (not isinstance(value, dict) or set(value) != {
            "schema", "enabled", "federation_id", "providers"} or
            value["schema"] != "ziokt.federation.v1" or
            type(value["enabled"]) is not bool or
            not isinstance(value["providers"], list) or
            not 1 <= len(value["providers"]) <= 8):
        raise ProtocolError("INVALID_CONFIG", "invalid federation configuration")
    identifier(value["federation_id"], "federation_id")
    ids = set()
    for provider in value["providers"]:
        if not isinstance(provider, dict) or set(provider) != {
                "native_project", "provider_id", "root", "native_config",
                "entrypoint_digest", "network_id", "state_root"}:
            raise ProtocolError("INVALID_CONFIG", "exact provider fields required")
        if (not isinstance(provider["native_project"], str) or
                provider["native_project"] not in ENTRYPOINTS):
            raise ProtocolError("INVALID_CONFIG", "unsupported native provider")
        identifier(provider["provider_id"], "provider_id")
        if provider["provider_id"] in ids:
            raise ProtocolError("INVALID_CONFIG", "duplicate provider identity")
        ids.add(provider["provider_id"])
        absolute(provider["root"])
        absolute(provider["native_config"])
        if provider["native_project"] == "corium":
            identifier(provider["network_id"], "network_id")
            expected = absolute(provider["state_root"]) / "etc/corix/networks" / provider["network_id"] / "corix.conf"
            if absolute(provider["native_config"]) != expected:
                raise ProtocolError("INVALID_CONFIG", "Corium configuration must match its root/network")
        elif provider["network_id"] is not None or provider["state_root"] is not None:
            raise ProtocolError("INVALID_CONFIG", "Shadow6 does not have a Corium network ID")
        import re
        if (not isinstance(provider["entrypoint_digest"], str) or
                not re.fullmatch(r"sha256:[0-9a-f]{64}", provider["entrypoint_digest"])):
            raise ProtocolError("INVALID_CONFIG", "native entrypoint digest required")
    return value

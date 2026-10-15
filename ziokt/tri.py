"""Bounded Tri simulator project exchange over Ziokt's encrypted vault.

The simulator remains local and offline. Projects cross a federation only as
SafeFS ciphertext; this module never evaluates imported instructions.
"""
import hashlib

from .protocol import ProtocolError, encoded, strict_json
from .safefs import Vault

MAX_PROGRAM = 64 * 1024
MAX_STATE = 1024 * 1024


def project_bundle(program, state=None):
    if not isinstance(program, str) or len(program.encode("utf-8")) > MAX_PROGRAM:
        raise ProtocolError("TRI_LIMIT", "Tri assembly source exceeds the 64 KiB project budget")
    if state is None:
        state = {}
    if not isinstance(state, dict) or len(encoded(state)) > MAX_STATE:
        raise ProtocolError("TRI_LIMIT", "Tri snapshot must be a bounded JSON object")
    value = {"schema": "ziokt.tri-project.v1", "engine": "ternary-computer-simulator", "program": program, "state": state}
    return encoded(value)


def read_project(data):
    value = strict_json(data, MAX_STATE + MAX_PROGRAM + 4096)
    if (not isinstance(value, dict) or set(value) != {"schema", "engine", "program", "state"} or
            value["schema"] != "ziokt.tri-project.v1" or value["engine"] != "ternary-computer-simulator" or
            not isinstance(value["program"], str) or len(value["program"].encode("utf-8")) > MAX_PROGRAM or
            not isinstance(value["state"], dict) or len(encoded(value["state"])) > MAX_STATE):
        raise ProtocolError("INVALID_TRI_PROJECT", "exact bounded Tri project envelope required")
    return value


def publish_project(vault: Vault, community, signing_key, program, state=None):
    bundle = project_bundle(program, state)
    digest = "sha256:" + hashlib.sha256(bundle).hexdigest()
    obj = vault.put("tri/projects/" + digest[7:], bundle)
    publication = vault.publish(community, signing_key, obj["digest"])
    return {"schema": "ziokt.tri-publication.v1", "digest": obj["digest"], "event": publication["event"],
            "sealed": True, "plaintext_disclosed": False}


def open_project(vault: Vault, digest):
    name, data = vault.get(digest)
    if (not name.startswith("tri/projects/") or "sha256:" + hashlib.sha256(vault.blob(digest)).hexdigest() != digest):
        raise ProtocolError("ARTIFACT_DIGEST_MISMATCH", "Tri project object name or digest changed")
    return read_project(data)

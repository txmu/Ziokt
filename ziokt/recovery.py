"""Encrypted, signed recovery bundles with explicit checkpoints and revocation epoch."""
import hashlib
import os
from pathlib import Path
import secrets
import struct

from .protocol import ProtocolError, encoded, secure_read, strict_json
from .security import sign, verify


def export_bundle(manifest, objects, store, private_key, encryption_key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if (not isinstance(manifest, dict) or set(manifest) != {"schema", "federation_id", "epoch", "checkpoints"} or
            manifest["schema"] != "ziokt.recovery.v1" or type(manifest["epoch"]) is not int or manifest["epoch"] < 0 or
            not isinstance(objects, list) or len(objects) > 64):
        raise ProtocolError("INVALID_RECOVERY", "bounded explicit native checkpoints required")
    entries, body = [], bytearray()
    for digest in objects:
        data = store.get(digest)
        if len(body) + len(data) > 64 * 1024 * 1024:
            raise ProtocolError("RECOVERY_LIMIT", "recovery bundle budget exceeded")
        entries.append({"digest": digest, "offset": len(body), "size": len(data)})
        body.extend(data)
    signed = sign({"manifest": manifest, "entries": entries}, private_key, "Ziokt/recovery/v1")
    header = encoded(signed)
    plaintext = struct.pack("!I", len(header)) + header + body
    nonce = secrets.token_bytes(12)
    return b"ZIOKT-R1" + nonce + AESGCM(encryption_key).encrypt(nonce, plaintext, b"Ziokt/recovery/v1")


def import_bundle(blob, store, publisher, encryption_key, *, federation, minimum_epoch):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag
    if not isinstance(blob, bytes) or not 40 <= len(blob) <= 65 * 1024 * 1024 or blob[:8] != b"ZIOKT-R1":
        raise ProtocolError("INVALID_RECOVERY", "bounded encrypted recovery bundle required")
    try:
        plaintext = AESGCM(encryption_key).decrypt(blob[8:20], blob[20:], b"Ziokt/recovery/v1")
    except (ValueError, InvalidTag):
        raise ProtocolError("RECOVERY_AUTH_FAILED", "recovery ciphertext authentication failed")
    size = struct.unpack("!I", plaintext[:4])[0]
    if size > 65536 or 4 + size > len(plaintext):
        raise ProtocolError("INVALID_RECOVERY", "recovery header exceeds budget")
    value = verify(strict_json(plaintext[4:4+size]), publisher, "Ziokt/recovery/v1")
    if not isinstance(value, dict) or set(value) != {"manifest", "entries"} or not isinstance(value["entries"], list) or len(value["entries"]) > 64:
        raise ProtocolError("INVALID_RECOVERY", "bounded signed recovery entry table required")
    manifest = value["manifest"]
    if not isinstance(manifest, dict) or set(manifest) != {"schema", "federation_id", "epoch", "checkpoints"} or manifest["schema"] != "ziokt.recovery.v1":
        raise ProtocolError("INVALID_RECOVERY", "exact signed recovery manifest required")
    if manifest["federation_id"] != federation or type(manifest["epoch"]) is not int or manifest["epoch"] < minimum_epoch:
        raise ProtocolError("RECOVERY_ROLLBACK", "recovery scope or revocation epoch rejected")
    body, pending = plaintext[4+size:], []
    expected_offset = 0
    for entry in value["entries"]:
        if (set(entry) != {"digest", "offset", "size"} or type(entry["offset"]) is not int or type(entry["size"]) is not int or
                entry["offset"] != expected_offset or entry["size"] < 0 or entry["offset"] + entry["size"] > len(body)):
            raise ProtocolError("INVALID_RECOVERY", "exact nonoverlapping recovery entries required")
        data = body[entry["offset"]:entry["offset"]+entry["size"]]
        if "sha256:" + hashlib.sha256(data).hexdigest() != entry["digest"]:
            raise ProtocolError("ARTIFACT_DIGEST_MISMATCH", "recovered content digest mismatch")
        pending.append((entry["digest"], data)); expected_offset += len(data)
    if expected_offset != len(body):
        raise ProtocolError("INVALID_RECOVERY", "unexpected recovery trailing content")
    for digest, data in pending:
        store.put(data, digest)
    # This restores immutable bytes only. Native databases, running processes and
    # old grants are never silently imported or reactivated from a bundle.
    return {"manifest": manifest, "objects": [digest for digest, _ in pending],
            "native_apply_required": True, "running_state_restored": False}

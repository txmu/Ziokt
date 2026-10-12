"""Content-addressed bounded store and signed federation publication metadata."""
import hashlib
import os
from pathlib import Path
import re
import tempfile

from .protocol import ProtocolError, encoded, secure_read, strict_json, make_private
from .security import verify

MAX_ARTIFACT = 64 * 1024 * 1024


class ArtifactStore:
    def __init__(self, root):
        self.root = Path(root)
        if self.root.is_symlink():
            raise ProtocolError("UNSAFE_FILE", "artifact store cannot be a symlink")
        existed = self.root.exists()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not existed: make_private(self.root)

    def put(self, data, expected=None):
        if not isinstance(data, bytes) or len(data) > MAX_ARTIFACT:
            raise ProtocolError("ARTIFACT_LIMIT", "bounded binary artifact required")
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        if expected is not None and digest != expected:
            raise ProtocolError("ARTIFACT_DIGEST_MISMATCH", "artifact content does not match digest")
        target = self.root / digest[7:]
        if target.exists():
            self.get(digest)
            return digest
        with tempfile.NamedTemporaryFile(dir=self.root, prefix=".artifact-", delete=False) as output:
            temporary = Path(output.name)
            output.write(data); output.flush(); os.fsync(output.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            self.get(digest)
        finally:
            temporary.unlink(missing_ok=True)
        return digest

    def get(self, digest):
        if not isinstance(digest, str) or not re.fullmatch("sha256:[a-f0-9]{64}", digest):
            raise ProtocolError("INVALID_ARTIFACT", "exact content digest required")
        data = secure_read(self.root / digest[7:], MAX_ARTIFACT)
        if hashlib.sha256(data).hexdigest() != digest[7:]:
            raise ProtocolError("ARTIFACT_DIGEST_MISMATCH", "stored artifact integrity failed")
        return data

    def fetch(self, digest, sources):
        """Explicit source readers; a corrupt source never changes trust policy."""
        failures = []
        for source in sources[:4]:
            try:
                return self.put(secure_read(source, MAX_ARTIFACT, private=None), digest)
            except (ProtocolError, OSError) as exc:
                failures.append(getattr(exc, "code", "SOURCE_UNAVAILABLE"))
        raise ProtocolError("ALL_SOURCES_FAILED", "no approved source supplied matching content: " + ",".join(failures))

    def fetch_native(self, digest, sources):
        """Verified ranged content via native C -> native S -> native C bindings.

        Each source is (NativeClient, peer_id). At most four reviewed providers;
        restart at the last admitted offset, verify the entire digest at publish.
        """
        import base64
        if not isinstance(digest, str) or not re.fullmatch("sha256:[a-f0-9]{64}", digest) or not isinstance(sources, list) or not 1 <= len(sources) <= 4:
            raise ProtocolError("INVALID_ARTIFACT", "exact digest and bounded reviewed native sources required")
        data, total = bytearray(), None
        failures = []
        for client, peer in sources:
            try:
                while total is None or len(data) < total:
                    part = client.call("content.get", {"peer_id": peer, "digest": digest, "offset": len(data), "length": 6144})
                    if (not isinstance(part, dict) or set(part) != {"status", "digest", "offset", "total_size", "data_base64"} or
                            part["status"] != "success" or part["digest"] != digest or part["offset"] != len(data) or
                            type(part["total_size"]) is not int or not 0 <= part["total_size"] <= MAX_ARTIFACT or
                            (total is not None and total != part["total_size"])):
                        raise ProtocolError("INVALID_RESPONSE", "native immutable content range drifted")
                    total = part["total_size"]
                    chunk = base64.b64decode(part["data_base64"], validate=True)
                    if len(chunk) != min(6144, total-len(data)):
                        raise ProtocolError("INVALID_RESPONSE", "native content range length changed")
                    data.extend(chunk)
                    if not total: break
                return self.put(bytes(data), digest)
            except (ProtocolError, OSError, ValueError, TypeError) as exc:
                failures.append(getattr(exc, "code", "SOURCE_UNAVAILABLE"))
                # A failed final hash does not let a corrupt earlier prefix
                # poison the next reviewed source.
                if getattr(exc, "code", "") == "ARTIFACT_DIGEST_MISMATCH": data.clear(); total = None
        raise ProtocolError("ALL_SOURCES_FAILED", "reviewed native content sources exhausted: "+",".join(failures))


def publication(envelope, publisher):
    manifest = verify(envelope, publisher, "Ziokt/artifact/v1")
    if (not isinstance(manifest, dict) or set(manifest) != {"schema", "digest", "size", "native_kind", "native_signature_digest"} or
            manifest["schema"] != "ziokt.artifact.v1" or
            manifest["native_kind"] not in {"shadow6-plugin", "shadow6-mod", "shadow6-app", "corium-package", "content"} or
            type(manifest["size"]) is not int or not 0 <= manifest["size"] <= MAX_ARTIFACT or
            not re.fullmatch("sha256:[a-f0-9]{64}", str(manifest["digest"]))):
        raise ProtocolError("INVALID_ARTIFACT", "typed publication manifest required")
    # This proof authenticates federation metadata only. Native package admission
    # MUST independently verify the original Ed25519/GPG package signature.
    return {**manifest, "publication_verified": True, "native_verified": manifest["native_kind"] == "content"}


def dependency_lock(packages):
    if not isinstance(packages, list) or not 1 <= len(packages) <= 256:
        raise ProtocolError("INVALID_LOCK", "bounded package graph required")
    index, active, visited = {}, set(), set()
    for package in packages:
        if not isinstance(package, dict) or set(package) != {"id", "provider", "version", "digest", "slot", "abi", "dependencies"}:
            raise ProtocolError("INVALID_LOCK", "exact native dependency entry required")
        if (any(not isinstance(package[k], str) or not 1 <= len(package[k]) <= 128 for k in ("id", "provider", "version", "slot", "abi")) or
                not isinstance(package["digest"], str) or not re.fullmatch("sha256:[a-f0-9]{64}", package["digest"])):
            raise ProtocolError("INVALID_LOCK", "exact package version, slot, ABI and digest required")
        if package["id"] in index:
            raise ProtocolError("DEPENDENCY_CONFLICT", "duplicate package identity")
        if not isinstance(package["dependencies"], list) or not all(isinstance(v, str) for v in package["dependencies"]):
            raise ProtocolError("INVALID_LOCK", "typed dependency identifiers required")
        index[package["id"]] = package
    order = []

    def visit(name):
        if name in active:
            raise ProtocolError("DEPENDENCY_CYCLE", "cross-provider dependency cycle")
        if name not in index:
            raise ProtocolError("DEPENDENCY_MISSING", "missing exact native dependency")
        if name in visited:
            return
        active.add(name)
        for dep in index[name]["dependencies"]:
            visit(dep)
        active.remove(name); visited.add(name); order.append(name)
    for name in sorted(index):
        visit(name)
    value = {"schema": "ziokt.dependency-lock.v1", "packages": [index[name] for name in order]}
    return {**value, "digest": "sha256:" + hashlib.sha256(encoded(value)).hexdigest()}

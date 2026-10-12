"""Domain-separated signed objects, scoped grants, revocation and replay state."""
import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
import time
import threading

from .protocol import ProtocolError, encoded, identifier, secure_read, strict_json, make_private


def sign(value, private_key, domain):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    key = Ed25519PrivateKey.from_private_bytes(private_key)
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    return {"schema": "ziokt.signed.v1", "domain": domain, "public_key": public,
            "payload": value, "signature": key.sign((domain + "\n").encode() + encoded(value)).hex()}


def verify(envelope, public_key, domain, *, maximum=65536):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    if (not isinstance(envelope, dict) or set(envelope) != {"schema", "domain", "public_key", "payload", "signature"} or
            envelope["schema"] != "ziokt.signed.v1" or envelope["domain"] != domain or
            envelope["public_key"] != public_key):
        raise ProtocolError("SIGNATURE_REJECTED", "signature domain/authority mismatch")
    try:
        if type(maximum) is not int or not 1 <= maximum <= 1024*1024:
            raise ValueError("signature payload budget")
        strict_json(encoded(envelope["payload"]), maximum)
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)).verify(
            bytes.fromhex(envelope["signature"]), (domain + "\n").encode() + encoded(envelope["payload"]))
    except (ValueError, TypeError, InvalidSignature):
        raise ProtocolError("SIGNATURE_REJECTED", "signed object verification failed")
    return envelope["payload"]


class ReplayAuthority:
    def __init__(self, path):
        path = Path(path)
        if path.is_symlink():
            raise ProtocolError("UNSAFE_FILE", "replay state cannot be a symlink")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        existed = path.exists()
        if existed:
            secure_read(path, 16 * 1024 * 1024)
        self.db = sqlite3.connect(path, timeout=5, check_same_thread=False)
        self._lock = threading.RLock()
        if not existed: make_private(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS used (issuer TEXT NOT NULL, nonce TEXT NOT NULL, expires INTEGER NOT NULL, PRIMARY KEY(issuer,nonce))")
        self.db.execute("CREATE TABLE IF NOT EXISTS epochs (issuer TEXT PRIMARY KEY, epoch INTEGER NOT NULL)")
        self.db.commit()

    def close(self):
        self.db.close()

    def revoke(self, issuer, epoch):
        with self._lock:
            return self._revoke(issuer, epoch)

    def _revoke(self, issuer, epoch):
        if type(epoch) is not int or not 0 <= epoch <= 2**53-1:
            raise ProtocolError("INVALID_GRANT", "bounded revocation epoch required")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            old = self.db.execute("SELECT epoch FROM epochs WHERE issuer=?", (issuer,)).fetchone()
            if old and epoch < old[0]:
                raise ProtocolError("REVOCATION_ROLLBACK", "revocation epoch cannot decrease")
            self.db.execute("INSERT OR REPLACE INTO epochs VALUES (?,?)", (issuer, epoch))
            self.db.commit()
        except BaseException:
            self.db.rollback(); raise

    def admit(self, envelope, issuer, *, audience, action, resource, federation, request_digest):
        with self._lock:
            return self._admit(envelope, issuer, audience=audience, action=action,
                               resource=resource, federation=federation, request_digest=request_digest)

    def _admit(self, envelope, issuer, *, audience, action, resource, federation, request_digest):
        grant = verify(envelope, issuer, "Ziokt/grant/v1")
        if not isinstance(grant, dict) or set(grant) != {"audience", "action", "resource", "federation_id", "request_digest", "issued_at", "expires_at", "nonce", "epoch"}:
            raise ProtocolError("INVALID_GRANT", "exact scoped grant required")
        now = int(time.time())
        if (any(grant[k] != v for k, v in {"audience": audience, "action": action,
                "resource": resource, "federation_id": federation, "request_digest": request_digest}.items()) or
                type(grant["issued_at"]) is not int or type(grant["expires_at"]) is not int or
                not now-30 <= grant["issued_at"] <= now+5 or not now < grant["expires_at"] <= grant["issued_at"]+30 or
                type(grant["epoch"]) is not int or not 0 <= grant["epoch"] <= 2**53-1 or
                not isinstance(grant["nonce"], str) or len(grant["nonce"]) != 32):
            raise ProtocolError("INVALID_GRANT", "grant scope or short validity rejected")
        try:
            if len(bytes.fromhex(grant["nonce"])) != 16:
                raise ValueError()
        except ValueError:
            raise ProtocolError("INVALID_GRANT", "cryptographic nonce required")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT epoch FROM epochs WHERE issuer=?", (issuer,)).fetchone()
            if grant["epoch"] != (row[0] if row else 0):
                raise ProtocolError("GRANT_REVOKED", "grant revocation epoch rejected")
            self.db.execute("DELETE FROM used WHERE expires<?", (now-30,))
            if self.db.execute("SELECT COUNT(*) FROM used").fetchone()[0] >= 4096:
                raise ProtocolError("REPLAY_LIMIT", "replay window exhausted")
            self.db.execute("INSERT INTO used VALUES (?,?,?)", (issuer, grant["nonce"], grant["expires_at"]))
            self.db.commit()
        except sqlite3.IntegrityError:
            self.db.rollback()
            raise ProtocolError("REPLAY_REJECTED", "grant nonce already consumed")
        except BaseException:
            self.db.rollback()
            raise
        return grant


def grant(private, *, audience, action, resource, federation, request_digest, epoch=0):
    now = int(time.time())
    return sign({"audience": audience, "action": action, "resource": resource,
                 "federation_id": federation, "request_digest": request_digest,
                 "issued_at": now, "expires_at": now+30, "nonce": secrets.token_hex(16), "epoch": epoch}, private, "Ziokt/grant/v1")


def identity_binding(ziokt_public, native_project, native_identity, federation):
    identifier(federation, "federation")
    if native_project not in {"shadow6", "corium"} or not isinstance(native_identity, str):
        raise ProtocolError("INVALID_BINDING", "typed native identity required")
    return {"schema": "ziokt.identity-binding.v1", "ziokt_public": ziokt_public,
            "native_project": native_project, "native_identity": native_identity,
            "federation_id": federation, "challenge": secrets.token_hex(16)}


def verify_native_binding(binding, native_signature, native_public, trusted_names=None):
    """Verify native proof without converting EC/RSA signatures into Ed25519."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519
    from cryptography.exceptions import InvalidSignature
    message = b"Ziokt/native-binding/v1\n" + encoded(binding)
    try:
        if (not isinstance(binding, dict) or set(binding) != {"schema", "ziokt_public", "native_project", "native_identity", "federation_id", "challenge"} or
                binding["schema"] != "ziokt.identity-binding.v1" or not isinstance(binding["challenge"], str) or len(bytes.fromhex(binding["challenge"])) != 16):
            raise ValueError()
        if binding["native_project"] == "shadow6":
            key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(native_public))
            key.verify(bytes.fromhex(native_signature), message)
            # ShadowIdentity is a native name plus key; the name is never
            # inferred from raw key bytes or asserted by an untrusted caller.
            if not isinstance(trusted_names, dict) or trusted_names.get(binding["native_identity"]) != native_public:
                raise ValueError()
            expected_identity = binding["native_identity"]
        elif binding["native_project"] == "corium":
            key = serialization.load_pem_public_key(native_public.encode())
            if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256K1):
                raise ValueError()
            key.verify(bytes.fromhex(native_signature), message, ec.ECDSA(hashes.SHA256()))
            expected_identity = hashlib.sha256(native_public.rstrip("\n").encode()).hexdigest()
        else: raise ValueError()
        if binding["native_identity"] != expected_identity:
            raise ValueError()
    except (ValueError, TypeError, InvalidSignature, KeyError):
        raise ProtocolError("BINDING_REJECTED", "native ownership proof rejected")
    return binding


class BindingRegistry(ReplayAuthority):
    """Two ownership proofs, persistent revocation; no native ACL promotion."""
    def __init__(self, path):
        super().__init__(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS bindings (federation TEXT,project TEXT,native_id TEXT,ziokt_key TEXT,epoch INTEGER,proof TEXT,PRIMARY KEY(federation,project,native_id))")
        self.db.commit()

    def enroll(self, envelope, federation, trusted_names=None):
        if not isinstance(envelope, dict) or not isinstance(envelope.get("public_key"), str):
            raise ProtocolError("INVALID_BINDING", "signed dual ownership proof required")
        public = envelope["public_key"]
        payload = verify(envelope, public, "Ziokt/binding/v1")
        if not isinstance(payload, dict) or set(payload) != {"binding", "native_public", "native_signature", "epoch"}:
            raise ProtocolError("INVALID_BINDING", "exact binding proof required")
        binding = verify_native_binding(payload["binding"], payload["native_signature"], payload["native_public"], trusted_names)
        if binding["ziokt_public"] != public or binding["federation_id"] != federation or type(payload["epoch"]) is not int:
            raise ProtocolError("SCOPE_MISMATCH", "binding authority or federation differs")
        with self._lock, self.db:
            epoch = self.db.execute("SELECT epoch FROM epochs WHERE issuer=?", (public,)).fetchone()
            if payload["epoch"] != (epoch[0] if epoch else 0):
                raise ProtocolError("BINDING_REVOKED", "binding revocation epoch differs")
            old = self.db.execute("SELECT ziokt_key FROM bindings WHERE federation=? AND project=? AND native_id=?",
                (federation, binding["native_project"], binding["native_identity"])).fetchone()
            if old and old[0] != public: raise ProtocolError("BINDING_CONFLICT", "native identity already has a different reviewed binding")
            self.db.execute("INSERT OR REPLACE INTO bindings VALUES (?,?,?,?,?,?)", (federation, binding["native_project"], binding["native_identity"], public, payload["epoch"], encoded(envelope).decode()))
        return {"binding": binding, "epoch": payload["epoch"], "native_permissions_granted": False}

    def bindings(self, federation):
        with self._lock:
            rows = self.db.execute("SELECT proof FROM bindings b WHERE federation=? AND epoch=COALESCE((SELECT epoch FROM epochs e WHERE e.issuer=b.ziokt_key),0) LIMIT 4097", (federation,)).fetchall()
        if len(rows) > 4096: raise ProtocolError("BINDING_LIMIT", "binding inventory requires archival")
        return [strict_json(row[0].encode()) for row in rows]

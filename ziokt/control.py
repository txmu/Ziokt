"""Single-authority durable leadership. No cross-machine consensus assumption."""
import hashlib
from pathlib import Path
import sqlite3
import time
from .protocol import ProtocolError, identifier, encoded, secure_read, make_private


class LeaderAuthority:
    def __init__(self, path):
        path = Path(path)
        existed = path.exists()
        if existed: secure_read(path, 16*1024*1024)
        if path.is_symlink(): raise ProtocolError("UNSAFE_FILE", "leadership state cannot be a symlink")
        self.db = sqlite3.connect(path, timeout=5)
        if not existed: make_private(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS leases (federation TEXT PRIMARY KEY,owner TEXT NOT NULL,term INTEGER NOT NULL,expires INTEGER NOT NULL)")
        self.db.commit()

    def close(self): self.db.close()
    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def acquire(self, federation, owner, ttl_ms=30000):
        identifier(federation, "federation_id"); identifier(owner, "leader_id")
        if type(ttl_ms) is not int or not 250 <= ttl_ms <= 30000:
            raise ProtocolError("INVALID_LEASE", "leadership lease must be 250..30000 ms")
        now = time.time_ns()//1_000_000
        try:
            self.db.execute("BEGIN IMMEDIATE")
            old = self.db.execute("SELECT owner,term,expires FROM leases WHERE federation=?", (federation,)).fetchone()
            if old and old[2] > now and old[0] != owner:
                raise ProtocolError("LEADER_BUSY", "another live coordinator owns this authority")
            term = old[1] if old and old[0] == owner and old[2] > now else (old[1]+1 if old else 1)
            if term > 2**53-1: raise ProtocolError("LEASE_LIMIT", "leadership term exhausted")
            self.db.execute("INSERT OR REPLACE INTO leases VALUES (?,?,?,?)", (federation, owner, term, now+ttl_ms))
            self.db.commit()
        except BaseException:
            self.db.rollback(); raise
        return {"federation_id": federation, "owner": owner, "term": term, "expires_at_ms": now+ttl_ms}

    def token(self, federation, owner, provider, params, private_key):
        lease = self.db.execute("SELECT owner,term,expires FROM leases WHERE federation=?", (federation,)).fetchone()
        if not lease or lease[0] != owner or lease[2] <= time.time_ns()//1_000_000:
            raise ProtocolError("STALE_FENCE", "live leadership authority required")
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        payload = {"federation_id": federation, "provider_id": provider, "operation_id": params["operation_id"],
                   "request_digest": "sha256:"+hashlib.sha256(encoded(params)).hexdigest(), "term": lease[1], "expires_at_ms": lease[2]}
        return {"payload": payload, "signature": Ed25519PrivateKey.from_private_bytes(private_key).sign(b"Ziokt/fence/v1\n"+encoded(payload)).hex()}

    def release(self, federation, owner):
        with self.db:
            self.db.execute("UPDATE leases SET expires=0 WHERE federation=? AND owner=?", (federation, owner))

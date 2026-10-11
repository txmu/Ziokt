import hashlib
from pathlib import Path
import secrets
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ziokt.artifacts import ArtifactStore, dependency_lock, publication
from ziokt.policy import Budget, evaluate, select_path
from ziokt.protocol import ProtocolError
from ziokt.recovery import export_bundle, import_bundle
from ziokt.security import ReplayAuthority, grant, sign, verify
from ziokt.workspace import review


class BusinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ziokt-business-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        key = Ed25519PrivateKey.generate()
        self.private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        self.public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()

    def test_signed_domain_and_tamper_rejection(self):
        signed = sign({"scope": "native"}, self.private, "Ziokt/test/v1")
        self.assertEqual(verify(signed, self.public, "Ziokt/test/v1"), {"scope": "native"})
        with self.assertRaises(ProtocolError):
            verify(signed, self.public, "Ziokt/grant/v1")
        signed["payload"]["scope"] = "other"
        with self.assertRaises(ProtocolError):
            verify(signed, self.public, "Ziokt/test/v1")

    def test_persistent_nonce_replay_and_revocation(self):
        authority = ReplayAuthority(self.root / "replay.sqlite"); self.addCleanup(authority.close)
        scope = {"audience": "provider", "action": "artifact.stage", "resource": "content",
                 "federation": "test", "request_digest": "sha256:" + "a" * 64}
        token = grant(self.private, **scope)
        authority.admit(token, self.public, **scope)
        with self.assertRaises(ProtocolError) as replay:
            authority.admit(token, self.public, **scope)
        self.assertEqual(replay.exception.code, "REPLAY_REJECTED")
        authority.revoke(self.public, 1)
        with self.assertRaises(ProtocolError) as revoked:
            authority.admit(grant(self.private, **scope), self.public, **scope)
        self.assertEqual(revoked.exception.code, "GRANT_REVOKED")
        with self.assertRaises(ProtocolError):
            authority.revoke(self.public, 0)

    def test_artifact_integrity_multisource_and_native_trust_separation(self):
        store = ArtifactStore(self.root / "store")
        correct, corrupt = self.root / "correct", self.root / "corrupt"
        correct.write_bytes(b"native artifact"); corrupt.write_bytes(b"wrong")
        digest = "sha256:" + hashlib.sha256(correct.read_bytes()).hexdigest()
        self.assertEqual(store.fetch(digest, [corrupt, correct]), digest)
        self.assertEqual(store.get(digest), b"native artifact")
        envelope = sign({"schema": "ziokt.artifact.v1", "digest": digest, "size": 15,
                         "native_kind": "corium-package", "native_signature_digest": "sha256:" + "b" * 64},
                        self.private, "Ziokt/artifact/v1")
        self.assertFalse(publication(envelope, self.public)["native_verified"])
        (store.root / digest[7:]).write_bytes(b"changed")
        with self.assertRaises(ProtocolError):
            store.get(digest)

    def test_cross_provider_dependency_order_and_cycle_detection(self):
        common = {"version": "1", "digest": "sha256:" + "a" * 64, "slot": "0", "abi": "1"}
        packages = [{**common, "id": "app", "provider": "shadow6", "dependencies": ["runtime"]},
                    {**common, "id": "runtime", "provider": "corium", "dependencies": []}]
        result = dependency_lock(packages)
        self.assertEqual([r["id"] for r in result["packages"]], ["runtime", "app"])
        packages[1]["dependencies"] = ["app"]
        with self.assertRaises(ProtocolError) as cycle:
            dependency_lock(packages)
        self.assertEqual(cycle.exception.code, "DEPENDENCY_CYCLE")

    def test_restricted_privacy_never_falls_back_to_direct(self):
        direct = {"approved": True, "observed": {"end_to_end_authentication": True,
                  "encrypted_content": True, "private_discovery": True, "direct_fallback": True}}
        anonymous = {"approved": True, "observed": {**direct["observed"], "anonymous_carrier": True, "direct_fallback": False}}
        with self.assertRaises(ProtocolError):
            select_path("restricted", [direct])
        self.assertEqual(select_path("restricted", [direct, anonymous]), anonymous)
        self.assertFalse(evaluate("private", {"encrypted_content": True})["satisfied"])

    def test_finite_budget_applies_backpressure_without_consuming_capacity(self):
        budget = Budget(10, 2); budget.admit(5)
        with self.assertRaises(ProtocolError):
            budget.admit(6)
        self.assertEqual((budget.bytes, budget.records), (5, 1))
        budget.admit(5)
        with self.assertRaises(ProtocolError):
            budget.admit(0)

    def test_encrypted_recovery_integrity_scope_epoch_and_no_runtime_restore(self):
        original = ArtifactStore(self.root / "original")
        digest = original.put(b"recovery fixture")
        manifest = {"schema": "ziokt.recovery.v1", "federation_id": "test", "epoch": 3,
                    "checkpoints": {"shadow6": "material-lock", "corium": "block-hash"}}
        key = secrets.token_bytes(32)
        blob = export_bundle(manifest, [digest], original, self.private, key)
        recovered = ArtifactStore(self.root / "recovered")
        result = import_bundle(blob, recovered, self.public, key, federation="test", minimum_epoch=3)
        self.assertEqual(recovered.get(digest), original.get(digest))
        self.assertTrue(result["native_apply_required"])
        self.assertFalse(result["running_state_restored"])
        for data, epoch, scope in ((blob[:-1] + bytes([blob[-1] ^ 1]), 3, "test"),
                                    (blob, 4, "test"), (blob, 3, "other")):
            with self.assertRaises(ProtocolError):
                import_bundle(data, recovered, self.public, key, federation=scope, minimum_epoch=epoch)

    def test_workspace_references_do_not_invent_live_readiness(self):
        manifest = {"schema": "ziokt.workspace.v1", "workspace_id": "workspace", "federation_id": "test",
                    "services": ["ziokt://test/s/service/known"], "packages": ["missing"],
                    "applications": [], "identities": [], "privacy": "private", "recovery": {"epoch": 0}}
        inventory = {"federation_id": "test", "objects": [{"object_id": "ziokt://test/s/service/known", "state": "running"}]}
        result = review(manifest, inventory)
        self.assertEqual(result["missing"], ["missing"])
        self.assertFalse(result["runtime_ready"])


if __name__ == "__main__":
    unittest.main()

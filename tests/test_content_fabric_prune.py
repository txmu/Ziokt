import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from ziokt.content_fabric import Fabric
from ziokt import content_api


class ContentFabricPruneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fabric = Fabric(self.root / "fabric")

    def tearDown(self):
        self.fabric.close()
        self.tmp.cleanup()

    def test_prune_and_auto_prune(self):
        owner = "alice"
        # 1. Create an upload
        payload = b"test payload for pruning"
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        self.fabric.begin(owner, "up1", len(payload), digest, "text/plain")

        # 2. Prune should clean dead uploads or report status
        result = self.fabric.prune(owner=owner)
        self.assertEqual(result["schema"], "ziokt.content-prune.v1")
        self.assertIn("disk_free", result)
        self.assertIn("quota_bytes", result)

    def test_replica_health_and_auto_repair(self):
        owner = "alice"
        health = self.fabric.replica_health(owner)
        self.assertEqual(health["schema"], "ziokt.content-replica-health.v1")
        self.assertTrue(health["healthy"])

        # Add an object and verify auto_repair actively verifies objects and database check
        payload = b"verifiable object data"
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        self.fabric.begin(owner, "up_vrf", len(payload), digest, "text/plain")
        self.fabric.put(owner, "up_vrf", 0, payload)
        fin = self.fabric.finish(owner, "up_vrf")

        repair = self.fabric.auto_repair(owner)
        self.assertEqual(repair["schema"], "ziokt.content-auto-repair.v1")
        self.assertEqual(repair["status"], "repaired")
        self.assertGreaterEqual(repair["verified_objects"], 1)
        self.assertEqual(repair["corrupted_objects"], 0)
        self.assertEqual(repair["database_check"], "ok")

    def test_api_integration(self):
        owner = "alice"
        # Test content.fabric.health via content_api
        res_health = content_api.invoke(self.fabric, owner, "content.fabric.health", {})
        self.assertEqual(res_health["schema"], "ziokt.content-replica-health.v1")

        # Test content.fabric.prune via content_api
        res_prune = content_api.invoke(self.fabric, owner, "content.fabric.prune", {"target_bytes": 1024, "max_age_days": 7})
        self.assertEqual(res_prune["schema"], "ziokt.content-prune.v1")

        # Test content.fabric.repair via content_api
        res_repair = content_api.invoke(self.fabric, owner, "content.fabric.repair", {})
        self.assertEqual(res_repair["schema"], "ziokt.content-auto-repair.v1")


if __name__ == "__main__":
    unittest.main()

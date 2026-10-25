import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from openci.state import Store, validate_pipeline, Error
from openci.controller import Controller
from openci.client import Client


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "state")

    def tearDown(self):
        self.tmp.cleanup()

    def test_pipeline_validation_with_cache_key(self):
        source = {
            "object": "cf1-" + "a" * 64,
            "digest": "sha256:" + "0" * 64,
        }
        pipe = {
            "schema": "openci.pipeline.v1",
            "project": "proj",
            "nonce": "n1",
            "source": source,
            "tasks": [
                {
                    "id": "t1",
                    "needs": [],
                    "image": "img@sha256:" + "1" * 64,
                    "argv": ["make"],
                    "arch": "x86_64",
                    "pool": "trusted",
                    "cpu": 2,
                    "memory_mb": 512,
                    "timeout": 60,
                    "attempts": 1,
                    "cache_key": "kernel-build-v1",
                    "cache_paths": [".cache", "target"],
                    "cache_mode": "read-write",
                }
            ],
        }
        val = validate_pipeline(pipe)
        self.assertEqual(val["tasks"][0]["cache_key"], "kernel-build-v1")
        self.assertEqual(val["tasks"][0]["cache_paths"], [".cache", "target"])
        self.assertEqual(val["tasks"][0]["cache_mode"], "read-write")

        # Invalid cache key rejected
        bad_pipe = dict(pipe, tasks=[dict(pipe["tasks"][0], cache_key="invalid/key!")])
        with self.assertRaises(Error) as ctx:
            validate_pipeline(bad_pipe)
        self.assertEqual(ctx.exception.code, "INVALID_CACHE_KEY")

        # Invalid cache mode rejected
        bad_mode = dict(pipe, tasks=[dict(pipe["tasks"][0], cache_mode="rw")])
        with self.assertRaises(Error) as ctx:
            validate_pipeline(bad_mode)
        self.assertEqual(ctx.exception.code, "INVALID_CACHE_MODE")

    def test_store_cache_lifecycle_and_pruning(self):
        art1 = {"object": "cf1-" + "1" * 64, "digest": "sha256:" + "1" * 64}
        art2 = {"object": "cf1-" + "2" * 64, "digest": "sha256:" + "2" * 64}

        # Put cache entries
        res1 = self.store.cache_put("proj", "key1", art1, 1024)
        self.assertTrue(res1["stored"])
        res2 = self.store.cache_put("proj", "key2", art2, 2048)
        self.assertTrue(res2["stored"])

        # Lookup cache
        c1 = self.store.cache_get("proj", "key1")
        self.assertIsNotNone(c1)
        self.assertEqual(c1["artifact"], art1)
        self.assertEqual(c1["size"], 1024)
        self.assertEqual(c1["hit_count"], 1)

        # Hit count increases
        c1_again = self.store.cache_get("proj", "key1")
        self.assertEqual(c1_again["hit_count"], 2)

        # List caches
        items = self.store.cache_list("proj")
        self.assertEqual(len(items), 2)

        # Prune with max_bytes = 2048 (total is 3072, so removing one entry leaves <= 2048)
        pruned = self.store.cache_prune("proj", max_bytes=2048)
        self.assertEqual(pruned["pruned_entries"], 1)

        # Delete remaining cache
        remaining = self.store.cache_list("proj")
        self.assertEqual(len(remaining), 1)
        del_res = self.store.cache_delete("proj", remaining[0]["cache_key"])
        self.assertTrue(del_res["deleted"])
        self.assertEqual(len(self.store.cache_list("proj")), 0)

    def test_controller_cache_endpoints_and_worker_assignment(self):
        cfg = self.root / "controller.json"
        token = "secret123"
        cfg.write_text(json.dumps({
            "principals": {
                "admin": {
                    "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                    "role": "admin",
                    "scopes": ["*"],
                    "projects": ["proj"]
                }
            }
        }))
        controller = Controller(self.root / "ctrl", cfg)
        try:
            payload = b"test payload for cache"
            digest = "sha256:" + hashlib.sha256(payload).hexdigest()
            owner = "openci-proj"
            controller.fabric.begin(owner, "up1", len(payload), digest, "application/octet-stream")
            controller.fabric.put(owner, "up1", 0, payload)
            ref_res = controller.fabric.finish(owner, "up1")
            real_art = {"object": ref_res["id"], "digest": ref_res["digest"]}

            # Store cache via controller dispatch
            status, stored = controller.dispatch("POST", "/v1/cache/store", {"project": ["proj"]},
                                                 {"key": "build-k1", "artifact": real_art}, "admin",
                                                 {"role": "admin", "projects": ["proj"]})
            self.assertEqual(status, 200)
            self.assertTrue(stored["stored"])

            # Lookup cache via dispatch
            status, found = controller.dispatch("GET", "/v1/cache/lookup", {"project": ["proj"], "key": ["build-k1"]},
                                                None, "admin", {"role": "admin", "projects": ["proj"]})
            self.assertEqual(status, 200)
            self.assertTrue(found["hit"])
            self.assertEqual(found["cache"]["artifact"], real_art)

            # List caches
            status, listed = controller.dispatch("GET", "/v1/cache/list", {"project": ["proj"]},
                                                 None, "admin", {"role": "admin", "projects": ["proj"]})
            self.assertEqual(status, 200)
            self.assertEqual(len(listed["caches"]), 1)

            # Prune
            status, p_res = controller.dispatch("POST", "/v1/cache/prune", {"project": ["proj"]},
                                                {"max_bytes": 0, "max_age": 0}, "admin",
                                                {"role": "admin", "projects": ["proj"]})
            self.assertEqual(status, 200)
            self.assertEqual(p_res["pruned_entries"], 1)
        finally:
            controller.close()


if __name__ == "__main__":
    unittest.main()

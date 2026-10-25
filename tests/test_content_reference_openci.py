import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from ziokt.content_fabric import Fabric
from ziokt import content_reference


class ContentReferenceOpenCITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fabric = Fabric(self.root / "fabric")

    def tearDown(self):
        self.fabric.close()
        self.tmp.cleanup()

    def test_universal_package_reference(self):
        owner = "openci-project1"
        payload = b"binary package executable code"
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        self.fabric.begin(owner, "up1", len(payload), digest, "application/octet-stream")
        self.fabric.put(owner, "up1", 0, payload)
        ref = self.fabric.finish(owner, "up1")

        # Publish a package record into Content Fabric
        pkg_body = {
            "name": "my-tool",
            "version": "1.0.0",
            "files": [
                {
                    "path": "bin/my-tool",
                    "role": "artifact",
                    "id": ref["id"],
                    "size": len(payload),
                    "digest": ref["digest"],
                    "mime": "application/octet-stream",
                }
            ],
        }
        pub_res = self.fabric.publish_package(owner, "my-tool", "1.0.0", pkg_body, visibility="public")
        record_id = pub_res["id"]

        # Create universal content reference
        created = content_reference.create(self.fabric, owner, record_id, verify_bytes=True)
        self.assertTrue(created["content_bytes_verified"])
        cref = created["reference"]
        self.assertEqual(cref["schema"], "ziokt.content-reference.v1")
        self.assertEqual(cref["kind"], "package")
        self.assertEqual(cref["record"], record_id)
        self.assertEqual(len(cref["objects"]), 1)
        self.assertEqual(cref["objects"][0]["id"], ref["id"])
        self.assertEqual(cref["objects"][0]["role"], "artifact")
        self.assertEqual(cref["objects"][0]["name"], "bin/my-tool")

        # Resolve universal content reference
        resolved = content_reference.resolve(self.fabric, "@anonymous", cref, verify_bytes=True)
        self.assertEqual(resolved["state"], "available")
        self.assertEqual(resolved["reference"], cref)


if __name__ == "__main__":
    unittest.main()

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class CoriumDownload(unittest.TestCase):
    def test_integrity_and_exclusive_output(self):
        source = Path(__file__).resolve().parents[2] / "Corium/corix_v108.sh"
        if not source.exists():
            self.skipTest("Corium source unavailable")
        script = source.read_text()
        function = script[script.index("forum_get_attachment() {"):script.index("\n\n# Exports a full topic")]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            cache.mkdir()
            data = b"verified object"
            digest = hashlib.sha256(data).hexdigest()
            obj = cache / digest
            obj.write_bytes(data)
            def run(*args):
                return subprocess.run(["bash", "-c", function + '\nforum_fetch_object() { return 1; }\nforum_get_attachment "$@"', "test", *args], cwd=root, env={**os.environ, "FORUM_OBJECTS_DIR": str(cache)}, capture_output=True)
            self.assertEqual(run(digest).returncode, 0)
            self.assertEqual((root / digest).read_bytes(), data)
            self.assertEqual((root / digest).stat().st_mode & 0o777, 0o600)
            self.assertNotEqual(run(digest).returncode, 0)
            self.assertNotEqual(run("../bad", "safe").returncode, 0)
            self.assertNotEqual(run(digest, "../safe").returncode, 0)
            (root / "link").symlink_to(root / digest)
            self.assertNotEqual(run(digest, "link").returncode, 0)
            obj.write_bytes(b"corrupt")
            self.assertNotEqual(run(digest, "corrupt-out").returncode, 0)
            self.assertFalse((root / "corrupt-out").exists())
            obj.unlink()
            obj.symlink_to(root / digest)
            self.assertNotEqual(run(digest, "source-link").returncode, 0)

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('effort_downloads',Path(__file__).resolve().parents[1]/'tools/install_effort_downloads.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class DownloadsTests(unittest.TestCase):
    def fixture(self,root):
        source=root/'ci';source.mkdir();downloads=root/'downloads';downloads.mkdir();(downloads/'index.html').write_text('<html>EXISTING GUI AND EXTENSIONS</html>')
        values={'build-source.json':json.dumps({'schema':'ziokt.effort.windows-build.v1','source_commit':'a'*40,'run_id':'123','signing':'unsigned-development'}),'README.md':'development','self-test.json':'{"success":true}','ziokt-effort-windows-x64-unsigned.exe':'unit fixture, not runnable','ziokt-effort-windows-x64-unsigned.msi':'unit installer fixture'}
        for name,data in values.items():(source/name).write_text(data)
        (source/'SHA256SUMS').write_text(''.join(hashlib.sha256((source/name).read_bytes()).hexdigest()+'  '+name+'\n' for name in values))
        return source,downloads
    def test_installs_idempotently_preserving_existing_downloads(self):
        with tempfile.TemporaryDirectory() as d:
            source,downloads=self.fixture(Path(d));first=module.install(source,downloads);second=module.install(source,downloads);self.assertEqual(first,second)
            self.assertIn('EXISTING GUI AND EXTENSIONS',(downloads/'index.html').read_text());self.assertEqual((downloads/'index.html').read_text().count('<h2 id="effort-title">'),1)
            self.assertTrue((downloads/'effort'/('a'*40)/'ziokt-effort-windows-x64-unsigned.msi').is_file())
    def test_rejects_changed_ci_bytes_before_modifying_index(self):
        with tempfile.TemporaryDirectory() as d:
            source,downloads=self.fixture(Path(d));(source/'ziokt-effort-windows-x64-unsigned.exe').write_text('tampered')
            with self.assertRaises(ValueError):module.install(source,downloads)
            self.assertEqual((downloads/'index.html').read_text(),'<html>EXISTING GUI AND EXTENSIONS</html>')
    def test_rejects_checksum_path_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            source,downloads=self.fixture(Path(d));(source/'SHA256SUMS').write_text('a'*64+'  ../outside\n')
            with self.assertRaises(ValueError):module.install(source,downloads)

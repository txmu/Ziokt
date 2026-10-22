import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
spec=importlib.util.spec_from_file_location('android_downloads',Path(__file__).resolve().parents[1]/'tools/install_effort_android_downloads.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class AndroidDownloadsTests(unittest.TestCase):
    def fixture(self,root,native=False):
        source=root/'source';source.mkdir();dest=root/'downloads';dest.mkdir();(dest/'index.html').write_text('<html>EXISTING WINDOWS AND GUI</html>');apk=source/'ziokt-effort-android-universal.apk'
        with zipfile.ZipFile(apk,'w') as z:z.writestr('lib/arm64-v8a/runtime.so' if native else 'classes.dex',b'unit fixture, not an actual APK')
        (source/'build-source.json').write_text(json.dumps({'schema':'ziokt.effort.android-build.v1','source_commit':'a'*40,'min_sdk':28,'apk_bytes':apk.stat().st_size,'run_id':'123'}))
        (source/'signature.txt').write_text('Verified using v2 scheme (APK Signature Scheme v2): true')
        (source/'package-badging.txt').write_text("sdkVersion:'28'")
        (source/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(source.iterdir()) if p.is_file()))
        return source,dest
    def test_preserves_other_installers_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            source,dest=self.fixture(Path(d));self.assertEqual(module.install(source,dest),module.install(source,dest));text=(dest/'index.html').read_text();self.assertIn('EXISTING WINDOWS AND GUI',text);self.assertEqual(text.count('<h2 id="effort-android-title">'),1)
    def test_rejects_tampered_apk(self):
        with tempfile.TemporaryDirectory() as d:
            source,dest=self.fixture(Path(d));(source/'ziokt-effort-android-universal.apk').write_bytes(b'changed')
            with self.assertRaises(ValueError):module.install(source,dest)
            self.assertEqual((dest/'index.html').read_text(),'<html>EXISTING WINDOWS AND GUI</html>')
    def test_rejects_bundled_native_runtime(self):
        with tempfile.TemporaryDirectory() as d:
            source,dest=self.fixture(Path(d),True)
            with self.assertRaises(ValueError):module.install(source,dest)

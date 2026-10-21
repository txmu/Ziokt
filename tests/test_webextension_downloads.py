import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.install_webextension_downloads import install, verified, PACKAGES, START
from tools.package_webextensions import package


class DownloadTests(unittest.TestCase):
    def test_real_packages_publish_idempotently_without_replacing_gui(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';package(source)
            manifest=json.loads((source/'build-source.json').read_text())
            self.assertFalse(manifest['source_dirty'],'release installation requires a clean packaging source')
            destination=root/'downloads';destination.mkdir()
            original='<html><body><a href="gui.apk">Android GUI</a></body></html>'
            (destination/'index.html').write_text(original)
            (destination/'gui.apk').write_bytes(b'existing GUI installer')
            first=install(source,destination,manifest['source_commit'])
            second=install(source,destination,manifest['source_commit'])
            self.assertEqual(first,second)
            self.assertEqual((destination/'index.html').read_text().count(START),1)
            self.assertIn('<a href="gui.apk">Android GUI</a>',(destination/'index.html').read_text())
            self.assertEqual((destination/'gui.apk').read_bytes(),b'existing GUI installer')
            for item in first['packages']:
                self.assertEqual(hashlib.sha256((destination/item['url']).read_bytes()).hexdigest(),item['sha256'])
            target=destination/first['packages'][0]['url'];target.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'immutable release conflict'):
                install(source,destination,manifest['source_commit'])

    def test_bad_digest_or_incomplete_installer_set_never_changes_live_page(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';package(source)
            commit=json.loads((source/'build-source.json').read_text())['source_commit']
            destination=root/'downloads';destination.mkdir();index=destination/'index.html';index.write_text('original GUI page')
            (source/PACKAGES['chromium']).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'digest mismatch'):install(source,destination,commit)
            self.assertEqual(index.read_text(),'original GUI page')
            (source/'SHA256SUMS').write_text('0'*64+'  ../escape\n')
            with self.assertRaises(ValueError):verified(source,commit)


if __name__=='__main__':unittest.main()

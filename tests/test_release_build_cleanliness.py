"""Reproduce the native-reuse download contaminating the release build stamp."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from ziokt import build_info

class BuildCleanlinessTests(unittest.TestCase):
    def test_reuse_cache_outside_checkout_does_not_hide_source_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'checkout';root.mkdir();(root/'ziokt').mkdir()
            source=root/'ziokt/example.py';source.write_text('value = 1\n')
            subprocess.run(['git','init','-q',str(root)],check=True)
            subprocess.run(['git','add','.'],cwd=root,check=True)
            subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture'],cwd=root,check=True)
            with patch.object(build_info,'__file__',str(root/'ziokt/build_info.py')):
                def snapshot():
                    build_info.snapshot.cache_clear();return build_info.snapshot()
                try:
                    self.assertFalse(snapshot()['working_tree_dirty'])
                    cache=root/'reuse-download';cache.mkdir();product=cache/'native.tar.gz';product.write_bytes(b'fixture')
                    self.assertTrue(snapshot()['working_tree_dirty'])
                    moved=base/'runner-temp';cache.rename(moved)
                    self.assertFalse(snapshot()['working_tree_dirty'])
                    source.write_text('value = 2\n')
                    self.assertTrue(snapshot()['working_tree_dirty'])
                finally:build_info.snapshot.cache_clear()

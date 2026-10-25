"""Audit the exact kernel configuration adaptation without building ALFS."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


class AlfsConfigTests(unittest.TestCase):
    def test_target_toolchain_defaults_are_explicit_and_hashed(self):
        source=Path(__file__).resolve().parents[1]/'ci/openci/alfs/configure.py'
        spec=importlib.util.spec_from_file_location('alfs_configuration',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'jhalfs/LFS/lfs.xsl';path.parent.mkdir(parents=True);(root/'evidence').mkdir()
            path.write_text('prefix\ntimeout 60 make oldconfig\nsuffix\n')
            module.prepare_kernel_defaults(root)
            self.assertEqual(path.read_text(),'prefix\ntimeout 60 make olddefconfig\nsuffix\n')
            evidence=json.loads((root/'evidence/kernel-config-adaptation.json').read_text())
            self.assertNotEqual(evidence['original_sha256'],evidence['patched_sha256'])
            with self.assertRaises(ValueError):module.prepare_kernel_defaults(root)

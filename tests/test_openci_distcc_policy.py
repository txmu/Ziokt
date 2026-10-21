"""Compiler routing policy only; actual distcc compilation is CI-only."""
import importlib.util
from pathlib import Path
import tempfile,unittest

spec=importlib.util.spec_from_file_location('distcc_target',Path(__file__).resolve().parents[1]/'ci/openci/distcc_target.py');policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)

class CompilerPolicyTests(unittest.TestCase):
    def test_only_absolute_approved_cross_toolchain_is_remote(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(policy.remote_compiler(root+'/aarch64-buildroot-linux-gnu-gcc.br_real',root))
            self.assertTrue(policy.remote_compiler(root+'/x86_64-buildroot-linux-gnu-g++',root))
            self.assertFalse(policy.remote_compiler('/usr/bin/gcc',root))
            self.assertFalse(policy.remote_compiler(root+'/gcc',root))
            self.assertFalse(policy.remote_compiler('aarch64-buildroot-linux-gnu-gcc',root))
            self.assertFalse(policy.remote_compiler('/unapproved/aarch64-buildroot-linux-gnu-gcc',root))

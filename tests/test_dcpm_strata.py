"""Tests for dCPM Strata backend: resolution, identity, rollback, permissions."""
import json
from pathlib import Path
import tempfile
import unittest

from ziokt.dcpm_strata import DCPMStrataManager, parse_package_spec


class DCPMStrataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.mgr = DCPMStrataManager(self.root)
        self.pubkey = "a" * 64
        self.mgr.authorize_publisher(self.pubkey)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_package_spec(self):
        spec1 = parse_package_spec("editor")
        self.assertEqual(spec1['name'], "editor")
        self.assertEqual(spec1['slot'], "0")
        self.assertEqual(spec1['category'], "app")

        spec2 = parse_package_spec("dev-util/editor:1#2.0.0@" + ("b" * 64))
        self.assertEqual(spec2['category'], "dev-util")
        self.assertEqual(spec2['name'], "editor")
        self.assertEqual(spec2['slot'], "1")
        self.assertEqual(spec2['version'], "2.0.0")
        self.assertEqual(spec2['publisher'], "b" * 64)

    def test_unauthorized_publisher_rejected(self):
        untrusted_key = "f" * 64
        files = {"bin/evil": b"echo evil"}
        with self.assertRaises(PermissionError):
            self.mgr.stage_package("app/evil:0#1.0.0", files, untrusted_key)

    def test_install_and_commit_slot_projection(self):
        files = {
            "bin/editor": b"#!/bin/sh\necho 'editor v1.0.0'\n",
            "etc/editor.conf": b"key=value\n"
        }
        res = self.mgr.stage_package("app/editor:0#1.0.0", files, self.pubkey)
        self.assertEqual(res['status'], 'staged')

        # File exists in slot
        slot_file = self.root / "slots/editor/0/1.0.0/bin/editor"
        self.assertTrue(slot_file.is_file())

        # Not yet active in root
        active_bin = self.root / "bin/editor"
        self.assertFalse(active_bin.exists())

        # Commit activation
        self.mgr.commit("editor", "0")
        self.assertTrue(active_bin.exists())
        self.assertTrue(active_bin.is_symlink())
        self.assertEqual(active_bin.read_bytes(), b"#!/bin/sh\necho 'editor v1.0.0'\n")

    def test_atomic_rollback(self):
        # Version 1.0.0
        files_v1 = {"bin/editor": b"version 1.0.0"}
        self.mgr.stage_package("app/editor:0#1.0.0", files_v1, self.pubkey)
        self.mgr.commit("editor", "0")

        # Upgrade to 2.0.0
        files_v2 = {"bin/editor": b"version 2.0.0"}
        self.mgr.stage_package("app/editor:0#2.0.0", files_v2, self.pubkey)
        self.mgr.commit("editor", "0")
        self.assertEqual((self.root / "bin/editor").read_bytes(), b"version 2.0.0")

        # Rollback to 1.0.0
        res = self.mgr.rollback("editor", "0")
        self.assertEqual(res['version'], "1.0.0")
        self.assertEqual((self.root / "bin/editor").read_bytes(), b"version 1.0.0")

    def test_strata_list_export_format(self):
        files = {"bin/editor": b"editor binary"}
        self.mgr.stage_package("app/editor:0#1.0.0", files, self.pubkey)
        self.mgr.commit("editor", "0")

        export_quiet = self.mgr.list_packages(quiet=True)
        self.assertEqual(export_quiet, f"editor:0#1.0.0@{self.pubkey}")

        tsv = self.mgr.list_packages(format='tsv')
        self.assertIn(f"editor\t1.0.0\tactive\tdcpm", tsv)


if __name__ == '__main__':
    unittest.main()

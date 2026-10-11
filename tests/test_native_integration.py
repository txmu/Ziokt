"""Exercise real production entrypoints; all state stays in private temp roots."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ziokt.client import NativeClient
from ziokt.cli import inspect, write_exclusive
from ziokt.config import fingerprint, load
from ziokt.protocol import ProtocolError

ROOT = Path(__file__).resolve().parents[1]
S = Path(os.environ.get("ZIOKT_SHADOW6_ROOT", ROOT.parent / "Shadow6")).absolute()
C = Path(os.environ.get("ZIOKT_CORIUM_ROOT", ROOT.parent / "Corium")).absolute()


def tree_state(base):
    return {str(p.relative_to(base)): (p.lstat().st_mode, p.read_bytes() if p.is_file() else None)
            for p in base.rglob("*")}


class NativeFixture(unittest.TestCase):
    def setUp(self):
        if not (S / "CLI/shadow6.py").is_file() or not (C / "corix_v108.sh").is_file():
            self.fail("real Shadow6 and Corium checkouts are required")
        self.temp = tempfile.TemporaryDirectory(prefix="ziokt-integration-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home, self.state = self.base / "home", self.base / "corium-state"
        self.home.mkdir(); self.state.mkdir()
        self.env_patch = patch.dict(os.environ, {"HOME": str(self.home)}, clear=False)
        self.env_patch.start(); self.addCleanup(self.env_patch.stop)
        self.sconfig = self.base / "shadow6.json"
        self.cconfig = self.state / "etc/corix/networks/default/corix.conf"
        self.cconfig.parent.mkdir(parents=True)
        write_exclusive(self.sconfig, {"schema": "ziokt.provider.v1", "enabled": True,
                                      "federation_id": "test", "provider_id": "shadow6-local"})
        self.cconfig.write_text("[ziokt]\nenabled = TRUE\nfederation_id = test\nprovider_id = corium-local\nallow_mutations = FALSE\n")
        self.cconfig.chmod(0o600)
        self.providers = [
            {"native_project": "shadow6", "provider_id": "shadow6-local", "root": str(S),
             "native_config": str(self.sconfig), "entrypoint_digest": fingerprint(S / "CLI/shadow6.py"),
             "network_id": None, "state_root": None},
            {"native_project": "corium", "provider_id": "corium-local", "root": str(C),
             "native_config": str(self.cconfig), "entrypoint_digest": fingerprint(C / "corix_v108.sh"),
             "network_id": "default", "state_root": str(self.state)}]
        self.federation = {"schema": "ziokt.federation.v1", "enabled": True,
                           "federation_id": "test", "providers": self.providers}


class IntegrationTests(NativeFixture):
    def test_real_native_doctor_and_no_state_changes(self):
        before = tree_state(self.base)
        report = inspect(self.federation, "doctor", "all")
        self.assertTrue(report["healthy"], report)
        self.assertEqual(len(report["providers"]), 2)
        self.assertEqual(tree_state(self.base), before)

    def test_union_of_native_service_package_and_strata(self):
        registry = self.home / ".config/shadow6/services.json"
        registry.parent.mkdir(mode=0o700, parents=True)
        # An unresolved record is a valid native service; no fake network claim.
        write_exclusive(registry, {"schema": "shadow6.service-registry.v2", "services": {
            "test/wiki": {"name": "test/wiki", "state": "unresolved", "spec": {},
                          "protocolContext": {"invalid": "validator-must-reject"}}}})
        bad = inspect(self.federation, "inventory", "all")
        self.assertFalse(bad["healthy"])
        registry.unlink()
        # Let the actual native authority construct a configured, stopped state.
        sys.path.insert(0, str(S))
        from Deployment.service_registry import ServiceRegistry
        from Deployment.core_catalog import CoreCatalog
        native = ServiceRegistry(registry, CoreCatalog(S))
        material = self.base / "native-go.json"
        write_exclusive(material, {"secret": "DO_NOT_DISCLOSE_NATIVE_MATERIAL"})
        native.create("test/wiki", core="go", config={"config_path": str(material)})
        installed = self.state / "var/lib/corix/networks/default/installed/docs_wiki-0"
        installed.mkdir(parents=True)
        installed.chmod(0o755); installed.parent.chmod(0o755)
        for key, value in {"name": "docs/wiki", "slot": "0", "version": "1.2"}.items():
            (installed / key).write_text(value + "\n")
            (installed / key).chmod(0o644)
        strata = self.state / "usr/corix/strata/networks/default/build"
        strata.mkdir(parents=True)
        strata.chmod(0o755); strata.parent.chmod(0o755)
        before = tree_state(self.base)
        report = inspect(self.federation, "inventory", "all")
        self.assertTrue(report["healthy"], report)
        self.assertEqual({r["kind"] for r in report["objects"]}, {"service", "package", "environment"})
        self.assertEqual({r["native_id"] for r in report["objects"]}, {"test/wiki", "docs/wiki:0", "build"})
        self.assertTrue(all(r["observation"] == "stored-metadata" for r in report["objects"]))
        self.assertEqual(tree_state(self.base), before)
        self.assertNotIn("config_path", json.dumps(report))
        self.assertNotIn("DO_NOT_DISCLOSE_NATIVE_MATERIAL", json.dumps(report))

    def test_native_disabled_is_not_overridden_by_federation(self):
        value = json.loads(self.sconfig.read_text()); value["enabled"] = False
        self.sconfig.write_text(json.dumps(value))
        report = inspect(self.federation, "doctor", "all")
        self.assertFalse(report["healthy"])
        self.assertEqual(report["providers"][0]["error"]["code"], "ZIOKT_DISABLED")
        self.assertTrue(report["providers"][1]["healthy"])

    def test_disabled_federation_starts_no_provider(self):
        self.federation["enabled"] = False
        with patch("ziokt.cli.NativeClient", side_effect=AssertionError("provider started")):
            report = inspect(self.federation, "inventory", "all")
        self.assertEqual(report["providers"], [])

    def test_provider_digest_scope_and_mutation_denial(self):
        client = NativeClient("test", self.providers[0])
        with self.assertRaises(ProtocolError) as mutation:
            client.call("operation.commit", {"operation_id": "not-approved", "plan_digest": "sha256:" + "0" * 64})
        self.assertEqual(mutation.exception.code, "MUTATION_DISABLED")
        with self.assertRaises(ProtocolError) as scope:
            NativeClient("other", self.providers[1]).call("status.get")
        self.assertEqual(scope.exception.code, "SCOPE_MISMATCH")
        stale = {**self.providers[0], "entrypoint_digest": "sha256:" + "0" * 64}
        with self.assertRaises(ProtocolError) as digest:
            NativeClient("test", stale).call("status.get")
        self.assertEqual(digest.exception.code, "STALE_PROVIDER")

    def test_native_configuration_symlink_bad_modes_duplicates_and_unknown_fields(self):
        for content in ("[ziokt]\nenabled = true\n", "[ziokt]\nenabled=TRUE\nenabled=FALSE\n",
                        "[ziokt]\nunknown=1\n", "[ziokt]\nenabled=FALSE\n[ziokt]\nenabled=FALSE\n"):
            self.cconfig.write_text(content)
            report = inspect(self.federation, "doctor", "all")
            self.assertFalse(report["providers"][1]["healthy"])
        self.sconfig.chmod(0o644)
        report = inspect(self.federation, "doctor", "all")
        self.assertEqual(report["providers"][0]["error"]["code"], "UNSAFE_FILE")
        self.sconfig.chmod(0o600)
        target = self.base / "actual.json"
        self.sconfig.rename(target); self.sconfig.symlink_to(target)
        report = inspect(self.federation, "doctor", "all")
        self.assertFalse(report["providers"][0]["healthy"])

    def test_monolith_copy_runs_without_ziokt_or_native_dependencies(self):
        script = self.base / "standalone-corix.sh"
        shutil.copyfile(C / "corix_v108.sh", script)
        empty = self.base / "empty-state"
        result = subprocess.run(["bash", str(script), "ziokt", "capabilities"],
                                env={**os.environ, "CORIUM_ROOT": str(empty)},
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["enabled"])
        self.assertFalse(empty.exists())

    def test_federation_config_scope_and_init_no_overwrite(self):
        path = self.base / "federation.json"
        write_exclusive(path, self.federation)
        self.assertEqual(load(path), self.federation)
        with self.assertRaises(FileExistsError):
            write_exclusive(path, {"overwrite": True})
        self.assertEqual(load(path), self.federation)
        self.providers[1]["native_config"] = str(self.base / "wrong.conf")
        path.write_text(json.dumps(self.federation))
        with self.assertRaises(ProtocolError):
            load(path)


if __name__ == "__main__":
    unittest.main()

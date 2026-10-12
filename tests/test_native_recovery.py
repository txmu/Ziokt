"""Actual native Phoenix cold restore and declarative Shadow6 reconstruction."""
import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

from test_native_integration import NativeFixture, C, S
from ziokt.client import NativeClient
from ziokt.config import fingerprint


class NativeRecoveryTests(NativeFixture):
    def test_native_phoenix_checkpoint_destroy_and_explicit_restore(self):
        sys.path.insert(0, str(C))
        from test_core import Fixture
        fixture = Fixture(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        store = self.base/"phoenix-artifacts"; store.mkdir(mode=0o700)
        config = fixture.etc/"corix.conf"
        config.write_text("[ziokt]\nenabled=TRUE\nfederation_id=test\nprovider_id=corium-local\nallow_mutations=TRUE\nallowed_operations=recovery.checkpoint,recovery.restore\nallowed_resources=*\nartifact_root="+str(store)+"\n"); config.chmod(0o600)
        client = NativeClient("test", {"native_project": "corium", "provider_id": "corium-local", "root": str(C),
            "native_config": str(config), "state_root": str(fixture.root), "network_id": "default", "entrypoint_digest": fingerprint(C/"corix_v108.sh")})
        def execute(op_id, action, resource, arguments):
            prepared = client.call("operation.prepare", {"operation_id": op_id, "action": action, "resource": resource,
                "arguments": arguments, "expected_revision": None})
            return client.call("operation.commit", {"operation_id": op_id, "plan_digest": prepared["plan_digest"]})
        checkpoint = execute("phoenix-export", "recovery.checkpoint", "checkpoint:default", {"height": 0})
        self.assertTrue(checkpoint["result"]["native_signature_verified"])
        artifact = checkpoint["result"]["checkpoint_digest"]
        original = json.loads((store/artifact[7:]).read_text())["state"]
        with closing(sqlite3.connect(fixture.chain)) as db, db:
            for table in ("blocks", "validators", "system_params"): db.execute("DELETE FROM "+table)
        with closing(sqlite3.connect(fixture.forum)) as db, db: db.execute("DELETE FROM nns_records")
        result = execute("phoenix-restore", "recovery.restore", "recovery:default", {"checkpoint_digest": artifact})
        self.assertFalse(result["result"]["running_state_restored"])
        restored = fixture.semantic()
        self.assertEqual(restored["application"], original["application_tables"])
        self.assertEqual(restored["chain"]["validators"], original["chain_tables"]["validators"])

    def test_shadow6_restore_materials_as_stopped_native_services(self):
        sys.path[:0] = [str(S), str(S/"integration"), str(S/"Crosed")]
        from stack_test import generate_configs
        from Deployment.service_registry import ServiceRegistry
        from Deployment.core_catalog import CoreCatalog
        from Deployment.protocol_context import minimal_context
        material = self.base/"native-material"
        asyncio.run(generate_configs("shadow6-go", material, 24567, 24568))
        config_file = next(p for p in material.glob("*.json") if json.loads(p.read_text()).get("role") == "client")
        config_file.chmod(0o600)
        registry = ServiceRegistry(catalog=CoreCatalog(S))
        context = minimal_context("go"); context["role"] = "client"
        registry.create("test/recovered", core="go", config={"config_path": str(config_file)}, context=context)
        registry.apply("test/recovered")
        store = self.base/"shadow-artifacts"; store.mkdir(mode=0o700)
        config = json.loads(self.sconfig.read_text())
        config.update(allow_mutations=True, allowed_operations=["recovery.checkpoint", "recovery.restore"],
                      allowed_resources=["checkpoint:shadow6", "recovery:shadow6"], artifact_root=str(store))
        self.sconfig.write_text(json.dumps(config))
        client = NativeClient("test", self.providers[0])
        plan = client.call("operation.prepare", {"operation_id": "shadow-export", "action": "recovery.checkpoint",
            "resource": "checkpoint:shadow6", "arguments": {"services": ["test/recovered"], "include_secrets": True}, "expected_revision": None})
        result = client.call("operation.commit", {"operation_id": "shadow-export", "plan_digest": plan["plan_digest"]})
        new_home = self.base/"restored-home"; new_home.mkdir(mode=0o700)
        with patch.dict(os.environ, {"HOME": str(new_home)}):
            plan = client.call("operation.prepare", {"operation_id": "shadow-restore", "action": "recovery.restore",
                "resource": "recovery:shadow6", "arguments": {"checkpoint_digest": result["result"]["checkpoint_digest"]}, "expected_revision": None})
            done = client.call("operation.commit", {"operation_id": "shadow-restore", "plan_digest": plan["plan_digest"]})
            self.assertFalse(done["result"]["running_state_restored"])
            native = ServiceRegistry(catalog=CoreCatalog(S))
            item = native.services["test/recovered"]
            self.assertNotEqual(item["state"], "running")
            self.assertEqual(item["coreBinding"]["core"], "go")
            self.assertIsNone(item.get("deploymentLock"))
            self.assertEqual(json.loads(Path(item["coreBinding"]["config"]["config_path"]).read_text()), json.loads(config_file.read_text()))


if __name__ == "__main__": unittest.main()

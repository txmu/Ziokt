import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest

from test_native_integration import NativeFixture, C, S
from ziokt.client import NativeClient
from ziokt.protocol import ProtocolError
from ziokt.workflow import WorkflowJournal


class OperationTests(NativeFixture):
    def enable_writes(self):
        value = json.loads(self.sconfig.read_text())
        value.update(allow_mutations=True, allowed_operations=["service.stop"], allowed_resources=["*"])
        self.sconfig.write_text(json.dumps(value))
        self.cconfig.write_text("[ziokt]\nenabled=TRUE\nfederation_id=test\nprovider_id=corium-local\nallow_mutations=TRUE\nallowed_operations=artifact.stage\nallowed_resources=*\n")
        sys.path.insert(0, str(C))
        from test_gateway import schema
        dht = self.state / "var/lib/corix/p2p/dht.db"
        dht.parent.mkdir(parents=True)
        db = sqlite3.connect(dht)
        try:
            db.executescript(schema("_init_dht_db"))
        finally:
            db.close()

    def test_real_native_artifact_stage_idempotence_and_outbox(self):
        self.enable_writes()
        data = b"Ziokt native content fixture"
        resource = "sha256:" + hashlib.sha256(data).hexdigest()
        client = NativeClient("test", self.providers[1])
        params = {"operation_id": "stage-test", "action": "artifact.stage", "resource": resource,
                  "arguments": {"data_base64": base64.b64encode(data).decode()}, "expected_revision": None}
        first = client.call("operation.prepare", params)
        self.assertEqual(client.call("operation.prepare", params)["plan_digest"], first["plan_digest"])
        result = client.call("operation.commit", {"operation_id": params["operation_id"], "plan_digest": first["plan_digest"]})
        self.assertEqual(result["state"], "committed")
        self.assertEqual(client.call("operation.commit", {"operation_id": params["operation_id"], "plan_digest": first["plan_digest"]}), result)
        with sqlite3.connect(self.state / "var/lib/corix/p2p/dht.db") as db:
            row = db.execute("SELECT file_path,size FROM local_chunks WHERE hash=?", (resource[7:],)).fetchone()
        self.assertEqual(Path(row[0]).read_bytes(), data)
        events = client.call("events.list")
        self.assertEqual(len(events["events"]), 1)
        with self.assertRaises(ProtocolError) as conflict:
            client.call("operation.prepare", {**params, "resource": "sha256:" + "0" * 64})
        self.assertEqual(conflict.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_same_service_operation_contract_for_all_twelve_cores(self):
        self.enable_writes()
        sys.path.insert(0, str(S))
        from Deployment.core_catalog import CoreCatalog
        from Deployment.service_registry import ServiceRegistry
        from Deployment.service_storage import atomic_write
        from Deployment.profile_registry import CORE_IDS
        material = self.base / "material.json"; atomic_write(material, b"{}")
        registry = ServiceRegistry(self.home / ".config/shadow6/services.json", CoreCatalog(S))
        for core in CORE_IDS:
            registry.create("test/" + core, core=core, config={"config_path": str(material)})
        client = NativeClient("test", self.providers[0])
        records = client.objects("service")
        self.assertEqual(len(records), 12)
        for record in records:
            op_id = "stop-" + record["properties"]["core"]
            plan = client.call("operation.prepare", {"operation_id": op_id, "action": "service.stop",
                   "resource": record["native_id"], "arguments": {}, "expected_revision": record["revision"]})
            done = client.call("operation.commit", {"operation_id": op_id, "plan_digest": plan["plan_digest"]})
            self.assertEqual(done["state"], "committed", record["properties"]["core"])
        self.assertTrue(all(r["state"] == "stopped" for r in client.objects("service")))

    def test_workflow_persists_and_resumes_native_result(self):
        self.enable_writes()
        data = b"workflow fixture"
        manifest = {"schema": "ziokt.workflow.v1", "workflow_id": "test-workflow", "steps": [{
            "step_id": "content", "provider_id": "corium-local", "action": "artifact.stage",
            "resource": "sha256:" + hashlib.sha256(data).hexdigest(),
            "arguments": {"data_base64": base64.b64encode(data).decode()},
            "expected_revision": None, "depends_on": []}]}
        path = self.base / "workflow.sqlite"
        with WorkflowJournal(path) as journal:
            plan = journal.plan(manifest, self.federation)
            done = journal.apply("test-workflow", self.federation, plan["plan_digest"], confirmed=True)
            self.assertEqual(done["state"], "committed")
        with WorkflowJournal(path) as journal:
            self.assertEqual(journal.apply("test-workflow", self.federation, plan["plan_digest"], confirmed=True), done)


if __name__ == "__main__":
    unittest.main()

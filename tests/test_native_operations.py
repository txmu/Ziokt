import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import os
import subprocess
import time
from contextlib import closing
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
        with closing(sqlite3.connect(self.state / "var/lib/corix/p2p/dht.db")) as db:
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

    def test_signed_native_package_install_activate_and_tamper_rejection(self):
        sys.path.insert(0, str(S/"Package-Manager"))
        from shadow6_pkg import keygen, build_package
        from ziokt.artifacts import ArtifactStore
        private, trust = self.base/"publisher.key", self.base/"trust.json"
        keygen(private, trust, "test-publisher"); trust.chmod(0o600)
        payload = self.base/"payload"; payload.mkdir(); (payload/"readme").write_bytes(b"signed native app")
        archive = self.base/"app.zip"
        build_package(payload, archive, private, "test-publisher", "app", "wiki-client", "1.0.0")
        store = ArtifactStore(self.base/"artifacts"); artifact = store.put(archive.read_bytes())
        packages = self.base/"packages"; packages.mkdir(mode=0o700)
        config = json.loads(self.sconfig.read_text())
        config.update(allow_mutations=True, allowed_operations=["package.install", "package.activate"],
                      allowed_resources=["app/wiki-client@1.0.0"], package_root=str(packages),
                      package_trust_file=str(trust), artifact_root=str(store.root))
        self.sconfig.write_text(json.dumps(config))
        client = NativeClient("test", self.providers[0])
        for action, arguments in (("package.install", {"artifact_digest": artifact}), ("package.activate", {})):
            op_id = action.replace(".", "-")
            prepared = client.call("operation.prepare", {"operation_id": op_id, "action": action,
                "resource": "app/wiki-client@1.0.0", "arguments": arguments, "expected_revision": None})
            done = client.call("operation.commit", {"operation_id": op_id, "plan_digest": prepared["plan_digest"]})
            self.assertTrue(done["result"]["native_signature_verified"])
        base = packages/"app/wiki-client"
        self.assertEqual(json.loads((base/"active.json").read_text())["version"], "1.0.0")
        (base/"versions/1.0.0/readme").write_bytes(b"tampered")
        with self.assertRaises(ProtocolError):
            client.call("operation.prepare", {"operation_id": "bad-activation", "action": "package.activate",
                        "resource": "app/wiki-client@1.0.0", "arguments": {}, "expected_revision": None})

    def test_real_process_crash_after_content_write_reconciles_without_duplicate_event(self):
        self.enable_writes()
        data = b"persist native effect before SIGKILL"
        resource = "sha256:" + hashlib.sha256(data).hexdigest()
        params = {"operation_id": "crash-test", "action": "artifact.stage", "resource": resource,
                  "arguments": {"data_base64": base64.b64encode(data).decode()}, "expected_revision": None, "lease_ms": 1000}
        client = NativeClient("test", self.providers[1]); plan = client.call("operation.prepare", params)
        # Test-only injection outside production source; execute the actual
        # generated native journal and native filesystem/database write first.
        code = '''import os,sys,signal
from pathlib import Path
from ziokt import _runtime as r
root=Path(sys.argv[1]); config=r.load_config("corium",root/"etc/corix/networks/default/corix.conf")
original=r.operation_execute
def crash(*args,**kw):
    original(*args,**kw)
    os.kill(os.getpid(),signal.SIGKILL)
r.operation_execute=crash
r.operation_dispatch("corium",root,"default",config,"operation.commit",{"operation_id":"crash-test","plan_digest":sys.argv[2]})
'''
        process = subprocess.run([sys.executable, "-c", code, str(self.state), plan["plan_digest"]], timeout=10)
        self.assertLess(process.returncode, 0)
        self.assertEqual(client.call("operation.status", {"operation_id": "crash-test"})["state"], "unknown")
        remaining = (plan["expires_at_ms"]-int(time.time()*1000))/1000
        if remaining > 0: time.sleep(remaining+.02)
        done = client.call("operation.reconcile", {"operation_id": "crash-test"})
        self.assertEqual(done["state"], "committed")
        self.assertEqual(client.call("operation.reconcile", {"operation_id": "crash-test"}), done)
        self.assertEqual(len(client.call("events.list")["events"]), 1)


if __name__ == "__main__":
    unittest.main()

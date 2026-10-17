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
        store = ArtifactStore(self.base/"artifacts")
        from ziokt.community import Community, RIGHTS, create_policy
        from ziokt.community_native import materialize
        from ziokt.security import sign
        import secrets
        community_private, content_key = secrets.token_bytes(32), secrets.token_bytes(32)
        community_public = sign({}, community_private, "test")["public_key"]
        policy = create_policy(community_private, "test", {community_public: sorted(RIGHTS)})
        with Community(self.base/"package-community", policy, community_public, content_key) as community:
            materials = community.put_file(archive.read_bytes())
            community.publish(community_private, "packages", "wiki-client", {"name": "wiki-client", "version": "1.0.0",
                "native_kind": "shadow6-app", "native_signature": "original embedded package manifest", **materials})
            handoff = materialize(community, materials, store)
            self.assertFalse(handoff["native_signature_verified"])
            artifact = handoff["artifact_digest"]
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

    def test_mcp_native_read_plan_apply_and_scope_boundary(self):
        from ziokt.mcp import Service
        self.enable_writes()
        federation=self.base/'mcp-federation.json'
        federation.write_text(json.dumps(self.federation));federation.chmod(0o600)
        scopes=['ziokt:read','ziokt:apply','corium:read','corium:artifact.stage:plan']
        config={'state':str(self.base/'mcp-state'),'issuer':'https://test.example','clients':{'operator':{'scopes':scopes,'redirect_uris':[]}},'writes_enabled':True,'federation':str(federation)}
        service=Service(config);principal={'client':'operator','scopes':set(scopes),'expires':int(time.time())+300}
        status=service.call(principal,'corium_local_status_get',{'params':{}})
        self.assertFalse(status['isError'],status)
        data=b'actual MCP to native artifact';resource='sha256:'+hashlib.sha256(data).hexdigest()
        plan=service.call(principal,'corium_local_artifact_stage_plan',{'resource':resource,'arguments':{'data_base64':base64.b64encode(data).decode()},'expected_revision':None,'operation_id':'mcp-stage'},'plan-operation-key')
        self.assertFalse(plan['isError'],plan);plan=plan['structuredContent']
        done=service.call(principal,'ziokt_workflow_apply',{'workflow_id':plan['workflow_id'],'plan_digest':plan['plan_digest'],'confirm':True},'apply-operation-key')
        self.assertFalse(done['isError'],done);self.assertEqual(done['structuredContent']['state'],'committed')
        with closing(sqlite3.connect(self.state/'var/lib/corix/p2p/dht.db')) as db:
            stored=db.execute('SELECT file_path FROM local_chunks WHERE hash=?',(resource[7:],)).fetchone()[0]
        self.assertEqual(Path(stored).read_bytes(),data)

    def test_mcp_cbb_uses_real_native_signature_verifier_and_database(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from ziokt.mcp_corium import CoriumProtocol
        self.enable_writes()
        from test_gateway import schema
        key=ec.generate_private_key(ec.SECP256K1())
        public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
        identity=hashlib.sha256(public.encode()).hexdigest()
        keys=self.state/'etc/corix/networks/default'
        private=keys/'identity.key';private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));private.chmod(0o600)
        (keys/'identity.key.pub').write_text(public+'\n')
        chain=self.state/'var/lib/corix/networks/default/blockchain/chain.db';chain.parent.mkdir(parents=True)
        forum=self.state/'var/lib/corix/networks/default/forum/forum.db';forum.parent.mkdir(parents=True)
        with closing(sqlite3.connect(chain)) as db:
            db.executescript(schema('_init_blockchain_db'));db.execute('INSERT INTO validators(public_key,public_key_hash,stake) VALUES (?,?,?)',(public,identity,1000));db.commit()
        with closing(sqlite3.connect(forum)) as db:db.executescript(schema('_init_app_db'))
        from unittest.mock import patch
        with patch.dict(os.environ,{'CORIUM_ROOT':str(self.state),'CORIUM_NETWORK_ID':'default'}):
            native=CoriumProtocol(self.providers[1]);result=native.publish_cbb('Actual MCP emergency bulletin 世界')
            self.assertTrue(result['native_verified'])
            messages=native.call('CBB_SYNC_REQUEST','')['data']
            self.assertEqual(messages[0]['message'],'Actual MCP emergency bulletin 世界')
            with closing(sqlite3.connect(forum)) as db:db.execute("UPDATE cbb_messages SET signature='00'");db.commit()
            with self.assertRaises(ProtocolError):native.call('CBB_SYNC_REQUEST','')


if __name__ == "__main__":
    unittest.main()

"""Native rejection of superseded signed coordinator terms."""
import json
import sys
from test_native_integration import NativeFixture, S
from ziokt.client import NativeClient
from ziokt.control import LeaderAuthority
from ziokt.protocol import ProtocolError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


class FenceTests(NativeFixture):
    def test_native_provider_fences_old_coordinator_and_preserves_new_intent(self):
        sys.path.insert(0, str(S))
        from Deployment.service_registry import ServiceRegistry
        from Deployment.core_catalog import CoreCatalog
        from Deployment.service_storage import atomic_write
        material = self.base/"material.json"; atomic_write(material, b"{}")
        registry = ServiceRegistry(catalog=CoreCatalog(S))
        registry.create("test/fenced", core="go", config={"config_path": str(material)})
        key = Ed25519PrivateKey.generate()
        private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        config = json.loads(self.sconfig.read_text()); config.update(allow_mutations=True,
            allowed_operations=["service.stop"], allowed_resources=["test/fenced"], coordinator_public_key=public)
        self.sconfig.write_text(json.dumps(config))
        client = NativeClient("test", self.providers[0]); revision = client.objects("service")[0]["revision"]
        def params(op_id): return {"operation_id": op_id, "action": "service.stop", "resource": "test/fenced", "arguments": {}, "expected_revision": revision}
        with LeaderAuthority(self.base/"leaders.sqlite") as authority:
            first = authority.acquire("test", "one")
            with self.assertRaises(ProtocolError): authority.acquire("test", "two")
            old_params = params("old-term")
            old_params["fence"] = authority.token("test", "one", "shadow6-local", old_params, private)
            old = client.call("operation.prepare", old_params)
            authority.release("test", "one")
            latest = authority.acquire("test", "two"); self.assertGreater(latest["term"], first["term"])
            new_params = params("new-term")
            new_params["fence"] = authority.token("test", "two", "shadow6-local", new_params, private)
            new = client.call("operation.prepare", new_params)
            with self.assertRaises(ProtocolError) as error:
                client.call("operation.commit", {"operation_id": "old-term", "plan_digest": old["plan_digest"]})
            self.assertEqual(error.exception.code, "STALE_FENCE")
            result = client.call("operation.commit", {"operation_id": "new-term", "plan_digest": new["plan_digest"]})
            self.assertEqual(result["state"], "committed")
            no_token = params("missing-fence")
            no_token["expected_revision"] = client.objects("service")[0]["revision"]
            with self.assertRaises(ProtocolError) as required: client.call("operation.prepare", no_token)
            self.assertEqual(required.exception.code, "FENCE_REQUIRED")

    def test_two_step_workflow_keeps_attempt_owner_separate_from_leader(self):
        from ziokt.workflow import WorkflowJournal
        sys.path.insert(0,str(S))
        from Deployment.service_registry import ServiceRegistry
        from Deployment.core_catalog import CoreCatalog
        from Deployment.service_storage import atomic_write
        material=self.base/'workflow-material.json';atomic_write(material,b'{}')
        registry=ServiceRegistry(catalog=CoreCatalog(S))
        for name in ('first','second'):registry.create('test/'+name,core='go',config={'config_path':str(material)})
        key=Ed25519PrivateKey.generate()
        private=key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())
        public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
        config=json.loads(self.sconfig.read_text());config.update(allow_mutations=True,
            allowed_operations=['service.stop'],allowed_resources=['test/first','test/second'],coordinator_public_key=public)
        self.sconfig.write_text(json.dumps(config))
        records=NativeClient('test',self.providers[0]).objects('service')
        steps=[{'step_id':str(i),'provider_id':'shadow6-local','action':'service.stop','resource':record['native_id'],
                'arguments':{},'expected_revision':record['revision'],'depends_on':[] if i==0 else ['0']}
               for i,record in enumerate(records)]
        manifest={'schema':'ziokt.workflow.v1','workflow_id':'fenced-workflow','steps':steps}
        with LeaderAuthority(self.base/'workflow-leader.sqlite') as authority,WorkflowJournal(self.base/'workflow.sqlite') as journal:
            plan=journal.plan(manifest,self.federation)
            done=journal.apply('fenced-workflow',self.federation,plan['plan_digest'],confirmed=True,leadership=(authority,'leader',private))
            self.assertEqual(done['state'],'committed');self.assertFalse(done['global_atomicity'])
            self.assertNotIn('application_health',done)
            self.assertEqual(len(done['steps']),2)
            self.assertEqual(journal.db.execute('SELECT count(*) FROM attempts').fetchone()[0],0)

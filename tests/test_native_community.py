"""Community operation receipts from real Corium execution, not catalog claims."""
import base64
import secrets
import unittest

import test_native_operations as operations
from ziokt.community import Community, RIGHTS, create_policy, content_id
from ziokt.community_native import native_workflow
from ziokt.protocol import ProtocolError
from ziokt.security import sign
from ziokt.workflow import WorkflowJournal


class CommunityNativeTests(operations.NativeFixture):
    enable_writes = operations.OperationTests.enable_writes

    def test_actual_native_workflow_and_portable_receipt(self):
        self.enable_writes()
        private, key = secrets.token_bytes(32), secrets.token_bytes(32)
        public = sign({}, private, 'test')['public_key']
        policy = create_policy(private, 'test', {public: sorted(RIGHTS)})
        data = b'community native operation'
        manifest = {'schema': 'ziokt.workflow.v1', 'workflow_id': 'community-stage', 'steps': [{
            'step_id': 'stage', 'provider_id': 'corium-local', 'action': 'artifact.stage', 'resource': content_id(data),
            'arguments': {'data_base64': base64.b64encode(data).decode()}, 'expected_revision': None, 'depends_on': []}]}
        with Community(self.base/'community', policy, public, key) as community, WorkflowJournal(self.base/'workflow.sqlite') as journal:
            planned = native_workflow(community, private, self.federation, journal, manifest, domain='hosting', object_key='archive')
            digest = planned['plan']['plan_digest']
            with self.assertRaises(ProtocolError):
                native_workflow(community, private, self.federation, journal, manifest, domain='hosting', object_key='archive', apply=True, expected_digest=digest)
            done = native_workflow(community, private, self.federation, journal, manifest, domain='hosting', object_key='archive', apply=True, expected_digest=digest, confirmed=True)
            self.assertEqual(done['plan']['state'], 'committed')
            self.assertIn(b'"native_registered":true', community.get_file(done['materials']))
            self.assertFalse(done['runtime_ready'])
            with Community(self.base/'new-node', policy, public, key) as restored:
                restored.restore(community.checkpoint(private), public)
                self.assertEqual(restored.get_file(done['materials']), community.get_file(done['materials']))


if __name__ == '__main__': unittest.main()

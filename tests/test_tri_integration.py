import secrets
import tempfile
import unittest
from pathlib import Path

from ziokt.community import Community, RIGHTS, create_policy
from ziokt.protocol import ProtocolError
from ziokt.safefs import Vault
from ziokt.security import sign
from ziokt.tri import open_project, project_bundle, publish_project, read_project


class TriFederation(unittest.TestCase):
    def test_simulator_project_is_encrypted_and_federated_as_safe_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signing_key = secrets.token_bytes(32)
            public = sign({}, signing_key, "test")["public_key"]
            policy = create_policy(signing_key, "tri-lab", {public: sorted(RIGHTS)})
            vault = Vault(root / "vault", "tri", secrets.token_bytes(32))
            source = "PUSH 1\nHALT"
            state = {"ternaryExpansionMemory": [0, 1, -1], "registers": {"pc": 0}}
            with Community(root / "community", policy, public, secrets.token_bytes(32)) as community:
                result = publish_project(vault, community, signing_key, source, state)
                self.assertTrue(result["sealed"])
                self.assertFalse(result["plaintext_disclosed"])
                event = community.view("files")["events"][0]
                sealed = community.get_file(event["body"])
                self.assertNotIn(source.encode(), sealed)
                self.assertEqual(open_project(vault, result["digest"])["state"], state)
            self.assertEqual(read_project(project_bundle(source)), {
                "schema": "ziokt.tri-project.v1", "engine": "ternary-computer-simulator",
                "program": source, "state": {}})

    def test_rejects_unbounded_or_malformed_project_objects(self):
        with self.assertRaises(ProtocolError):
            project_bundle("x" * (64 * 1024 + 1))
        with self.assertRaises(ProtocolError):
            read_project(b'{"schema":"ziokt.tri-project.v1","engine":"ternary-computer-simulator","program":"x","state":[],"extra":true}')


if __name__ == "__main__":
    unittest.main()

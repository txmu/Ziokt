"""Production monolith Wiki, consensus and snapshot operations via Ziokt."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing

from test_native_integration import C, S
from ziokt.client import NativeClient
from ziokt.config import fingerprint
from ziokt.protocol import ProtocolError


class NativeApplicationTests(unittest.TestCase):
    def test_wiki_native_acl_consensus_inventory_and_snapshot(self):
        sys.path.insert(0, str(C))
        from test_core import Fixture
        fixture = Fixture(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        for directory in fixture.root.rglob("*"):
            if directory.is_dir(): directory.chmod(0o700)
        (fixture.etc/"identity.key").chmod(0o600)
        group = "b"*64
        with closing(sqlite3.connect(fixture.forum)) as db, db:
            db.execute("INSERT INTO acl_state VALUES (?,?,?)", (group, fixture.identity, '["member"]'))
        config = fixture.etc/"corix.conf"
        config.write_text("[ziokt]\nenabled=TRUE\nfederation_id=test\nprovider_id=corium-local\nallow_mutations=TRUE\nallowed_operations=wiki.create,chain.mine,snapshot.create\nallowed_resources=*\n")
        config.chmod(0o600)
        client = NativeClient("test", {"native_project": "corium", "provider_id": "corium-local",
            "root": str(C), "native_config": str(config), "state_root": str(fixture.root), "network_id": "default",
            "entrypoint_digest": fingerprint(C/"corix_v108.sh")})
        def execute(op_id, action, resource, arguments):
            plan = client.call("operation.prepare", {"operation_id": op_id, "action": action,
                "resource": resource, "arguments": arguments, "expected_revision": None})
            return client.call("operation.commit", {"operation_id": op_id, "plan_digest": plan["plan_digest"]})
        denied = {"operation_id": "unauthorized-page", "action": "wiki.create", "resource": "a"*64+"/denied",
                  "arguments": {"content": "secret", "message": "test"}, "expected_revision": None}
        with self.assertRaises(ProtocolError) as error: client.call("operation.prepare", denied)
        self.assertEqual(error.exception.code, "POLICY_DENIED")
        wiki = execute("wiki-create", "wiki.create", group+"/ziokt", {"content": "# Ziokt\n原生 Wiki 内容", "message": "native integration"})
        self.assertEqual(wiki["result"]["phase"], "pending-native-consensus")
        mined = execute("wiki-mine", "chain.mine", "chain:default", {})
        self.assertTrue(mined["result"]["block_created"])
        inventory = client.objects("application")
        self.assertEqual(inventory[0]["native_id"], group+"/ziokt")
        self.assertEqual(inventory[0]["properties"]["version_hash"], wiki["result"]["transaction_hash"])
        # Share the real C Wiki reference through the original S chat protocol.
        sys.path.insert(0, str(S/"Application-Layer"))
        from shadow_protocols import ShadowIdentity, ShadowChat
        import secrets
        alice, bob = ShadowIdentity.generate("alice"), ShadowIdentity.generate("bob")
        key = secrets.token_bytes(32)
        sender, receiver = ShadowChat(key, alice), ShadowChat(key, bob)
        shared = sender.encrypt("bob", inventory[0]["object_id"])
        self.assertEqual(receiver.decrypt(shared, alice.public_hex()), inventory[0]["object_id"])
        with self.assertRaises(ValueError): receiver.decrypt(shared, alice.public_hex())
        import shutil
        if shutil.which("rsync"):
            backup = execute("wiki-backup", "snapshot.create", "ziokt-wiki", {})
            self.assertEqual(backup["state"], "committed")
            self.assertEqual(client.objects("recovery")[0]["native_id"], "ziokt-wiki")
        else:
            self.fail("native snapshot test requires rsync (provided in integration CI)")


if __name__ == "__main__": unittest.main()

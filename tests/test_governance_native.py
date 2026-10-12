"""Existing native C registration facts guard an opt-in reviewed workflow."""
import json
from pathlib import Path
import shlex
import sys
import unittest
from contextlib import closing
import sqlite3
from test_native_integration import C
from ziokt.client import NativeClient
from ziokt.config import fingerprint
from ziokt.governance import guard
from ziokt.protocol import ProtocolError


class GovernanceTests(unittest.TestCase):
    def test_native_signed_inclusion_and_reorg_guard(self):
        sys.path.insert(0, str(C))
        from test_core import Fixture
        fixture = Fixture(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        config = fixture.etc/"corix.conf"
        config.write_text("[ziokt]\nenabled=TRUE\nfederation_id=test\nprovider_id=corium-local\nallow_mutations=FALSE\n"); config.chmod(0o600)
        digest = "sha256:"+"a"*64
        payload = json.dumps({"nickname": "Ziokt approval fixture", "ziokt_workflow_digest": digest}, separators=(',', ':'))
        fixture.run_core('blockchain_create_transaction registration '+shlex.quote(payload)+'; blockchain_mine_block')
        with closing(sqlite3.connect(fixture.chain)) as db:
            tx_hash = db.execute("SELECT hash FROM transactions WHERE type='registration'").fetchone()[0]
        client = NativeClient("test", {"native_project": "corium", "provider_id": "corium-local", "root": str(C),
            "native_config": str(config), "state_root": str(fixture.root), "network_id": "default", "entrypoint_digest": fingerprint(C/"corix_v108.sh")})
        policy = {"schema": "ziokt.governance-policy.v1", "network_id": "default", "allowed_senders": [fixture.identity],
                  "transaction_types": ["registration"], "minimum_confirmations": 1, "minimum_height": 1}
        admitted, recheck = guard(client, policy, tx_hash, digest)
        self.assertFalse(admitted["native_permissions_granted"])
        recheck()
        with self.assertRaises(ProtocolError): guard(client, policy, tx_hash, "sha256:"+"b"*64)
        with closing(sqlite3.connect(fixture.chain)) as db, db:
            db.execute("UPDATE transactions SET block_height=NULL WHERE hash=?", (tx_hash,))
        with self.assertRaises(ProtocolError): recheck()

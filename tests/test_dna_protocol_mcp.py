"""Tests for DNA duplex, RNA frames, OpenCI commitments, governance archive, and companion tunnels in MCP."""
import json
import sqlite3
from pathlib import Path
import tempfile
import time
import unittest
import hashlib
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from ziokt.dna_protocol import public_key_pem

from ziokt.mcp import Service
from ziokt.dna_protocol import (
    CANONICAL_CHAIN_ID,
    CANONICAL_POLICY_ID,
    ARCHIVE_CHAIN_ID,
    ARCHIVE_POLICY_ID,
    dna_protect_payload,
    dna_verify_payload,
    zdns_rna_announce,
    zdns_rna_verify,
    openci_commit_evidence,
    openci_verify_evidence,
    query_governance_archive,
    shadow6_companion_tunnel_status,
)


class TestDnaProtocolMcp(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="ziokt-test-dna-mcp-")
        self.root = Path(self.tempdir.name)
        key=ec.generate_private_key(ec.SECP256K1())
        key_path=self.root/'owner.pem'
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        key_path.chmod(0o600)
        archive=self.root/'archive.db'
        with sqlite3.connect(archive) as db:
            db.execute('CREATE TABLE blocks(height INTEGER,hash TEXT)');db.execute('INSERT INTO blocks VALUES(784,?)',('a'*64,))
            db.execute('CREATE TABLE transactions(block_height INTEGER,hash TEXT,type TEXT,data TEXT,timestamp INTEGER)')
            db.execute('INSERT INTO transactions VALUES(784,?,?,?,1)',('b'*64,'propose_new_compute_engine','{}'))
        self.config = {
            "governance_archive":str(archive),
            "writes_enabled": True,
            "protocol_state": {"signing_key":str(key_path),"owners":{"archive.library.ziokt":hashlib.sha256(public_key_pem(key).encode()).hexdigest()}},
            "state": str(self.root / "state"),
            "bridges": {},
            "clients": {
                "test-operator": {
                    "redirect_uris": ["http://localhost/cb"],
                    "scopes": [
                        "ziokt:read",
                        "ziokt:names:read", "ziokt:names:write", "ziokt:evidence:write",
                        "corium:read",
                        "shadow6:read",
                    ]
                }
            }
        }
        self.service = Service(self.config)
        self.principal = {
            "client": "test-operator",
            "scopes": {"ziokt:read", "ziokt:names:read", "ziokt:names:write", "ziokt:evidence:write", "corium:read", "shadow6:read"},
            "expires": 2**63,
            "token_id": "test-token"
        }

    def tearDown(self):
        self.service.close()
        self.tempdir.cleanup()

    def test_dna_duplex_tool_execution(self):
        # 1. Protect payload via MCP tool call
        text = "Ziokt Library preserved document: charter v1."
        call1 = self.service.call(
            self.principal,
            "ziokt_dna_duplex_protect",
            {"payload_text": text, "domain": "library", "metadata": {"author": "admin"}}
        )
        self.assertFalse(call1.get("isError"))
        gene = call1["structuredContent"]
        self.assertEqual(gene["schema"], "corium.dna.duplex.v1")
        self.assertEqual(gene["domain"], "library")
        self.assertIn("root", gene)
        self.assertIn("sense", gene)
        self.assertIn("antisense", gene)

        # 2. Verify payload via MCP tool call
        call2 = self.service.call(
            self.principal,
            "ziokt_dna_duplex_verify",
            {"gene": gene, "authenticated_root": gene["root"]}
        )
        self.assertFalse(call2.get("isError"))
        res = call2["structuredContent"]
        self.assertTrue(res["valid"])
        self.assertEqual(res["payload_text"], text)

        # 3. Test single-strand damage repair
        corrupted = dict(gene)
        corrupted["antisense"] = "A" * len(gene["antisense"])
        call3 = self.service.call(
            self.principal,
            "ziokt_dna_duplex_verify",
            {"gene": corrupted, "authenticated_root": gene["root"], "repair": True}
        )
        self.assertFalse(call3.get("isError"))
        res3 = call3["structuredContent"]
        self.assertTrue(res3["valid"])
        self.assertTrue(res3["repaired"])
        self.assertEqual(res3["payload_text"], text)

    def test_zdns_rna_announce_and_verify_tools(self):
        # 1. Announce via MCP tool
        domain = "archive.library.ziokt"
        target = "https://cor-web.ziokt.com/library"
        call1 = self.service.call(
            self.principal,
            "ziokt_zdns_rna_announce",
            {"domain": domain, "target": target, "idempotency_key":"announce_test_0001"}
        )
        self.assertFalse(call1.get("isError"))
        announced = call1["structuredContent"]
        self.assertIn("frame", announced)
        self.assertIn("pem", announced)
        self.assertEqual(announced["chain_id"], CANONICAL_CHAIN_ID)

        # 2. Verify via MCP tool
        call2 = self.service.call(
            self.principal,
            "ziokt_zdns_rna_verify",
            {
                "idempotency_key":"verify_test_000001",
                "frame": announced["frame"],
                "pem": announced["pem"],
                "chain_id": announced["chain_id"],
                "policy_id": announced["policy_id"],
                "sender": announced["sender"],
            }
        )
        self.assertFalse(call2.get("isError"))
        verified = call2["structuredContent"]
        self.assertTrue(verified["valid"])
        self.assertEqual(verified["record"]["domain"], domain)
        self.assertEqual(verified["record"]["target"], target)

    def test_openci_evidence_commit_and_verify_tools(self):
        call1 = self.service.call(
            self.principal,
            "ziokt_openci_evidence_commit",
            {
                "idempotency_key":"evidence_test_0001",
                "pipeline": "build-ziokt-2.0",
                "task": "formal-verification",
                "worker": "worker-hk-01",
                "artifact_digest": "e" * 64,
                "result": {"passed": True, "tests_run": 42}
            }
        )
        self.assertFalse(call1.get("isError"))
        committed = call1["structuredContent"]
        self.assertIn("commitment_hash", committed)
        self.assertEqual(committed["commitment"]["schema"], "openci.evidence-commitment.v1")

        call2 = self.service.call(
            self.principal,
            "ziokt_openci_evidence_verify",
            {
                "commitment": committed["commitment"],
                "expected_hash": committed["commitment_hash"]
            }
        )
        self.assertFalse(call2.get("isError"))
        self.assertTrue(call2["structuredContent"]["valid"])

    def test_governance_archive_query_tool(self):
        call = self.service.call(
            self.principal,
            "corium_governance_archive_query",
            {"limit": 5}
        )
        self.assertFalse(call.get("isError"))
        res = call["structuredContent"]
        self.assertTrue(res["found"])
        self.assertEqual(res["archive_scope"], "H0-H784")
        self.assertEqual(res["latest_archive_height"], 784)
        self.assertGreaterEqual(res["count"], 1)

    def test_companion_tunnel_status_tool(self):
        call = self.service.call(
            self.principal,
            "shadow6_companion_tunnel_status",
            {}
        )
        self.assertFalse(call.get("isError"))
        res = call["structuredContent"]
        self.assertEqual(res["schema"], "ziokt.companion-tunnel-status.v1")
        self.assertEqual(res["status"], "not_configured")
        self.assertNotIn("runtime_connectivity",res)
        self.assertFalse(res["companion_mesh"]["multi_hop_capable"])
        self.assertFalse(res["companion_mesh"]["disaster_recovery_forwarding"])


if __name__ == "__main__":
    unittest.main()

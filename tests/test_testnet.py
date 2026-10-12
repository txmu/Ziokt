"""Persistent developer-chain CLI data, native mining and account RPC."""
import json
from pathlib import Path
import tempfile
import unittest

from test_native_integration import C
from ziokt.client import NativeClient
from ziokt.config import fingerprint
from ziokt.testnet import initialize, invoke


class TestnetTests(unittest.TestCase):
    def test_isolated_native_chain_no_overwrite_transfer_and_federated_account(self):
        with tempfile.TemporaryDirectory(prefix="ziokt-persistent-testnet-") as directory:
            root = Path(directory)/"chain"
            marker = initialize(C, root)
            with self.assertRaises(Exception):
                initialize(C, root)
            status = json.loads(invoke(root, ["zkt", "status"]))
            self.assertEqual(status["total_units"], 1_000_000)
            self.assertEqual(status["height"], 0)
            invoke(root, ["zkt", "send", marker["wallets"]["bob"], "1000", "1", "--confirm"])
            invoke(root, ["zkt", "mine", "--confirm-test-only"])
            provider = {"native_project": "corium", "provider_id": "corium-testnet", "root": str(C),
                        "state_root": str(root), "native_config": str(root/"etc/corix/networks"/marker["network_id"]/"corix.conf"),
                        "entrypoint_digest": fingerprint(C/"corix_v108.sh"), "network_id": marker["network_id"]}
            account = NativeClient("testnet", provider).call("zkt.account", {"address": marker["wallets"]["alice"]})
            self.assertEqual(account["account"]["balance"], 898_993)
            self.assertEqual(account["account"]["nonce"], 1)
            self.assertEqual(account["issuance"], "fixed-genesis")
            self.assertEqual(account["finality"], "unverified")

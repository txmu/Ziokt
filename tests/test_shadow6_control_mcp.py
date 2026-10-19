import json
import secrets
import tempfile
import time
import unittest
from pathlib import Path

from ziokt.mcp import Service, McpError
from ziokt.shadow6_control_mcp import Shadow6ControlAdapter, attach_shadow6_control


class Shadow6ControlMcpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        admin = self.root / "admin"
        admin.write_text("a" * 64)
        admin.chmod(0o600)
        self.config = {
            "schema": "ziokt.mcp.v1",
            "issuer": "https://gateway.test",
            "origins": ["https://gateway.test"],
            "state": str(self.root / "state"),
            "admin_token": str(admin),
            "bridges": {},
            "clients": {
                "s6-reader": {
                    "redirect_uris": ["http://127.0.0.1:8765/callback"],
                    "scopes": ["shadow6:read"],
                },
                "s6-writer": {
                    "redirect_uris": ["http://127.0.0.1:8765/callback"],
                    "scopes": ["shadow6:read", "shadow6:write"],
                },
                "unauthorized": {
                    "redirect_uris": ["http://127.0.0.1:8765/callback"],
                    "scopes": ["ziokt:read"],
                },
            },
            "writes_enabled": True,
        }

    def test_direct_adapter_stdio_connection_and_discovery(self):
        """Adapter connects to local shadow6-control mcp, lists tools and calls tools."""
        adapter = Shadow6ControlAdapter()
        self.addCleanup(adapter.close)
        tools = adapter.list_tools()
        self.assertGreater(len(tools), 10)
        tool_names = {t["name"] for t in tools}
        self.assertIn("shadow6_privacy_report", tool_names)
        self.assertIn("shadow6_system_status", tool_names)

        # Call a read-only tool
        result = adapter.call_tool("shadow6_privacy_report", {})
        self.assertFalse(result.get("isError", False))
        structured = result.get("structuredContent", {})
        self.assertIn("checks", structured)
        self.assertIn("passed", structured)

    def test_allowed_tools_filtering_and_adapter_permission_guard(self):
        """Adapter restricts exposed tools and denies unpermitted calls."""
        allowed = ["shadow6_privacy_report", "shadow6_system_status"]
        adapter = Shadow6ControlAdapter(allowed_tools=allowed)
        self.addCleanup(adapter.close)
        tools = adapter.get_allowed_tools()
        self.assertEqual(len(tools), 2)
        names = {t["name"] for t in tools}
        self.assertEqual(names, set(allowed))

        # Permitted tool succeeds
        res = adapter.call_tool("shadow6_privacy_report", {})
        self.assertFalse(res.get("isError", False))

        # Unpermitted tool raises PermissionError
        with self.assertRaises(PermissionError):
            adapter.call_tool("shadow6_system_schema", {})

    def test_ziokt_service_mapping_and_forwarding(self):
        """Service maps permitted shadow6-control tools and forwards tools/call."""
        adapter = Shadow6ControlAdapter(
            allowed_tools=["shadow6_privacy_report", "shadow6_config_render"]
        )
        self.addCleanup(adapter.close)
        service = Service(self.config)
        self.addCleanup(service.close)
        attach_shadow6_control(service, adapter=adapter)

        self.assertIn("shadow6_privacy_report", service.tools)
        self.assertIn("shadow6_config_render", service.tools)

        # Check annotations and scopes
        read_tool = service.tools["shadow6_privacy_report"]
        self.assertEqual(read_tool["scope"], "shadow6:read")
        self.assertFalse(read_tool["annotations"]["destructiveHint"])

        write_tool = service.tools["shadow6_config_render"]
        self.assertEqual(write_tool["scope"], "shadow6:write")
        self.assertTrue(write_tool["annotations"]["destructiveHint"])
        self.assertIn("idempotency_key", write_tool["inputSchema"]["properties"])

        # Scope check: reader can call read tool
        reader = service.auth(
            "Bearer " + service.issue("s6-reader", {"shadow6:read"})["access_token"]
        )
        res = service.call(reader, "shadow6_privacy_report", {})
        self.assertFalse(res["isError"])
        self.assertIn("checks", res["structuredContent"])

        # Scope check: unauthorized client is rejected
        unauth = service.auth(
            "Bearer " + service.issue("unauthorized", {"ziokt:read"})["access_token"]
        )
        with self.assertRaises(McpError) as cm:
            service.call(unauth, "shadow6_privacy_report", {})
        self.assertEqual(cm.exception.code, -32001)

        # Scope check: reader cannot call write tool
        with self.assertRaises(McpError) as cm:
            service.call(reader, "shadow6_config_render", {}, key="k" * 16)
        self.assertEqual(cm.exception.code, -32001)

    def test_both_sides_permission_checks(self):
        """Ziokt guards writes and Shadow6 guards mutations."""
        # Case A: Shadow6 allow_mutations=False (default).
        # Ziokt writer has valid scope and idempotency key, but Shadow6 rejects mutation.
        adapter_no_mut = Shadow6ControlAdapter(
            allow_mutations=False, allowed_tools=["shadow6_config_render"]
        )
        self.addCleanup(adapter_no_mut.close)
        service = Service(self.config)
        self.addCleanup(service.close)
        attach_shadow6_control(service, adapter=adapter_no_mut)

        writer = service.auth(
            "Bearer "
            + service.issue("s6-writer", {"shadow6:read", "shadow6:write"})["access_token"]
        )

        # Write without idempotency key fails on Ziokt side
        with self.assertRaises(ValueError):
            service.call(writer, "shadow6_config_render", {}, key=None)

        # Write with idempotency key passes Ziokt guard, but Shadow6 denies mutation
        res = service.call(writer, "shadow6_config_render", {}, key="idemp_key_12345678")
        self.assertTrue(res["isError"])
        self.assertIn("operation rejected", res["content"][0]["text"])

        # Case B: Shadow6 allow_mutations=True. Both Ziokt and Shadow6 allow the call.
        adapter_with_mut = Shadow6ControlAdapter(
            allow_mutations=True, allowed_tools=["shadow6_config_render"]
        )
        self.addCleanup(adapter_with_mut.close)
        service2 = Service(self.config)
        self.addCleanup(service2.close)
        attach_shadow6_control(service2, adapter=adapter_with_mut)

        writer2 = service2.auth(
            "Bearer "
            + service2.issue("s6-writer", {"shadow6:read", "shadow6:write"})["access_token"]
        )
        res2 = service2.call(writer2, "shadow6_config_render", {}, key="idemp_key_87654321")
        self.assertFalse(res2["isError"])
        self.assertIn("content", res2["structuredContent"])

        # Case C: writes_enabled=False on Ziokt side denies call before Shadow6
        self.config["writes_enabled"] = False
        with self.assertRaises(McpError):
            service2.call(writer2, "shadow6_config_render", {}, key="idemp_key_99999999")

    def test_config_driven_shadow6_control_attachment(self):
        """Service automatically attaches shadow6_control adapter when present in config."""
        cfg = {
            **self.config,
            "shadow6_control": {
                "allowed_tools": ["shadow6_privacy_report", "shadow6_system_status"]
            },
        }
        service = Service(cfg)
        self.addCleanup(service.close)
        self.assertIn("shadow6_privacy_report", service.tools)
        self.assertIn("shadow6_system_status", service.tools)
        self.assertNotIn("shadow6_config_render", service.tools)


if __name__ == "__main__":
    unittest.main()

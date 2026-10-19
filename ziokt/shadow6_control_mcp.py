"""Shadow6-control MCP client adapter.

Connects to local shadow6-control mcp over stdio, reads tools/list, maps
permitted tools to Ziokt's MCP directory, and forwards tools/call while
preserving permission checks on both sides.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from typing import Any, Dict, List, Optional, Set

from .mcp import McpError


def find_shadow6_control() -> str:
    which = shutil.which("shadow6-control")
    if which:
        return which
    candidates = [
        Path.home() / ".local/bin/shadow6-control",
        Path("/usr/local/bin/shadow6-control"),
        Path.home() / "Shadow6/Control-Center/shadow6_control.py",
        Path(__file__).resolve().parents[2] / "Shadow6/Control-Center/shadow6_control.py",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return "shadow6-control"


class Shadow6ControlAdapter:
    """Client adapter connecting Ziokt to local shadow6-control MCP."""

    def __init__(
        self,
        command: Optional[Any] = None,
        allow_mutations: bool = False,
        allowed_tools: Optional[Any] = None,
        timeout: float = 10.0,
        transport: Optional[Any] = None,
    ):
        self.command = command
        self.allow_mutations = bool(allow_mutations)
        self.allowed_tools: Optional[Set[str]] = (
            set(allowed_tools) if allowed_tools is not None else None
        )
        self.timeout = float(timeout)
        self.transport = transport
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()
        self._request_id = 0

    def _resolve_command(self) -> List[str]:
        if self.command is None:
            raw = find_shadow6_control()
            cmd = [sys.executable, raw] if raw.endswith(".py") else [raw]
        elif isinstance(self.command, (list, tuple)):
            cmd = list(self.command)
        elif isinstance(self.command, str):
            cmd = [self.command]
        else:
            raise ValueError("command must be a string or list of arguments")

        if len(cmd) == 1 and cmd[0].endswith(".py"):
            cmd = [sys.executable, *cmd]

        if "mcp" not in cmd:
            cmd.append("mcp")

        if self.allow_mutations and "--allow-mutations" not in cmd:
            cmd.append("--allow-mutations")
        elif not self.allow_mutations and "--allow-mutations" in cmd:
            cmd.remove("--allow-mutations")
        return cmd

    def _next_id(self) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _ensure_connected(self) -> None:
        with self._lock:
            if self.transport is not None:
                return
            if self._process is not None and self._process.poll() is None:
                return
            self._start_process()
            self._handshake()

    def _start_process(self) -> None:
        cmd = self._resolve_command()
        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def _send_notification(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        if self.transport is not None:
            if hasattr(self.transport, "notify"):
                self.transport.notify(method, params or {})
            return
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        raw = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._lock:
            if self._process is None or self._process.stdin is None:
                raise RuntimeError("shadow6-control process not running")
            self._process.stdin.write(raw)
            self._process.stdin.flush()

    def _send_raw(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        req_id = self._next_id()
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        if self.transport is not None:
            return self.transport.request(payload)
        raw = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._lock:
            if self._process is None or self._process.stdin is None or self._process.stdout is None:
                raise RuntimeError("shadow6-control process not running")
            self._process.stdin.write(raw)
            self._process.stdin.flush()
            line = self._process.stdout.readline()
            if not line:
                code = self._process.poll()
                err = ""
                if self._process.stderr:
                    err = self._process.stderr.read()
                raise RuntimeError(
                    f"shadow6-control process terminated unexpectedly (exit code {code}): {err}"
                )
            return json.loads(line)

    def _handshake(self) -> None:
        init_res = self._send_raw(
            "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}}
        )
        if "error" in init_res:
            raise RuntimeError(f"Shadow6-control MCP initialization failed: {init_res['error']}")
        self._send_notification("notifications/initialized", {})

    def list_tools(self) -> List[Dict[str, Any]]:
        self._ensure_connected()
        res = self._send_raw("tools/list", {})
        if "error" in res:
            raise RuntimeError(f"tools/list error: {res['error']}")
        return res.get("result", {}).get("tools", [])

    def get_allowed_tools(self) -> List[Dict[str, Any]]:
        tools = self.list_tools()
        if self.allowed_tools is not None:
            return [t for t in tools if t.get("name") in self.allowed_tools]
        return tools

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self.allowed_tools is not None and name not in self.allowed_tools:
            raise PermissionError(f"Tool {name} is not permitted by client adapter allowlist")
        self._ensure_connected()
        res = self._send_raw("tools/call", {"name": name, "arguments": arguments or {}})
        if "error" in res:
            err = res["error"]
            raise McpError(err.get("code", -32603), err.get("message", "Tool call error"))
        return res.get("result", {})

    def close(self) -> None:
        with self._lock:
            if self._process is not None:
                for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
                    try:
                        if stream:
                            stream.close()
                    except Exception:
                        pass
                try:
                    self._process.terminate()
                    self._process.wait(timeout=2.0)
                except Exception:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
                self._process = None

    def __enter__(self):
        self._ensure_connected()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()

    @classmethod
    def from_config(cls, config: Any) -> "Shadow6ControlAdapter":
        if config is True:
            return cls()
        if isinstance(config, (str, list)):
            return cls(command=config)
        if isinstance(config, dict):
            return cls(
                command=config.get("command"),
                allow_mutations=config.get("allow_mutations", False),
                allowed_tools=config.get("allowed_tools") or config.get("allow_tools"),
                timeout=config.get("timeout", 10.0),
            )
        return cls()


Shadow6ControlMcpClient = Shadow6ControlAdapter


def attach_shadow6_control(
    service: Any,
    config: Optional[Any] = None,
    adapter: Optional[Shadow6ControlAdapter] = None,
) -> Shadow6ControlAdapter:
    """Attach shadow6-control MCP client adapter and map allowed tools into service."""
    if adapter is None:
        adapter = Shadow6ControlAdapter.from_config(config if config is not None else True)
    service.shadow6_control = adapter
    tools = adapter.get_allowed_tools()
    for tool in tools:
        raw_name = tool["name"]
        target_name = (
            raw_name
            if raw_name not in service.tools
            else f"shadow6_control_{raw_name.removeprefix('shadow6_')}"
        )
        if target_name in service.tools:
            continue
        annotations = tool.get("annotations", {})
        write = bool(
            annotations.get("destructiveHint", False)
            or not annotations.get("readOnlyHint", True)
        )
        scope = "shadow6:write" if write else "shadow6:read"
        description = tool.get("description", f"Shadow6 control tool: {raw_name}")
        schema = tool.get("inputSchema", {"type": "object", "properties": {}, "required": []})
        service.add(
            target_name,
            description,
            schema,
            write,
            scope,
            ("shadow6-control", raw_name),
        )
    return adapter

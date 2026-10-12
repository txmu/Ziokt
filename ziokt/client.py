"""Bounded one-shot local RPC, with pinned native source and process cleanup."""
import hashlib
import os
from pathlib import Path
import secrets
import threading
import signal
import subprocess
import sys
import tempfile
import time

from .config import entrypoint, source_bytes
from .protocol import MAX_OBJECTS, MAX_RESPONSE, PROTOCOL, ProtocolError, encoded, strict_json

PYTHON_BOOTSTRAP = """import os,sys
snapshot=sys.argv[1];path=sys.argv[2];sys.argv=sys.argv[2:]
sys.dont_write_bytecode=True
sys.path.insert(0,os.path.dirname(path))
with open(snapshot,'rb') as source: code=source.read()
exec(compile(code,path,'exec'),{'__name__':'__main__','__file__':path,'__builtins__':__builtins__})
"""


def exchange(provider, request, timeout=30):
    path = entrypoint(provider)
    code = source_bytes(path)
    if "sha256:" + hashlib.sha256(code).hexdigest() != provider["entrypoint_digest"]:
        raise ProtocolError("STALE_PROVIDER", "native entrypoint changed; review and refresh its digest")
    # Private source snapshot also works where anonymous FD execution is absent.
    with tempfile.TemporaryDirectory(prefix="ziokt-provider-") as directory:
        source = Path(directory) / ("provider.py" if provider["native_project"] == "shadow6" else "provider.sh")
        source.write_bytes(code)
        source.chmod(0o600)
        args = ["ziokt", "--config", provider["native_config"]]
        env = {key: value for key, value in os.environ.items()
               if key in {"PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT"}}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if provider["native_project"] == "shadow6":
            command = [sys.executable, "-c", PYTHON_BOOTSTRAP, str(source), str(path),
                       *args, "rpc", "--stdio"]
        else:
            env["CORIUM_ROOT"] = provider["state_root"]
            args += ["--network", provider["network_id"], "rpc", "--stdio"]
            command = ["bash", str(source), *args]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=env,
                                   start_new_session=os.name == "posix", **({"umask": 0o077} if os.name == "posix" else {}))
        try:
            body = encoded(request) + b"\n"
            deadline = time.monotonic() + timeout
            output, errors, violations = bytearray(), bytearray(), []
            activity = threading.Event()

            def read(stream, target, limit):
                try:
                    while True:
                        chunk = os.read(stream.fileno(), 65536)
                        if not chunk:
                            break
                        if len(target) + len(chunk) > limit:
                            violations.append("output")
                            break
                        target.extend(chunk)
                except OSError:
                    violations.append("io")
                finally:
                    activity.set()

            def write():
                try:
                    process.stdin.write(body)
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    process.stdin.close()
                    activity.set()

            threads = [threading.Thread(target=read, args=(process.stdout, output, MAX_RESPONSE + 1), daemon=True),
                       threading.Thread(target=read, args=(process.stderr, errors, 16384), daemon=True),
                       threading.Thread(target=write, daemon=True)]
            for thread in threads:
                thread.start()
            while any(thread.is_alive() for thread in threads):
                if violations:
                    raise ProtocolError("PROVIDER_OUTPUT_LIMIT", "native provider exceeded pipe budget")
                if time.monotonic() >= deadline:
                    raise ProtocolError("PROVIDER_TIMEOUT", "native provider timed out")
                activity.wait(min(.05, max(.001, deadline - time.monotonic())))
                activity.clear()
            returncode = process.wait(timeout=max(.001, deadline - time.monotonic()))
            if not output.endswith(b"\n") or output.count(b"\n") != 1:
                raise ProtocolError("INVALID_RESPONSE", "one bounded response required")
            value = strict_json(bytes(output[:-1]), MAX_RESPONSE)
            if (not isinstance(value, dict) or value.get("protocol") != PROTOCOL or
                    type(value.get("ok")) is not bool or
                    (value.get("request_id") != request["request_id"] and
                     not (value.get("request_id") is None and value["ok"] is False))):
                raise ProtocolError("INVALID_RESPONSE", "response correlation failed")
            if value["ok"]:
                if set(value) != {"protocol", "request_id", "ok", "result"} or returncode != 0:
                    raise ProtocolError("INVALID_RESPONSE", "inconsistent provider success")
                return value["result"]
            error = value.get("error")
            if (set(value) != {"protocol", "request_id", "ok", "error"} or
                    not isinstance(error, dict) or set(error) != {"code", "message"} or
                    not all(isinstance(error[k], str) for k in error)):
                raise ProtocolError("INVALID_RESPONSE", "invalid provider error")
            raise ProtocolError(error["code"], error["message"])
        except subprocess.TimeoutExpired:
            raise ProtocolError("PROVIDER_TIMEOUT", "native provider timed out")
        finally:
            # Only this child's newly created process group is touched.
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.kill()
            process.wait()
            for thread in locals().get("threads", []):
                thread.join(timeout=1)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream and not stream.closed:
                    stream.close()


class NativeClient:
    def __init__(self, federation, provider):
        self.federation = federation
        self.provider = provider

    def call(self, method, params=None):
        request = {"protocol": PROTOCOL, "request_id": secrets.token_hex(16),
                   "federation_id": self.federation, "provider_id": self.provider["provider_id"],
                   "method": method, "params": params or {},
                   "nonce": secrets.token_hex(16), "deadline_ms": time.time_ns() // 1_000_000 + 25_000}
        return exchange(self.provider, request)

    def objects(self, kind="all"):
        records, cursor, snapshot = [], None, None
        for _ in range(MAX_OBJECTS // 100 + 2):
            params = {"kind": kind, "limit": 100}
            if cursor:
                params["cursor"] = cursor
            result = self.call("objects.list", params)
            if (not isinstance(result, dict) or set(result) != {
                    "objects", "next_cursor", "snapshot_digest", "total"} or
                    not isinstance(result["objects"], list) or len(result["objects"]) > 100 or
                    type(result["total"]) is not int or not 0 <= result["total"] <= MAX_OBJECTS):
                raise ProtocolError("INVALID_RESPONSE", "invalid inventory page")
            if snapshot is not None and result["snapshot_digest"] != snapshot:
                raise ProtocolError("STALE_CURSOR", "provider snapshot changed")
            snapshot = result["snapshot_digest"]
            for record in result["objects"]:
                if (not isinstance(record, dict) or record.get("owner_provider") != self.provider["provider_id"]
                        or not isinstance(record.get("object_id"), str)
                        or not record["object_id"].startswith("ziokt://" + self.federation + "/" + self.provider["provider_id"] + "/")):
                    raise ProtocolError("INVALID_RESPONSE", "inventory scope mismatch")
            records.extend(result["objects"])
            if len(records) > MAX_OBJECTS:
                raise ProtocolError("INVENTORY_LIMIT", "provider inventory exceeds budget")
            previous, cursor = cursor, result["next_cursor"]
            if cursor is None:
                if len(records) != result["total"] or len({r["object_id"] for r in records}) != len(records):
                    raise ProtocolError("INVALID_RESPONSE", "incomplete or duplicate inventory")
                return records
            if not isinstance(cursor, str) or cursor == previous or not result["objects"]:
                raise ProtocolError("INVALID_RESPONSE", "inventory cursor did not progress")
        raise ProtocolError("INVENTORY_LIMIT", "too many inventory pages")

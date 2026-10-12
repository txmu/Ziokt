"""Explicit mTLS remote federation with signed, replay-protected scoped grants.

This server belongs to Ziokt. It does not open or relax Shadow6's /v1 Web API.
Local native policy remains the final execution gate.
"""
import hashlib
import http.client
import http.server
import json
from pathlib import Path
import socket
import ssl
import threading
import tempfile
import re

from .client import NativeClient
from .protocol import MAX_REQUEST, MAX_RESPONSE, ProtocolError, encoded, strict_json
from .security import ReplayAuthority

WRITE_METHODS = {"operation.prepare", "operation.commit", "operation.abort", "operation.reconcile"}


def resource_for(method, params):
    if method == "operation.prepare":
        return params.get("resource")
    if method.startswith("operation."):
        return "operation:" + str(params.get("operation_id"))
    return "provider:read"


def tls_context(cert, key, ca, server=False):
    from .protocol import secure_read
    # Validate permissions before handing these operator-controlled paths to TLS.
    key_bytes = secure_read(key, 16384)
    cert_bytes = secure_read(cert, 65536, private=None)
    ca_bytes = secure_read(ca, 65536, private=None)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    from .protocol import make_private
    with tempfile.TemporaryDirectory(prefix="ziokt-tls-") as directory:
        material = Path(directory)
        for name, data in (("cert.pem", cert_bytes), ("key.pem", key_bytes)):
            path = material/name; path.write_bytes(data); make_private(path)
        context.load_cert_chain(material/"cert.pem", material/"key.pem")
    context.load_verify_locations(cadata=ca_bytes.decode("ascii"))
    context.verify_mode = ssl.CERT_REQUIRED
    if not server:
        context.check_hostname = True
    return context


def remote_server(federation, context, replay_path, trusted_clients, *, host="127.0.0.1", port=0, allow_mutations=False):
    if not federation["enabled"]:
        raise ProtocolError("ZIOKT_DISABLED", "remote federation must be explicitly enabled")
    if (type(allow_mutations) is not bool or not isinstance(trusted_clients, dict) or not 1 <= len(trusted_clients) <= 64 or
            type(port) is not int or not 0 <= port <= 65535 or not isinstance(host, str)):
        raise ProtocolError("INVALID_CONFIG", "bounded explicit remote authority configuration required")
    for fingerprint, principal in trusted_clients.items():
        if (not re.fullmatch("[a-f0-9]{64}", fingerprint) or not isinstance(principal, dict) or
                set(principal) != {"public_key", "methods", "providers"} or
                not re.fullmatch("[a-f0-9]{64}", str(principal["public_key"])) or
                any(not isinstance(principal[k], list) or not 1 <= len(principal[k]) <= 64 or
                    not all(isinstance(v, str) for v in principal[k]) for k in ("methods", "providers"))):
            raise ProtocolError("INVALID_CONFIG", "exact pinned certificate principal required")
    authority = ReplayAuthority(replay_path)
    providers = {p["provider_id"]: p for p in federation["providers"]}
    slots, authority_lock = threading.BoundedSemaphore(8), threading.RLock()

    class Handler(http.server.BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)
            self.connection.do_handshake()

        def log_message(self, *_):
            pass

        def do_POST(self):
            status, result = 200, None
            try:
                if (self.path != "/zfcp" or self.headers.get("Transfer-Encoding") or self.headers.get("Content-Type") != "application/json" or
                        len(self.headers.get_all("Content-Length", [])) != 1 or len(self.headers.get_all("Content-Type", [])) != 1):
                    raise ProtocolError("INVALID_REQUEST", "bounded JSON POST /zfcp required")
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= MAX_REQUEST:
                    raise ProtocolError("INVALID_REQUEST", "request size budget exceeded")
                envelope = strict_json(self.rfile.read(length))
                if not isinstance(envelope, dict) or set(envelope) != {"request", "grant"}:
                    raise ProtocolError("INVALID_REQUEST", "exact request and scoped grant required")
                request = envelope["request"]
                if (not isinstance(request, dict) or set(request) != {"provider_id", "method", "params"} or
                        not isinstance(request["params"], dict) or not isinstance(request["provider_id"], str) or not isinstance(request["method"], str)):
                    raise ProtocolError("INVALID_REQUEST", "typed provider operation required")
                cert = self.connection.getpeercert(binary_form=True)
                principal = trusted_clients.get(hashlib.sha256(cert).hexdigest())
                if not principal or request["method"] not in principal["methods"] or request["provider_id"] not in principal["providers"]:
                    raise ProtocolError("POLICY_DENIED", "certificate is not allowed for requested operation")
                if request["provider_id"] not in providers:
                    raise ProtocolError("POLICY_DENIED", "provider not configured on this server")
                if request["method"] in WRITE_METHODS and not allow_mutations:
                    raise ProtocolError("MUTATION_DISABLED", "remote mutations are disabled")
                with authority_lock:
                    authority.admit(envelope["grant"], principal["public_key"],
                        audience=request["provider_id"], action=request["method"], resource=resource_for(request["method"], request["params"]),
                        federation=federation["federation_id"], request_digest="sha256:"+hashlib.sha256(encoded(request)).hexdigest())
                if not slots.acquire(False):
                    raise ProtocolError("BACKPRESSURE", "remote native execution budget exhausted")
                try:
                    value = NativeClient(federation["federation_id"], providers[request["provider_id"]]).call(request["method"], request["params"])
                finally:
                    slots.release()
                result = {"ok": True, "result": value}
            except (ProtocolError, ValueError, OSError, TypeError, KeyError) as exc:
                status = 403 if isinstance(exc, ProtocolError) else 400
                result = {"ok": False, "error": {"code": getattr(exc, "code", "INVALID_REQUEST"),
                    "message": str(exc) if isinstance(exc, ProtocolError) else "remote request rejected"}}
            raw = encoded(result)
            if len(raw) > MAX_RESPONSE:
                status, raw = 413, encoded({"ok": False, "error": {"code": "RESPONSE_LIMIT", "message": "response budget exceeded"}})
            self.send_response(status); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw))); self.send_header("Connection", "close")
            self.end_headers(); self.wfile.write(raw)

    class Server(http.server.ThreadingHTTPServer):
        daemon_threads = False
        connection_slots = threading.BoundedSemaphore(32)
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(5)
            return context.wrap_socket(connection, server_side=True, do_handshake_on_connect=False), address
        def process_request(self, request, address):
            if not self.connection_slots.acquire(False):
                self.shutdown_request(request); return
            super().process_request(request, address)
        def process_request_thread(self, request, address):
            try: super().process_request_thread(request, address)
            finally: self.connection_slots.release()
        def handle_error(self, *_):
            pass  # No certificate, path, request or secret-bearing traceback.
        def server_close(self):
            super().server_close(); authority.close()
    server = Server((host, port), Handler)
    return server


def request_remote(host, port, context, request, signed_grant):
    connection = http.client.HTTPSConnection(host, port, context=context, timeout=30)
    try:
        body = encoded({"request": request, "grant": signed_grant})
        if len(body) > MAX_REQUEST:
            raise ProtocolError("INVALID_REQUEST", "remote request exceeds budget")
        connection.request("POST", "/zfcp", body, {"Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE+1)
        result = strict_json(raw, MAX_RESPONSE)
        if not isinstance(result, dict) or type(result.get("ok")) is not bool:
            raise ProtocolError("INVALID_RESPONSE", "typed remote response required")
        if result.get("ok") is not True:
            raise ProtocolError(result["error"]["code"], result["error"]["message"])
        return result["result"]
    finally:
        connection.close()


def load_remote(path, serving=False):
    from .protocol import secure_read
    config = strict_json(secure_read(path))
    base = {"schema", "host", "port", "certificate", "private_key", "ca"}
    extra = {"replay_state", "trusted_clients", "allow_mutations"} if serving else set()
    if not isinstance(config, dict) or set(config) != base|extra or config["schema"] != "ziokt.remote.v1":
        raise ProtocolError("INVALID_CONFIG", "exact private remote endpoint configuration required")
    for field in ("certificate", "private_key", "ca", *(["replay_state"] if serving else [])):
        if not isinstance(config[field], str) or not Path(config[field]).is_absolute() or ".." in Path(config[field]).parts:
            raise ProtocolError("INVALID_CONFIG", "fixed absolute remote material paths required")
    if not isinstance(config["host"], str) or type(config["port"]) is not int or not 0 <= config["port"] <= 65535:
        raise ProtocolError("INVALID_CONFIG", "bounded remote endpoint required")
    return config

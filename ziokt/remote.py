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
import time
import secrets

from .client import NativeClient
from .protocol import MAX_REQUEST, MAX_RESPONSE, ProtocolError, encoded, strict_json
from .security import ReplayAuthority

def padded_json(value, maximum, *, fixed_size=None):
    empty=encoded({**value,'padding':[]})
    size=max(16384,1<<(len(empty)-1).bit_length()) if fixed_size is None else fixed_size
    if type(size) is not int or size<16384 or size&(size-1) or len(empty)>size:raise ProtocolError('RESPONSE_LIMIT','fixed padded frame budget exceeded')
    if size>maximum:raise ProtocolError('RESPONSE_LIMIT','padded frame exceeds bounded transport budget')
    count=max(1,(size-len(empty)+4095)//4096)
    length=size-len(empty)-(3*count-1)
    if length<0:raise ProtocolError('RESPONSE_LIMIT','padding shape exceeds frame budget')
    chunks=[]
    for index in range(count):
        part=min(4096,length);chunks.append(secrets.token_hex((part+1)//2)[:part]);length-=part
    return encoded({**value,'padding':chunks})


def valid_padding(value):
    return (isinstance(value,list) and len(value)<=64 and all(isinstance(v,str) and len(v)<=4096 and re.fullmatch('[a-f0-9]*',v) is not None for v in value))


WRITE_METHODS = {"operation.prepare", "operation.commit", "operation.abort", "operation.reconcile", "community.checkpoint.create", "community.checkpoint.release", "community.event.put", "community.blob.put"}
WRITE_METHODS |= {"relay.start", "relay.part.put", "relay.ack", "tracker.register", "tracker.revoke"}


def resource_for(method, params):
    if method.startswith("tracker."):
        return "tracker:directory"
    if method.startswith("relay."):
        return params.get("packet_id", "relay:queue")
    if method in {"community.checkpoint.get", "community.checkpoint.release", "community.event.put", "community.blob.put"}:
        return params.get("digest")
    if method.startswith("community."):
        return "community:replicate"
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


def remote_server(federation, context, replay_path, trusted_clients, *, host="127.0.0.1", port=0, allow_mutations=False, community=None):
    from .runtime_policy import require_network
    require_network()
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
    if context.verify_mode!=ssl.CERT_REQUIRED or context.minimum_version<ssl.TLSVersion.TLSv1_3:
        raise ProtocolError('INVALID_CONFIG','mutual TLS 1.3 remote context required')
    if community is not None and getattr(community,'policy',getattr(community.community,'policy',{})).get('privacy')=='restricted':
        import ipaddress
        try:private_listener=ipaddress.ip_address(host).is_loopback
        except ValueError:private_listener=False
        if not private_listener:raise ProtocolError('NO_POLICY_COMPLIANT_PATH','restricted community API must be private behind an admitted anonymous carrier')
    authority = ReplayAuthority(replay_path)
    providers = {p["provider_id"]: p for p in federation["providers"]}
    if community is not None and (community.community.community_id != federation["federation_id"] or community.community.community_id in providers):
        authority.close()
        raise ProtocolError("INVALID_CONFIG", "community endpoint needs its own matching federation scope")
    slots, authority_lock = threading.BoundedSemaphore(8), threading.RLock()

    class Handler(http.server.BaseHTTPRequestHandler):
        def setup(self):
            # Authenticate before creating buffered HTTP files. Failed TLS
            # handshakes otherwise leave makefile references holding sockets.
            self.connection = self.request
            def expire():
                try: self.connection.shutdown(socket.SHUT_RDWR)
                except OSError: pass
            self.deadline_timer = threading.Timer(30, expire)
            self.deadline_timer.daemon = True
            self.deadline_timer.start()
            self.connection.settimeout(5)
            try:
                self.connection.do_handshake()
                fingerprint=hashlib.sha256(self.connection.getpeercert(binary_form=True)).hexdigest()
                if fingerprint in trusted_clients:
                    # Authenticated anonymous carriers can pause between TLS records.
                    # Unauthenticated connections keep the short handshake budget.
                    self.connection.settimeout(25)
                    self.deadline_timer.cancel()
                    self.deadline_timer=threading.Timer(90,expire)
                    self.deadline_timer.daemon=True;self.deadline_timer.start()
                super().setup()
            except BaseException:
                self.deadline_timer.cancel()
                raise

        def finish(self):
            try: super().finish()
            finally: self.deadline_timer.cancel()

        def log_message(self, *_):
            pass

        def send_response(self, code, message=None):
            # Authenticated peers need status codes, not Python/product banners.
            self.send_response_only(code, message)
            self.send_header("Date", self.date_time_string())

        def send_error(self, code, message=None, explain=None):
            self.send_response(code)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()

        def do_POST(self):
            status, result, padded = 200, None, False
            delivery_id=None
            length_header=self.headers.get('Content-Length','')
            if len(self.headers.get_all('Content-Length',[]))==1 and length_header.isascii() and length_header.isdecimal() and len(length_header)<=6:
                announced=int(length_header)
                padded=16384<=announced<=MAX_REQUEST and announced&(announced-1)==0
            try:
                if (self.path != "/zfcp" or self.headers.get("Transfer-Encoding") or self.headers.get("Content-Type") != "application/json" or
                        len(self.headers.get_all("Content-Length", [])) != 1 or len(self.headers.get_all("Content-Type", [])) != 1):
                    raise ProtocolError("INVALID_REQUEST", "bounded JSON POST /zfcp required")
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= MAX_REQUEST:
                    raise ProtocolError("INVALID_REQUEST", "request size budget exceeded")
                envelope = strict_json(self.rfile.read(length))
                if isinstance(envelope,dict) and envelope.get('schema')=='ziokt.zkn-delivery.v2':
                    from .collectibles import unwrap_delivery
                    envelope,delivery_id=unwrap_delivery(envelope,length)
                    padded=True
                if (not isinstance(envelope, dict) or not {"request","grant"} <= set(envelope) or set(envelope)-{"request","grant","padding"} or
                        "padding" in envelope and not valid_padding(envelope["padding"])):
                    raise ProtocolError("INVALID_REQUEST", "exact request and scoped grant required")
                if "padding" in envelope and (length<16384 or length&(length-1)):
                    raise ProtocolError("INVALID_REQUEST","padded request must use a bounded power-of-two frame")
                padded=padded or "padding" in envelope
                request = envelope["request"]
                if (not isinstance(request, dict) or set(request) != {"provider_id", "method", "params"} or
                        not isinstance(request["params"], dict) or not isinstance(request["provider_id"], str) or not isinstance(request["method"], str)):
                    raise ProtocolError("INVALID_REQUEST", "typed provider operation required")
                cert = self.connection.getpeercert(binary_form=True)
                principal = trusted_clients.get(hashlib.sha256(cert).hexdigest())
                if not principal or request["method"] not in principal["methods"] or request["provider_id"] not in principal["providers"]:
                    raise ProtocolError("POLICY_DENIED", "certificate is not allowed for requested operation")
                is_community = community is not None and request["provider_id"] == community.community.community_id
                if request["provider_id"] not in providers and not is_community:
                    raise ProtocolError("POLICY_DENIED", "provider not configured on this server")
                if request["method"] in WRITE_METHODS and not allow_mutations:
                    raise ProtocolError("MUTATION_DISABLED", "remote mutations are disabled")
                if delivery_id is not None:
                    from .collectibles import delivery_digest
                    digest=delivery_digest(request,delivery_id)
                    if request['method'] not in {'zkn.fact','operation.prepare','operation.commit','operation.reconcile'}:
                        raise ProtocolError('POLICY_DENIED','collectible delivery method required')
                    if request['method']=='operation.prepare' and request['params'].get('action')!='zkn.gift':
                        raise ProtocolError('POLICY_DENIED','collectible gift preparation required')
                else:digest="sha256:"+hashlib.sha256(encoded(request)).hexdigest()
                with authority_lock:
                    authority.admit(envelope["grant"], principal["public_key"],
                        audience=request["provider_id"], action=request["method"], resource=resource_for(request["method"], request["params"]),
                        federation=federation["federation_id"], request_digest=digest)
                if not slots.acquire(False):
                    raise ProtocolError("BACKPRESSURE", "remote native execution budget exhausted")
                try:
                    if is_community:
                        value = community.call(request["method"], request["params"], principal["public_key"])
                    else:
                        value = NativeClient(federation["federation_id"], providers[request["provider_id"]]).call(request["method"], request["params"])
                finally:
                    slots.release()
                result = {"ok": True, "result": value}
            except TimeoutError:
                status=504
                result={'ok':False,'error':{'code':'CARRIER_UNAVAILABLE','message':'bounded authenticated transport deadline exceeded'}}
            except (ProtocolError, ValueError, OSError, TypeError, KeyError) as exc:
                status = 403 if isinstance(exc, ProtocolError) else 400
                result = {"ok": False, "error": {"code": getattr(exc, "code", "INVALID_REQUEST"),
                    "message": str(exc) if isinstance(exc, ProtocolError) else "remote request rejected"}}
            def response_bytes(value):
                if delivery_id is not None:
                    from .collectibles import wrap_delivery
                    return wrap_delivery(value,delivery_id,MAX_RESPONSE,response=True)
                return padded_json(value,MAX_RESPONSE) if padded else encoded(value)
            try:raw = response_bytes(result)
            except ProtocolError:
                status=413;result={"ok":False,"error":{"code":"RESPONSE_LIMIT","message":"response budget exceeded"}}
                raw=response_bytes(result)
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


def request_remote(host, port, context, request, signed_grant, *, carrier=None, timeout=None, cancellation=None, privacy_padding=False, delivery_id=None):
    from .runtime_policy import require_network
    require_network()
    from .carrier import carrier_deadline, open_carrier, validate_carrier
    if type(privacy_padding) is not bool:raise ProtocolError("INVALID_CONFIG","explicit privacy padding flag required")
    if carrier is not None: validate_carrier(carrier, host)
    preferred = carrier_deadline(carrier)
    maximum = 120 if preferred > 30 else 30
    if timeout is None: timeout = preferred
    if type(timeout) not in {int, float} or not 0 < timeout <= maximum:
        raise ProtocolError("INVALID_CONFIG", "bounded remote deadline required")
    connection = http.client.HTTPSConnection(host, port, context=context, timeout=timeout)
    deadline = time.monotonic()+timeout
    timer = None
    response = None
    done = threading.Event()
    expired = threading.Event()
    try:
        raw_socket = open_carrier(host, port, carrier, timeout=timeout, cancellation=cancellation)
        try:
            if carrier is not None and carrier['kind'] in {'peer-multihop', 'shadow6-stream'}:
                from .peer_proxy import TLSStream
                connection.sock = TLSStream(raw_socket, context, host, deadline)
            else:
                connection.sock = context.wrap_socket(raw_socket, server_hostname=host, do_handshake_on_connect=False)
        except BaseException:
            raw_socket.close()
            raise
        def stop_io():
            # SSL wrapping takes ownership of the descriptor: the original
            # raw_socket object no longer owns the live connection.
            active = connection.sock
            if active is not None:
                try: active.shutdown(socket.SHUT_RDWR)
                except OSError: pass
        if cancellation is not None:
            if cancellation.is_set(): raise ProtocolError('CANCELLED', 'remote request cancelled')
            def monitor():
                while not done.wait(.2):
                    if cancellation.is_set():
                        stop_io()
                        return
            watcher = threading.Thread(target=monitor, daemon=True); watcher.start()
        remaining = deadline-time.monotonic()
        if remaining <= 0: raise TimeoutError("remote deadline")
        connection.sock.settimeout(remaining)
        def expire():
            expired.set()
            stop_io()
        timer = threading.Timer(remaining, expire); timer.daemon = True; timer.start()
        connection.sock.do_handshake()
        if cancellation is not None and cancellation.is_set(): raise ProtocolError('CANCELLED', 'remote request cancelled')
        if expired.is_set() or time.monotonic() >= deadline: raise TimeoutError('bounded remote deadline exceeded')
        envelope={"request":request,"grant":signed_grant() if callable(signed_grant) else signed_grant}
        if delivery_id is not None:
            from .collectibles import wrap_delivery
            body=wrap_delivery(envelope,delivery_id,MAX_REQUEST)
        else:body = padded_json(envelope,MAX_REQUEST) if privacy_padding else encoded(envelope)
        if len(body) > MAX_REQUEST:
            raise ProtocolError("INVALID_REQUEST", "remote request exceeds budget")
        connection.request("POST", "/zfcp", body, {"Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE+1)
        if cancellation is not None and cancellation.is_set(): raise ProtocolError('CANCELLED', 'remote request cancelled')
        if expired.is_set() or time.monotonic() >= deadline: raise TimeoutError('bounded remote deadline exceeded')
        result = strict_json(raw, MAX_RESPONSE)
        if delivery_id is not None:
            from .collectibles import unwrap_delivery
            result,returned_id=unwrap_delivery(result,len(raw),response=True)
            if returned_id!=delivery_id:raise ProtocolError('INVALID_RESPONSE','collectible delivery correlation rejected')
        if (not isinstance(result, dict) or type(result.get("ok")) is not bool or
                "padding" in result and not valid_padding(result["padding"]) or
                privacy_padding and delivery_id is None and "padding" not in result):
            raise ProtocolError("INVALID_RESPONSE", "typed remote response required")
        fields={"ok","result"} if result["ok"] else {"ok","error"}
        if set(result)-{"padding"} != fields:raise ProtocolError("INVALID_RESPONSE","exact typed remote response required")
        if result.get("ok") is not True:
            error=result["error"]
            if not isinstance(error,dict) or set(error)!={"code","message"} or not all(isinstance(v,str) for v in error.values()):raise ProtocolError("INVALID_RESPONSE","typed remote error required")
            raise ProtocolError(error["code"],error["message"])
        if expired.is_set() or time.monotonic() >= deadline: raise TimeoutError('bounded remote deadline exceeded')
        return result["result"]
    except (OSError, http.client.HTTPException) as exc:
        if cancellation is not None and cancellation.is_set():
            raise ProtocolError('CANCELLED', 'remote request cancelled') from None
        if expired.is_set() and not isinstance(exc, ssl.SSLCertVerificationError):
            raise TimeoutError('bounded remote deadline exceeded') from None
        raise
    finally:
        done.set()
        if timer is not None: timer.cancel()
        if response is not None: response.close()
        connection.close()


def load_remote(path, serving=False):
    from .protocol import secure_read
    config = strict_json(secure_read(path))
    base = {"schema", "host", "port", "certificate", "private_key", "ca"}
    extra = {"replay_state", "trusted_clients", "allow_mutations"} if serving else set()
    optional = set() if serving else {"carrier", "connection_policy", "rendezvous", "candidates", "discovery"}
    if not isinstance(config, dict) or not base|extra <= set(config) or set(config)-(base|extra|optional) or config["schema"] != "ziokt.remote.v1":
        raise ProtocolError("INVALID_CONFIG", "exact private remote endpoint configuration required")
    for field in ("certificate", "private_key", "ca", *(["replay_state"] if serving else [])):
        if not isinstance(config[field], str) or not Path(config[field]).is_absolute() or ".." in Path(config[field]).parts:
            raise ProtocolError("INVALID_CONFIG", "fixed absolute remote material paths required")
    if not isinstance(config["host"], str) or type(config["port"]) is not int or not 0 <= config["port"] <= 65535:
        raise ProtocolError("INVALID_CONFIG", "bounded remote endpoint required")
    if "carrier" in config:
        from .carrier import validate_carrier
        validate_carrier(config["carrier"], config["host"])
    if "connection_policy" in config:
        from .routes import validate_route
        validate_route(config["connection_policy"], config)
    if 'candidates' in config and config.get('connection_policy', {}).get('mode') != 'approved-paths':
        raise ProtocolError('INVALID_CONFIG', 'candidates require explicit approved-paths mode')
    if "rendezvous" in config:
        value = config["rendezvous"]
        if not isinstance(value, dict) or set(value) != {"recipient"} or not isinstance(value["recipient"], str) or not re.fullmatch('[a-f0-9]{64}', value['recipient']):
            raise ProtocolError('INVALID_CONFIG', 'fixed approved relay recipient identity required')
    return config

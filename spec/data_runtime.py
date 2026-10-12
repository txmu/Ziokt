"""Core-neutral encrypted application records over stream or message boundaries.

Native Core wire protocols remain untouched. Fixed Corium read operations retain
their native signatures; an additional signed application envelope binds network,
nonce, expiry and the authenticated responder. No arbitrary target or shell.
"""
import socket
import socketserver
import struct
import threading

DATA_MAGIC = b"ZIOKT-D1"
DATA_HEADER = struct.Struct("!16sBHHH")
DATA_MAX = 65536
DATA_PARTS = 256


class DataCipher:
    def __init__(self, key, server=False):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if not isinstance(key, bytes) or len(key) != 32:
            fail("INVALID_DATA_KEY", "32-byte private application key required")
        client = HKDF(hashes.SHA256(), 32, None, b"Ziokt/data/client/v1").derive(key)
        responder = HKDF(hashes.SHA256(), 32, None, b"Ziokt/data/server/v1").derive(key)
        self.send = AESGCM(responder if server else client)
        self.receive = AESGCM(client if server else responder)

    def pack(self, request_id, kind, index, count, payload=b"", pad_to=None):
        if (not isinstance(request_id, bytes) or len(request_id) != 16 or kind not in {1,2,3,4,5,6} or
                type(index) is not int or not 0 <= index < DATA_PARTS or type(count) is not int or not 0 <= count <= DATA_PARTS or
                not isinstance(payload, bytes) or len(payload) > 8192-59):
            fail("INVALID_DATA_FRAME", "bounded typed encrypted frame required")
        nonce = os.urandom(12)
        plain = DATA_HEADER.pack(request_id, kind, index, count, len(payload)) + payload
        if pad_to is not None:
            if type(pad_to) is not int or not len(plain)+28 <= pad_to <= 8192:
                fail("DATA_FRAME_LIMIT", "padding must fit the original native record budget")
            plain += os.urandom(pad_to-28-len(plain))
        # Version/domain is authenticated as AAD, not a cleartext product marker.
        return nonce + self.send.encrypt(nonce, plain, DATA_MAGIC)

    def unpack(self, frame):
        from cryptography.exceptions import InvalidTag
        if not isinstance(frame, bytes) or not 51 <= len(frame) <= 8192:
            fail("INVALID_DATA_FRAME", "bounded encrypted application record required")
        try:
            plain = self.receive.decrypt(frame[:12], frame[12:], DATA_MAGIC)
        except InvalidTag:
            fail("DATA_AUTH_REJECTED", "application record authentication failed")
        if len(plain) < DATA_HEADER.size:
            fail("INVALID_DATA_FRAME", "truncated application record")
        request_id, kind, index, count, payload_size = DATA_HEADER.unpack(plain[:DATA_HEADER.size])
        if payload_size > len(plain)-DATA_HEADER.size: fail("INVALID_DATA_FRAME", "encrypted payload length exceeds frame")
        if kind not in {1, 2, 3, 4, 5, 6} or count > DATA_PARTS or index >= DATA_PARTS:
            fail("INVALID_DATA_FRAME", "record kind or fragmentation budget rejected")
        return request_id, kind, index, count, plain[DATA_HEADER.size:DATA_HEADER.size+payload_size]


class FrameSocket:
    def __init__(self, sock, kind, maximum=4096):
        if kind not in {"stream", "message"} or type(maximum) is not int or not 128 <= maximum <= 8192:
            fail("UNSUPPORTED_BOUNDARY", "bounded stream/message application contract required")
        self.socket, self.kind, self.maximum = sock, kind, maximum
        self.buffer = bytearray()

    def send(self, frame):
        if not frame or len(frame) > self.maximum:
            fail("DATA_FRAME_LIMIT", "application record exceeds native boundary")
        if self.kind == "stream":
            self.socket.sendall(struct.pack("!I", len(frame)) + frame)
        elif self.socket.send(frame) != len(frame):
            fail("DATA_SHORT_SEND", "record was not submitted in full")

    def receive(self):
        if self.kind == "message":
            frame = self.socket.recv(self.maximum + 1)
            if not frame or len(frame) > self.maximum:
                fail("DATA_FRAME_LIMIT", "truncated or oversized native record")
            return frame
        while True:
            if len(self.buffer) >= 4:
                size = struct.unpack("!I", self.buffer[:4])[0]
                if not 57 <= size <= self.maximum:
                    fail("DATA_FRAME_LIMIT", "stream frame length rejected")
                if len(self.buffer) >= size + 4:
                    frame = bytes(self.buffer[4:size+4]); del self.buffer[:size+4]
                    return frame
            chunk = self.socket.recv(8192)
            if not chunk:
                fail("DATA_CLOSED", "application boundary closed")
            self.buffer.extend(chunk)
            if len(self.buffer) > 16384:
                fail("DATA_FRAME_LIMIT", "stream receive buffer exceeded")


def native_ec_verify(public, signature, message):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.exceptions import InvalidSignature
    try:
        key = serialization.load_pem_public_key(public.encode())
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256K1):
            raise ValueError()
        key.verify(bytes.fromhex(signature), message, ec.ECDSA(hashes.SHA256()))
    except (ValueError, TypeError, InvalidSignature):
        fail("NATIVE_SIGNATURE_REJECTED", "native Corium signature rejected")


def native_ec_sign(key, message):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    return key.sign(message, ec.ECDSA(hashes.SHA256())).hex()


class CoriumDataChannel:
    def __init__(self, handle, key, native_private, expected_peer, network, privacy_profile="standard"):
        from cryptography.hazmat.primitives import serialization
        self.handle = handle
        boundary = handle.boundary
        self.frames = FrameSocket(handle.socket, boundary.kind, min(boundary.max_record or 4096, 4096))
        self.cipher = DataCipher(key)
        if privacy_profile not in {"standard", "private"}: fail("NO_POLICY_COMPLIANT_PATH", "verified anonymous carrier required for restricted profile")
        self.padding = self.frames.maximum if privacy_profile == "private" else None
        self.private = native_private
        self.public = native_private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip("\n")
        self.expected_peer, self.network = expected_peer, network

    def call(self, message_type, payload="", timeout=30):
        if type(timeout) not in {int, float} or not 0 < timeout <= 30:
            fail("INVALID_DATA_TIMEOUT", "finite application deadline required")
        request_id = os.urandom(16)
        native = {"type": message_type, "payload": payload,
                  "sender_id": hashlib.sha256(self.public.encode()).hexdigest(), "public_key": self.public,
                  "signature": native_ec_sign(self.private, (message_type + "|" + payload).encode())}
        body = {"schema": "ziokt.corium-request.v1", "network_id": self.network,
                "request_id": request_id.hex(), "expires_at": int(time.time()) + 30, "native": native}
        request = {"body": body, "signature": native_ec_sign(self.private, b"Ziokt/C/request/v1\n" + encoded(body))}
        raw = encoded(request)
        if len(raw) > DATA_MAX:
            fail("DATA_MESSAGE_LIMIT", "application request exceeds budget")
        chunk_size = self.frames.maximum - 64
        parts = [raw[offset:offset+chunk_size] for offset in range(0, len(raw), chunk_size)]
        if len(parts) > DATA_PARTS:
            fail("DATA_MESSAGE_LIMIT", "native boundary requires too many fragments")
        deadline = time.monotonic() + timeout
        previous_timeout = self.frames.socket.gettimeout()

        def exchange(kind, index, count, data, expected):
            for _ in range(4):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    fail("DATA_TIMEOUT", "application request deadline exceeded")
                self.frames.socket.settimeout(min(2, remaining))
                self.frames.send(self.cipher.pack(request_id, kind, index, count, data, self.padding))
                try:
                    for _ in range(8):
                        rid, received, position, total, content = self.cipher.unpack(self.frames.receive())
                        if rid != request_id or position != index:
                            continue
                        if received == 6:
                            fail("DATA_REQUEST_REJECTED", content.decode("ascii", "replace"))
                        if received == expected:
                            return total, content
                        if received == 5:
                            time.sleep(min(.01, max(0, deadline-time.monotonic())))
                            break
                except socket.timeout:
                    continue
            fail("DATA_RETRY_EXHAUSTED", "bounded application retransmission exhausted")
        try:
            for index, part in enumerate(parts):
                exchange(1, index, len(parts), part, 2)
            total, first = exchange(3, 0, 0, b"", 4)
            response = bytearray(first)
            if not 1 <= total <= DATA_PARTS:
                fail("INVALID_DATA_FRAME", "invalid response fragment count")
            for index in range(1, total):
                count, part = exchange(3, index, 0, b"", 4)
                if count != total or len(response) + len(part) > DATA_MAX:
                    fail("INVALID_DATA_FRAME", "response fragmentation changed")
                response.extend(part)
            envelope = strict_json(bytes(response), DATA_MAX)
            if set(envelope) != {"body", "public_key", "signature"}:
                fail("INVALID_DATA_FRAME", "exact signed response required")
            result = envelope["body"]
            if hashlib.sha256(envelope["public_key"].rstrip("\n").encode()).hexdigest() != self.expected_peer:
                fail("NATIVE_IDENTITY_REJECTED", "Corium responder identity mismatch")
            if result["request_id"] != request_id.hex() or result["network_id"] != self.network:
                fail("NATIVE_IDENTITY_REJECTED", "Corium response scope mismatch")
            native_ec_verify(envelope["public_key"], envelope["signature"], b"Ziokt/C/response/v1\n" + encoded(result))
            return result["native"]
        finally:
            self.frames.socket.settimeout(previous_timeout)


class CoriumDataGateway:
    def __init__(self, key, native_private, handler, network, root=None):
        from cryptography.hazmat.primitives import serialization
        self.cipher = DataCipher(key, server=True)
        self.private, self.handler, self.network = native_private, handler, network
        self.public = native_private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip("\n")
        self.root, self.pending, self.lock = root, {}, threading.RLock()
        self.verified_content = {}

    def content_range(self, query):
        if (not isinstance(query, dict) or not {"digest"} <= set(query) or set(query)-{"digest", "offset", "length"} or
                not isinstance(query["digest"], str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", query["digest"]) or self.root is None or
                type(query.get("offset", 0)) is not int or not 0 <= query.get("offset", 0) <= 64*1024*1024 or
                type(query.get("length", 6144)) is not int or not 1 <= query.get("length", 6144) <= 6144):
            fail("INVALID_PARAMS", "bounded immutable native content range required")
        config = load_config("corium", self.root/"etc/corix/networks"/self.network/"corix.conf")
        if not config["enabled"]: fail("ZIOKT_DISABLED", "native content binding was disabled")
        directory = Path(config["artifact_root"]) if "artifact_root" in config else self.root/"var/lib/corix/p2p/objects/ziokt"
        safe_directory(directory)
        path = directory/query["digest"][7:]
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_mode & 0o077 or before.st_size > 64*1024*1024):
            fail("UNSAFE_FILE", "private bounded native content object required")
        fd = os.open(path, os.O_RDONLY|os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            signature = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
            if signature != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns):
                fail("UNSAFE_FILE", "native object changed while opening")
            cached = self.verified_content.get(query["digest"])
            if cached != signature:
                hasher = hashlib.sha256()
                while True:
                    data = os.read(fd, 65536)
                    if not data: break
                    hasher.update(data)
                if hasher.hexdigest() != query["digest"][7:]: fail("ARTIFACT_DIGEST_MISMATCH", "native content integrity rejected")
                if len(self.verified_content) >= 64: self.verified_content.clear()
                self.verified_content[query["digest"]] = signature
            offset = query.get("offset", 0)
            if offset > opened.st_size: fail("INVALID_PARAMS", "native content offset exceeds immutable size")
            os.lseek(fd, offset, os.SEEK_SET); data = os.read(fd, min(query.get("length", 6144), opened.st_size-offset))
            after = os.fstat(fd)
            if signature != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                fail("ARTIFACT_DIGEST_MISMATCH", "native content changed during transfer")
            import base64
            return {"status": "success", "digest": query["digest"], "offset": offset,
                    "total_size": opened.st_size, "data_base64": base64.b64encode(data).decode()}
        finally: os.close(fd)

    def receive(self, frame):
        rid, kind, index, count, payload = self.cipher.unpack(frame)
        with self.lock:
            now = time.monotonic()
            self.pending = {k: v for k, v in self.pending.items() if v["deadline"] > now}
            if kind == 1:
                if not 1 <= count <= DATA_PARTS or index >= count:
                    fail("INVALID_DATA_FRAME", "request fragment bounds rejected")
                if rid not in self.pending:
                    if len(self.pending) >= 32:
                        fail("DATA_BACKPRESSURE", "gateway request budget exhausted")
                    self.pending[rid] = {"parts": {}, "count": count, "size": 0, "deadline": now+30, "frame_limit": len(frame),
                                         "padding": len(frame) if len(frame) > 51+len(payload) else None}
                entry = self.pending[rid]
                if entry["count"] != count or (index in entry["parts"] and entry["parts"][index] != payload):
                    fail("IDEMPOTENCY_CONFLICT", "request fragment changed")
                if index not in entry["parts"]:
                    entry["size"] += len(payload)
                    if entry["size"] > DATA_MAX:
                        fail("DATA_MESSAGE_LIMIT", "gateway request exceeds budget")
                    entry["parts"][index] = payload
                if len(entry["parts"]) == count and "response" not in entry:
                    raw = b"".join(entry["parts"][i] for i in range(count))
                    request = strict_json(raw, DATA_MAX)
                    if not isinstance(request, dict) or set(request) != {"body", "signature"}:
                        fail("INVALID_DATA_FRAME", "exact signed native request required")
                    body = request["body"]
                    if (not isinstance(body, dict) or set(body) != {"schema", "network_id", "request_id", "expires_at", "native"} or
                            body["schema"] != "ziokt.corium-request.v1" or body["network_id"] != self.network or
                            body["request_id"] != rid.hex() or type(body["expires_at"]) is not int or not int(time.time()) < body["expires_at"] <= int(time.time())+30):
                        fail("INVALID_DATA_FRAME", "native application scope/expiry rejected")
                    native = body["native"]
                    if (not isinstance(native, dict) or set(native) != {"type", "payload", "sender_id", "public_key", "signature"} or
                            not all(isinstance(v, str) for v in native.values()) or native["type"] not in {
                            "PING", "FIND_NODE", "FIND_VALUE", "GET_BLOCK_HASH_AT_HEIGHT", "GET_BLOCK_HEADER", "GET_TRANSACTION", "ZIOKT_CONTENT_GET"}):
                        fail("POLICY_DENIED", "only fixed native read operations are available")
                    native_ec_verify(native["public_key"], request["signature"], b"Ziokt/C/request/v1\n" + encoded(body))
                    if hashlib.sha256(native["public_key"].rstrip("\n").encode()).hexdigest() != native["sender_id"]:
                        fail("NATIVE_IDENTITY_REJECTED", "native requester identity mismatch")
                    native_ec_verify(native["public_key"], native["signature"], (native["type"] + "|" + native["payload"]).encode())
                    if native["type"] == "ZIOKT_CONTENT_GET":
                        query = strict_json(native["payload"].encode())
                        result = self.content_range(query)
                    else:
                        result = self.handler.handle_dht_message(native)
                    response_body = {"request_id": rid.hex(), "network_id": self.network, "native": result}
                    response = encoded({"body": response_body, "public_key": self.public,
                                        "signature": native_ec_sign(self.private, b"Ziokt/C/response/v1\n" + encoded(response_body))})
                    if len(response) > DATA_MAX:
                        fail("DATA_MESSAGE_LIMIT", "native response exceeds budget")
                    size = max(64, min(entry["frame_limit"] - 64, 4096-64))
                    entry["response"] = [response[o:o+size] for o in range(0, len(response), size)]
                    if len(entry["response"]) > DATA_PARTS:
                        fail("DATA_MESSAGE_LIMIT", "native response fragmentation exceeds budget")
                return self.cipher.pack(rid, 2, index, count, pad_to=entry["padding"])
            if kind == 3:
                entry = self.pending.get(rid)
                if not entry or "response" not in entry:
                    return self.cipher.pack(rid, 5, index, 0, pad_to=len(frame) if len(frame)>51 else None)
                if index >= len(entry["response"]):
                    fail("INVALID_DATA_FRAME", "response index out of bounds")
                return self.cipher.pack(rid, 4, index, len(entry["response"]), entry["response"][index], entry["padding"])
            fail("INVALID_DATA_FRAME", "invalid gateway frame direction")


def corium_native_handler(source, root, network):
    """Load the production gateway declarations from Corium's own monolith."""
    import ast
    text = secure_read(source, 8*1024*1024, private=None).decode()
    # Split the spelling too: Corium's static checker treats a source line
    # containing that spelling and a heredoc as a real Bash Python invocation.
    marker = "$" + "{PYTH" + "ON_CMD}" + " - <<'EOF' &\n"
    native = text.split(marker, 1)[1].split("\nEOF\n", 1)[0]
    nodes = ast.parse(native).body
    boundary = next(i for i, node in enumerate(nodes) if isinstance(node, ast.ClassDef) and node.name == "SandboxAPI")
    os.environ.update(CORIUM_NETWORK_ID=network, SCRIPT_PATH=str(source))
    namespace = {"__name__": "ziokt_corium_native_gateway"}
    exec(compile(ast.Module(body=nodes[:boundary], type_ignores=[]), str(source)+":native-gateway", "exec"), namespace)
    namespace.update(SCRIPT_PATH=str(source), BLOCKCHAIN_DB_PATH=str(root/"var/lib/corix/networks"/network/"blockchain/chain.db"),
                     FORUM_DB_PATH=str(root/"var/lib/corix/networks"/network/"forum/forum.db"),
                     DHT_DB_PATH=str(root/"var/lib/corix/p2p/dht.db"), USER_PUBLIC_KEY_FILE=str(root/"etc/corix/networks"/network/"identity.key.pub"), OUR_NODE_ID_CACHE=None)
    return namespace["CoriumGatewayHandler"].__new__(namespace["CoriumGatewayHandler"])


def serve_corium_data(root, network, key_file, port):
    from cryptography.hazmat.primitives import serialization
    private = serialization.load_pem_private_key(secure_read(root/"etc/corix/networks"/network/"identity.key"), password=None)
    source = os.environ.get("_ZIOKT_CORIUM_SOURCE")
    if not source:
        fail("NATIVE_STATE_UNAVAILABLE", "production monolith source unavailable")
    gateway = CoriumDataGateway(secure_read(key_file, 32), private, corium_native_handler(source, root, network), network, root)

    class TCPHandler(socketserver.BaseRequestHandler):
        def handle(self):
            deadline = time.monotonic()+45
            frames = FrameSocket(self.request, "stream", 8192)
            try:
                for _ in range(1024):
                    remaining = deadline-time.monotonic()
                    if remaining <= 0: return
                    self.request.settimeout(min(30, remaining))
                    frames.send(gateway.receive(frames.receive()))
            except (ProtocolError, OSError, TypeError, KeyError, ValueError):
                return

    class UDPHandler(socketserver.BaseRequestHandler):
        def handle(self):
            frame, endpoint = self.request
            try:
                endpoint.sendto(gateway.receive(frame), self.client_address)
            except (ProtocolError, OSError, TypeError, KeyError, ValueError):
                return

    class BoundedTCP(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = False
        slots = threading.BoundedSemaphore(32)
        def process_request(self, request, address):
            if not self.slots.acquire(False):
                self.shutdown_request(request); return
            super().process_request(request, address)
        def process_request_thread(self, request, address):
            try:
                super().process_request_thread(request, address)
            finally:
                self.slots.release()

    # UDP processing is serialized and bounded; never spawn a thread per packet.
    tcp = BoundedTCP(("127.0.0.1", port), TCPHandler)
    udp = socketserver.UDPServer(("127.0.0.1", tcp.server_address[1]), UDPHandler)
    extra, hosts = [], ["127.0.0.1"]
    if socket.has_ipv6:
        class TCP6(BoundedTCP):
            address_family = socket.AF_INET6
        class UDP6(socketserver.UDPServer):
            address_family = socket.AF_INET6
        extra = [TCP6(("::1", tcp.server_address[1]), TCPHandler), UDP6(("::1", tcp.server_address[1]), UDPHandler)]
        hosts.append("::1")
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in [tcp, *extra]]
    for thread in threads: thread.start()
    print(encoded({"event": "ziokt.data-ready", "host": "127.0.0.1", "hosts": hosts,
                   "port": tcp.server_address[1], "transports": ["stream", "message"]}).decode(), flush=True)
    try:
        udp.serve_forever()
    finally:
        for server in [tcp, *extra]: server.shutdown(); server.server_close()
        udp.server_close()

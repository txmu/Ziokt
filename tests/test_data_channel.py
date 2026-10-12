"""Real encrypted stream and record sockets, with native C signatures/handler."""
import ast
from pathlib import Path
import secrets
import socket
import sys
import threading
from types import SimpleNamespace
import unittest

from cryptography.hazmat.primitives.asymmetric import ec
from ziokt._runtime import CoriumDataChannel, CoriumDataGateway, DataCipher, FrameSocket, ProtocolError


class DataChannelTests(unittest.TestCase):
    def test_direction_keys_tampering_and_frame_limits(self):
        key = secrets.token_bytes(32)
        client, server = DataCipher(key), DataCipher(key, server=True)
        rid = secrets.token_bytes(16)
        frame = client.pack(rid, 1, 0, 1, b"payload")
        self.assertNotIn(b"ZIOKT-D1", frame)
        self.assertEqual(server.unpack(frame)[-1], b"payload")
        for bad in (frame[:-1] + bytes([frame[-1] ^ 1]), b"invalid", frame * 200):
            with self.assertRaises(ProtocolError):
                server.unpack(bad)
        with self.assertRaises(ProtocolError):
            client.unpack(frame)
        padded = client.pack(rid, 1, 0, 1, b"payload", 512)
        self.assertEqual(len(padded), 512)
        self.assertEqual(server.unpack(padded)[-1], b"payload")

    def test_stream_and_datagram_use_identical_signed_application_protocol(self):
        # The handler fixture verifies native request signatures in the same
        # format; genuine Corium/S E2E is a separate integration gate.
        from ziokt._runtime import native_ec_verify
        import hashlib
        server_key, client_key = ec.generate_private_key(ec.SECP256K1()), ec.generate_private_key(ec.SECP256K1())
        key = secrets.token_bytes(32)
        class Handler:
            def handle_dht_message(self, value):
                native_ec_verify(value["public_key"], value["signature"], (value["type"]+"|"+value["payload"]).encode())
                return {"status": "success", "data": "PONG:" + "x" * 1500}
        for kind in ("stream", "message"):
            with self.subTest(kind=kind):
                if kind == "stream":
                    left, right = socket.socketpair()
                else:
                    left, right = socket.socket(socket.AF_INET, socket.SOCK_DGRAM), socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    left.bind(("127.0.0.1", 0)); right.bind(("127.0.0.1", 0))
                    left.connect(right.getsockname()); right.connect(left.getsockname())
                gateway = CoriumDataGateway(key, server_key, Handler(), "test")
                peer = hashlib.sha256(gateway.public.encode()).hexdigest()
                handle = SimpleNamespace(socket=left, boundary=SimpleNamespace(kind=kind, max_record=512))
                errors = []; stop = threading.Event()
                def worker():
                    frames = FrameSocket(right, kind, 512); right.settimeout(.2)
                    while not stop.is_set():
                        try:
                            frames.send(gateway.receive(frames.receive()))
                        except socket.timeout:
                            continue
                        except (OSError, ProtocolError) as exc:
                            if not stop.is_set(): errors.append(exc)
                            break
                thread = threading.Thread(target=worker); thread.start()
                try:
                    result = CoriumDataChannel(handle, key, client_key, peer, "test", "private").call("PING", "content" * 100)
                    self.assertEqual(result["data"], "PONG:" + "x" * 1500)
                    self.assertEqual(errors, [])
                finally:
                    stop.set(); left.close(); right.close(); thread.join(2)


if __name__ == "__main__":
    unittest.main()

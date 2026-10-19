"""Real mTLS trickle responses must not evade overall timeouts/cancellation."""
import http.server
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from test_community_network import certificates
from ziokt.protocol import ProtocolError
from ziokt.remote import request_remote, tls_context


class RemoteDeadlineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ziokt-deadline-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        ca, pairs = certificates(root, 'localhost')
        self.context = tls_context(*pairs['client'][:2], ca)
        self.received = threading.Event()
        received = self.received

        class Slow(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_): pass

            def do_POST(self):
                self.close_connection = True
                self.rfile.read(int(self.headers['Content-Length']))
                payload = json.dumps({'ok': True, 'result': {'verified': True}}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                received.set()
                try:
                    # Every individual read is fast; only an actual overall
                    # deadline can stop this response before it is complete.
                    for byte in payload:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(.04)
                except OSError:
                    pass

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Slow)
        server.daemon_threads = True
        server.socket = tls_context(*pairs['server'][:2], ca, server=True).wrap_socket(server.socket, server_side=True)
        self.server = server
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

    def test_trickle_cannot_extend_overall_tls_deadline(self):
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            request_remote('localhost', self.server.server_port, self.context,
                           {'method': 'community.status'}, {}, timeout=.25)
        self.assertLess(time.monotonic()-start, 1.5)

    def test_cancellation_interrupts_wrapped_tls_socket(self):
        cancel = threading.Event()

        def stop():
            if self.received.wait(3): cancel.set()

        thread = threading.Thread(target=stop, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        start = time.monotonic()
        with self.assertRaises(ProtocolError) as caught:
            request_remote('localhost', self.server.server_port, self.context,
                           {'method': 'community.status'}, {}, timeout=5, cancellation=cancel)
        self.assertEqual(caught.exception.code, 'CANCELLED')
        self.assertLess(time.monotonic()-start, 1.5)


if __name__ == '__main__':
    unittest.main()

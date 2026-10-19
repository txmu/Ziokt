"""An unauthenticated idle TCP client must not pin a DoT worker forever."""
import socket
import threading
import time
import unittest

from ziokt.dns_server import servers


class TLSAdmissionTests(unittest.TestCase):
    def test_idle_client_is_closed_before_tls_handshake(self):
        opened = servers(object(), host='127.0.0.1', port=None, doh_port=None, dot_port=0)
        server = opened[0]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with socket.create_connection(server.server_address, timeout=2) as client:
            client.settimeout(8)
            start = time.monotonic()
            # No ClientHello is sent; the peer must release its worker/socket.
            self.assertEqual(client.recv(1), b'')
            self.assertLess(time.monotonic()-start, 7)


if __name__ == '__main__':
    unittest.main()

"""Local socket tests for sanitized Tor diagnostics; no public network traffic."""
import contextlib
from pathlib import Path
import secrets
import socketserver
import tempfile
import threading
import time
import unittest
from test_community_network import ONION
from test_tor_live import tor_health
from ziokt.carrier import connect_onion
from ziokt.protocol import ProtocolError


class LocalServer(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True


@contextlib.contextmanager
def server(handler):
    service=LocalServer(('127.0.0.1',0),handler)
    thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
    try:yield service.server_address[1]
    finally:service.shutdown();service.server_close();thread.join(5)


class TorDiagnostics(unittest.TestCase):
    def test_cancel_interrupts_pending_socks_negotiation(self):
        ready, cancel = threading.Event(), threading.Event()
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.request.settimeout(3)
                self.rfile.read(3)
                ready.set()
                try:self.rfile.read(1)
                except OSError:pass
        def stop():
            if ready.wait(2):cancel.set()
        thread = threading.Thread(target=stop, daemon=True)
        thread.start()
        try:
            with server(Handler) as port:
                start = time.monotonic()
                with self.assertRaises(ProtocolError) as caught:
                    connect_onion(ONION,443,{'kind':'tor-socks5','proxy_host':'127.0.0.1','proxy_port':port},cancellation=cancel)
                self.assertEqual(caught.exception.code,'CANCELLED')
                self.assertLess(time.monotonic()-start,1.5)
        finally:thread.join(3)

    def test_extended_socks_rejection_retains_code_and_stage_without_destination(self):
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.request.settimeout(2)
                if self.rfile.read(3)!=b'\x05\x01\x02':return
                self.wfile.write(b'\x05\x02');self.wfile.flush()
                if self.rfile.read(1)!=b'\x01':return
                self.rfile.read(self.rfile.read(1)[0]);self.rfile.read(self.rfile.read(1)[0])
                self.wfile.write(b'\x01\x00');self.wfile.flush()
                if self.rfile.read(4)!=b'\x05\x01\x00\x03':return
                self.rfile.read(self.rfile.read(1)[0]);self.rfile.read(2)
                self.wfile.write(b'\x05\xf0\x00\x01\x00\x00\x00\x00\x00\x00');self.wfile.flush()
        with server(Handler) as port:
            with self.assertRaises(ProtocolError) as failed:
                connect_onion(ONION,443,{'kind':'tor-socks5','proxy_host':'127.0.0.1','proxy_port':port})
        self.assertEqual(failed.exception.code,'CARRIER_UNAVAILABLE')
        self.assertIn('phase=target-socks-connect',str(failed.exception))
        self.assertIn('socks_reply=0xf0',str(failed.exception))
        self.assertNotIn(ONION,str(failed.exception));self.assertNotIn(str(port),str(failed.exception))

    def test_cookie_control_health_is_bounded_and_omits_network_identifiers(self):
        cookie=secrets.token_bytes(32);commands=[]
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.request.settimeout(2)
                while line:=self.rfile.readline(8192):
                    command=line.decode().strip();commands.append(command)
                    if command.startswith('AUTHENTICATE '):
                        if command.split()[1]!=cookie.hex():self.wfile.write(b'515 Authentication failed\r\n');self.wfile.flush();return
                        response='250 OK\r\n'
                    elif command=='GETINFO status/circuit-established':response='250-status/circuit-established=1\r\n250 OK\r\n'
                    elif command=='GETINFO network-liveness':response='250-network-liveness=up\r\n250 OK\r\n'
                    elif command=='GETINFO circuit-status':response='250+circuit-status=\r\n123 BUILT $PRIVATE_RELAY_PATH PURPOSE=HS_CLIENT_REND\r\n124 EXTENDED $ANOTHER_RELAY\r\n.\r\n250 OK\r\n'
                    else:response='552 Unrecognized key\r\n'
                    self.wfile.write(response.encode());self.wfile.flush()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'control.cookie').write_bytes(cookie)
            with server(Handler) as port:
                result=tor_health(root,port,['Bootstrapped 100% (done)','[warn] private address in ignored raw log'])
        self.assertEqual(result,{'bootstrap_progress':100,'warning_lines_in_tail':1,'status/circuit-established':'1','network-liveness':'up','circuit_states':{'BUILT':1,'EXTENDED':1}})
        self.assertNotIn(cookie.hex(),str(result));self.assertNotIn('PRIVATE_RELAY',str(result))
        self.assertEqual(len(commands),4)

"""Bounded local control-protocol units; not onion-network connectivity evidence."""
from pathlib import Path
import secrets
import socketserver
import tempfile
import threading
import unittest
from ziokt.tor_control import DescriptorObserver
from ziokt.protocol import ProtocolError
from test_community_network import ONION

class ControlTests(unittest.TestCase):
    def run_observer(self,event):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);cookie=Path(temp.name)/'cookie';cookie.write_bytes(secrets.token_bytes(32));cookie.chmod(0o600)
        expected=cookie.read_bytes().hex()
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                if self.rfile.readline()!=('AUTHENTICATE '+expected+'\r\n').encode():return
                self.wfile.write(b'250 OK\r\n');self.wfile.flush()
                if self.rfile.readline()!=b'SETEVENTS HS_DESC\r\n':return
                self.wfile.write(b'250 OK\r\n'+event);self.wfile.flush()
                self.rfile.read(1)
        server=socketserver.ThreadingTCPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever);thread.start()
        def close():server.shutdown();server.server_close();thread.join()
        self.addCleanup(close)
        observer=DescriptorObserver('127.0.0.1',server.server_address[1],cookie,[ONION]);self.addCleanup(observer.close)
        return observer
    def test_only_authenticated_service_upload_receipt_counts_and_is_sanitized(self):
        observer=self.run_observer(('650 HS_DESC UPLOADED '+ONION[:-6]+' NO_AUTH relay\r\n').encode())
        health=observer.wait(1);self.assertEqual(health['uploaded_services'],1)
        self.assertNotIn(ONION[:-6],str(health));self.assertNotIn('application_verified',health)
    def test_bootstrap_and_other_service_events_never_imply_publication(self):
        observer=self.run_observer(b'650 STATUS_CLIENT NOTICE BOOTSTRAP PROGRESS=100\r\n650 HS_DESC UPLOADED unknown NO_AUTH relay\r\n')
        with self.assertRaises(ProtocolError):observer.wait(.1)
        self.assertEqual(observer.health()['uploaded_services'],0)
if __name__=='__main__':unittest.main()

"""Real externally routed onion service gate, mandatory in anonymous-carrier CI.

Temporary unprivileged Tor process; no system Tor, firewall or route changes.
"""
import os
from pathlib import Path
import queue
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import hashlib

from test_community_network import certificates
from ziokt.community import Community, RIGHTS, create_policy
from ziokt.community_network import CommunityEndpoint, sync_remote
from ziokt.protocol import ProtocolError
from ziokt.remote import remote_server, tls_context
from ziokt.security import sign
from cryptography.hazmat.primitives import serialization


class TorLiveTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('ZIOKT_TOR_LIVE') == '1', 'real Tor network is a separate mandatory CI gate')
    def test_actual_onion_mutual_tls_and_community_cold_sync(self):
        self.assertIsNotNone(shutil.which('tor'), 'real Tor executable required')
        with tempfile.TemporaryDirectory(prefix='ziokt-onion-') as directory:
            root = Path(directory); hidden = root/'hidden'; hidden.mkdir(mode=0o700)
            with socket.socket() as available:
                available.bind(('127.0.0.1', 0)); service_port = available.getsockname()[1]
            with socket.socket() as available:
                available.bind(('127.0.0.1', 0)); socks_port = available.getsockname()[1]
            process = subprocess.Popen(['tor', '--DataDirectory', str(root/'tor'), '--SocksPort', '127.0.0.1:'+str(socks_port),
                '--HiddenServiceDir', str(hidden), '--HiddenServicePort', '443 127.0.0.1:'+str(service_port),
                '--Log', 'notice stdout', '--ClientOnly', '0'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            messages = queue.Queue()
            reader = threading.Thread(target=lambda: [messages.put(line) for line in process.stdout], daemon=True); reader.start()
            source = target = server = thread = None
            try:
                deadline = time.monotonic()+180
                bootstrapped = False
                while time.monotonic() < deadline:
                    if process.poll() is not None: self.fail('temporary Tor process exited before bootstrap')
                    try: line = messages.get(timeout=1)
                    except queue.Empty: continue
                    if 'Bootstrapped 100%' in line: bootstrapped = True; break
                self.assertTrue(bootstrapped, 'actual Tor network did not bootstrap within 180 seconds')
                host = (hidden/'hostname').read_text().strip()
                private, key = secrets.token_bytes(32), secrets.token_bytes(32)
                public = sign({}, private, 'test')['public_key']
                policy = create_policy(private, 'village', {public: sorted(RIGHTS)})
                source = Community(root/'source', policy, public, key)
                target = Community(root/'target', policy, public, key)
                ca, pairs = certificates(root, host)
                trusted = {hashlib.sha256(pairs['client'][2].public_bytes(serialization.Encoding.DER)).hexdigest(): {
                    'public_key': public, 'methods': ['community.status', 'community.checkpoint.create', 'community.checkpoint.get', 'community.checkpoint.release', 'community.event.put', 'community.blob.put'], 'providers': ['village']}}
                server = remote_server({'enabled': True, 'federation_id': 'village', 'providers': []},
                    tls_context(*pairs['server'][:2], ca, server=True), root/'replay.sqlite', trusted,
                    port=service_port, allow_mutations=True, community=CommunityEndpoint(source, private))
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                source.publish(private, 'wiki', 'home', {'title': 'Onion wiki', 'text': 'real anonymous carrier'})
                manifest = source.put_file(b'encrypted community archive')
                source.publish(private, 'files', 'archive', {'name': 'archive', **manifest})
                endpoint = {'host': host, 'port': 443, 'carrier': {'kind': 'tor-socks5', 'proxy_host': '127.0.0.1', 'proxy_port': socks_port}}
                # Fresh service descriptor publication can need a short delay.
                success = False; deadline = time.monotonic()+180
                while time.monotonic() < deadline:
                    try:
                        sync_remote(target, endpoint, tls_context(*pairs['client'][:2], ca), private, publisher=public)
                        success = True; break
                    except OSError: time.sleep(2)
                self.assertTrue(success, 'genuine onion endpoint did not complete mTLS sync')
                self.assertEqual(target.get_file(manifest), b'encrypted community archive')
                self.assertEqual(target.view('wiki'), source.view('wiki'))
            finally:
                if server: server.shutdown(); server.server_close()
                if thread: thread.join(5)
                if source: source.close()
                if target: target.close()
                process.terminate()
                try: process.wait(10)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
                reader.join(5); process.stdout.close()


if __name__ == '__main__': unittest.main()

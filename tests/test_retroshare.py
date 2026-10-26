"""Small loopback protocol tests; a fixture server is not native acceptance."""
import base64
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ziokt.protocol import ProtocolError
from ziokt.retroshare import RetroShare


class RetroShareTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ziokt-retroshare-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.auth = self.root / 'auth.json'
        self.auth.write_text(json.dumps({'username': 'ziokt', 'password': 'private-test-password'}))
        self.auth.chmod(0o600)
        self.paths = []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                owner.paths.append(self.path)
                expected = 'Basic ' + base64.b64encode(b'ziokt:private-test-password').decode()
                if self.headers.get('Authorization') != expected:
                    self.send_error(401)
                    return
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                values = {
                    '/RsJsonApi/version': {'major': 0, 'minor': 6, 'mini': 7},
                    '/rsPeers/getPeersCount': {'retval': True, 'peersCount': 2, 'onlinePeersCount': 1},
                    '/rsPeers/getFriendList': {'retval': True, 'sslIds': ['a' * 32]},
                    '/rsPeers/getOnlineList': {'retval': True, 'sslIds': ['a' * 32]},
                    '/rsFiles/getSharedDirectories': {'retval': True, 'dirs': []},
                    '/rsFiles/FileDownloads': {'hashs': ['b' * 40]},
                }
                if self.path == '/rsPeers/getPeersCount':
                    self.assert_count_locations = data == {'countLocations': True}
                body = json.dumps(values.get(self.path, {})).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.config = {'enabled': True, 'endpoint': f'http://127.0.0.1:{self.server.server_port}', 'auth_file': str(self.auth)}

    def test_authentication_and_fixed_read_only_methods(self):
        adapter = RetroShare(self.config)
        status = adapter.status()
        self.assertEqual(status['state'], 'connected')
        self.assertEqual(status['friends'], 2)
        self.assertTrue(status['native_authenticated'])
        self.assertEqual(adapter.inspect('friends')['items'], ['a' * 32])
        self.assertEqual(adapter.inspect('shares')['items'], [])
        self.assertEqual(adapter.inspect('downloads')['items'], ['b' * 40])
        with self.assertRaises(ProtocolError):
            adapter.call('../rsPeers/addFriend')
        self.assertNotIn('private-test-password', json.dumps(status))

    def test_disabled_and_unreachable_are_explicit(self):
        self.assertEqual(RetroShare().status()['state'], 'not_configured')
        self.auth.write_text(json.dumps({'username': 'ziokt', 'password': 'wrong-password'}))
        status = RetroShare(self.config).status()
        self.assertEqual(status['state'], 'unavailable')
        self.assertFalse(status['native_authenticated'])

    def test_credential_privacy_and_literal_loopback_origin(self):
        for url in ('https://example.com', 'http://localhost:9092', 'http://127.0.0.1:9092/secret',
                    'http://user:password@127.0.0.1:9092', 'http://127.0.0.1:9092?token=bad'):
            with self.assertRaises(ValueError):
                RetroShare(dict(self.config, endpoint=url))
        self.auth.chmod(0o644)
        with self.assertRaises(ProtocolError):
            RetroShare(self.config)

    def test_mcp_routes_reuse_scope_and_gateway_dispatch(self):
        from ziokt.mcp import Service
        token = self.root / 'admin-token'
        token.write_text('a' * 64)
        token.chmod(0o600)
        config = {'schema': 'ziokt.mcp.v1', 'issuer': 'https://retroshare.test', 'state': str(self.root / 'mcp'),
                  'admin_token': str(token), 'bridges': {}, 'clients': {}, 'writes_enabled': False,
                  'retroshare': self.config}
        service = Service(config)
        self.addCleanup(service.close)
        self.assertEqual(service.tools['retroshare_friends']['scope'], 'retroshare:read')
        self.assertFalse(service.tools['retroshare_friends']['annotations']['destructiveHint'])
        result = service.execute({'client': 'owner', 'scopes': {'retroshare:read'}}, 'retroshare_shares', {})
        self.assertEqual(result['kind'], 'shares')
        self.assertEqual(service.execute({}, 'retroshare_status', {})['state'], 'connected')


if __name__ == '__main__':
    unittest.main()

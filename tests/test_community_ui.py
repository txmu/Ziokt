"""Authenticated local portal, CSRF boundary, opaque downloads and safe assets."""
import http.client
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest

from ziokt.community import Community, RIGHTS, create_policy
from ziokt.community_ui import portal_server
from ziokt.security import sign


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name)
        self.private, key = secrets.token_bytes(32), secrets.token_bytes(32)
        self.public = sign({}, self.private, 'test')['public_key']
        policy = create_policy(self.private, 'village', {self.public: sorted(RIGHTS)}, privacy='private')
        self.community = Community(self.root/'community', policy, self.public, key); self.addCleanup(self.community.close)
        self.server, self.token = portal_server(self.community, self.private)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start(); self.addCleanup(self.stop)

    def stop(self): self.server.shutdown(); self.server.server_close(); self.thread.join(5)

    def request(self, path, data=None, *, token=True, origin=None, host=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        headers = {}
        if token: headers['Authorization'] = 'Bearer '+self.token
        if origin: headers['Origin'] = origin
        if host: headers['Host'] = host
        if data is not None: headers['Content-Type'] = 'application/json'
        try:
            connection.request('GET' if data is None else 'POST', path, json.dumps(data) if data is not None else None, headers)
            response = connection.getresponse(); return response.status, dict(response.getheaders()), response.read()
        finally: connection.close()

    def test_authentication_host_and_origin_boundaries(self):
        self.assertEqual(self.request('/api/status', token=False)[0], 403)
        self.assertEqual(self.request('/api/status', origin='https://attacker.example')[0], 403)
        self.assertEqual(self.request('/api/status', host='attacker.example')[0], 403)
        status, headers, raw = self.request('/api/status')
        self.assertEqual(status, 200); self.assertEqual(json.loads(raw)['community_id'], 'village')
        self.assertNotIn('Server', headers); self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])

    def test_real_publish_read_and_encrypted_checkpoint_download(self):
        body = {'domain': 'wiki', 'key': 'home', 'body': {'title': 'Wiki', 'text': '<script>alert(1)</script>'}, 'parents': None, 'deleted': False}
        self.assertEqual(self.request('/api/publish', body)[0], 200)
        status, _, raw = self.request('/api/view?domain=wiki')
        self.assertEqual(status, 200); self.assertEqual(json.loads(raw)['events'][0]['body']['text'], '<script>alert(1)</script>')
        status, headers, raw = self.request('/api/checkpoint', {})
        self.assertEqual(status, 200); self.assertEqual(headers['Content-Type'], 'application/octet-stream')
        self.assertNotIn(b'<script>', raw)
        _, _, javascript = self.request('/app.js', token=False)
        self.assertNotIn(b'innerHTML', javascript); self.assertIn(b'textContent', javascript)

    def test_file_roundtrip_and_unknown_path(self):
        import base64
        status, _, raw = self.request('/api/file-put', {'data_base64': base64.b64encode(b'archive').decode()})
        self.assertEqual(status, 200); manifest = json.loads(raw)
        self.assertEqual(self.request('/api/file-get', manifest)[2], b'archive')
        self.assertEqual(self.request('/../../owner.key')[0], 403)
        self.assertEqual(self.request('/api/file-put', {'data_base64': '!invalid'})[0], 403)


if __name__ == '__main__': unittest.main()

"""Unit tests for Unified Static Website Publishing: upload, sandboxed preview,
domain binding, atomic publish, history tracking, version rollback, and security boundaries.
"""
from pathlib import Path
import secrets
import tempfile
import unittest

from ziokt.site_publishing import SitePublisher, SANDBOXED_CSP
from ziokt.protocol import ProtocolError


class SitePublishingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.signing_key = secrets.token_bytes(32)
        self.publisher = SitePublisher(self.root, signing_key=self.signing_key)
        self.owner = 'owner-alice-pubkey'

    def test_upload_bundle_validation_and_manifest(self):
        # Missing index.html fails
        with self.assertRaises(ProtocolError) as ctx:
            self.publisher.upload({'app.js': b'console.log(1)'}, owner=self.owner)
        self.assertEqual(ctx.exception.code, 'ENTRY_MISSING')

        # Path traversal fails
        with self.assertRaises(ProtocolError) as ctx:
            self.publisher.upload({'index.html': b'<h1>Hi</h1>', '../secret.txt': b'bad'}, owner=self.owner)
        self.assertEqual(ctx.exception.code, 'PATH_TRAVERSAL')

        # Successful upload
        bundle = {
            'index.html': b'<!doctype html><html><body><h1>Hello World</h1></body></html>',
            'style.css': b'body { color: blue; }',
            'assets/app.js': b'console.log("Ready");'
        }
        rec = self.publisher.upload(bundle, owner=self.owner, title="Alice Blog", version="1.0.0")
        self.assertEqual(rec['schema'], 'ziokt.site-upload-receipt.v1')
        self.assertEqual(rec['file_count'], 3)
        self.assertTrue(rec['manifest_digest'].startswith('sha256:'))

    def test_sandboxed_preview_and_strict_csp(self):
        bundle = {
            'index.html': b'<h1>Sandboxed Content</h1>',
            'script.js': b'alert("hello");'
        }
        upload_rec = self.publisher.upload(bundle, owner=self.owner)
        preview = self.publisher.create_preview(upload_rec['manifest_digest'], owner=self.owner, ttl=300)

        self.assertIn('token', preview)
        self.assertTrue(preview['preview_url'].startswith('/preview/'))

        # Serve preview index.html
        status, headers, body = self.publisher.serve_preview(preview['token'], '')
        self.assertEqual(status, 200)
        self.assertIn(b'Sandboxed Content', body)
        self.assertEqual(headers['Content-Type'], 'text/html; charset=utf-8')
        # Crucial security verification: MUST have sandbox allow-scripts and NEVER allow-same-origin
        self.assertIn('sandbox allow-scripts', headers['Content-Security-Policy'])
        self.assertNotIn('allow-same-origin', headers['Content-Security-Policy'])
        self.assertEqual(headers['Content-Security-Policy'], SANDBOXED_CSP)

        # Serve preview script.js
        status_js, headers_js, body_js = self.publisher.serve_preview(preview['token'], 'script.js')
        self.assertEqual(status_js, 200)
        self.assertEqual(headers_js['Content-Type'], 'text/javascript')
        self.assertEqual(body_js, b'alert("hello");')

        # Missing file fails
        with self.assertRaises(ProtocolError) as ctx:
            self.publisher.serve_preview(preview['token'], 'nonexistent.png')
        self.assertEqual(ctx.exception.code, 'FILE_NOT_FOUND')

    def test_domain_publishing_and_version_rollback(self):
        domain = 'alice.corium'

        # 1. Publish v1.0.0
        b1 = {'index.html': b'<h1>Alice Site Version 1.0</h1>'}
        u1 = self.publisher.upload(b1, owner=self.owner, version='1.0.0')
        pub1 = self.publisher.publish(domain, u1['manifest_digest'], owner=self.owner, version='1.0.0')
        self.assertEqual(pub1['schema'], 'ziokt.signed.v1')
        self.assertEqual(pub1['payload']['action'], 'publish')
        self.assertEqual(pub1['payload']['version'], '1.0.0')

        st1 = self.publisher.status(domain)
        self.assertEqual(st1['status'], 'published')
        self.assertEqual(st1['version'], '1.0.0')
        self.assertFalse(st1['rollback_available'])

        # 2. Publish v2.0.0
        b2 = {'index.html': b'<h1>Alice Site Version 2.0</h1>'}
        u2 = self.publisher.upload(b2, owner=self.owner, version='2.0.0')
        pub2 = self.publisher.publish(domain, u2['manifest_digest'], owner=self.owner, version='2.0.0')
        self.assertEqual(pub2['payload']['version'], '2.0.0')
        self.assertEqual(pub2['payload']['previous_digest'], u1['manifest_digest'])

        st2 = self.publisher.status(domain)
        self.assertEqual(st2['version'], '2.0.0')
        self.assertTrue(st2['rollback_available'])

        # 3. Rollback to v1.0.0
        rb = self.publisher.rollback(domain, owner=self.owner)
        self.assertEqual(rb['payload']['action'], 'rollback')
        self.assertEqual(rb['payload']['version'], '1.0.0')
        self.assertEqual(rb['payload']['reverted_from_version'], '2.0.0')

        st3 = self.publisher.status(domain)
        self.assertEqual(st3['version'], '1.0.0')
        self.assertEqual(st3['active_manifest_digest'], u1['manifest_digest'])

        # 4. Check history log
        hist = self.publisher.history(domain)
        self.assertEqual(len(hist), 3)  # publish v1, publish v2, rollback v1
        actions = [h['action'] for h in hist]
        self.assertEqual(actions, ['rollback', 'publish', 'publish'])

    def test_permission_boundary_checks(self):
        domain = 'alice.ziokt'
        b = {'index.html': b'<h1>Original</h1>'}
        u = self.publisher.upload(b, owner=self.owner)
        self.publisher.publish(domain, u['manifest_digest'], owner=self.owner)

        # Attacker tries to publish or rollback
        attacker = 'attacker-pubkey'
        with self.assertRaises(ProtocolError) as ctx:
            self.publisher.rollback(domain, owner=attacker)
        self.assertEqual(ctx.exception.code, 'PERMISSION_DENIED')


if __name__ == '__main__':
    unittest.main()

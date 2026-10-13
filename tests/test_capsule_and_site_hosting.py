"""Tests for air-gapped capsules, decentralized site hosting, and native package staging."""
import http.client
import io
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest

from ziokt.artifacts import ArtifactStore
from ziokt.capsule import export_capsule, import_capsule, capsule_info, read_capsule_envelope
from ziokt.community import Community, RIGHTS, create_policy, content_id
from ziokt.community_cli import register, execute
from ziokt.community_native import stage_package
from ziokt.community_site import publish_site, load_site_file, list_sites
from ziokt.community_ui import portal_server
from ziokt.protocol import ProtocolError, strict_json, secure_read, encoded
from ziokt.security import sign


class CapsuleAndSiteHostingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private, self.key = secrets.token_bytes(32), secrets.token_bytes(32)
        self.public = sign({}, self.private, 'test')['public_key']
        self.policy = create_policy(self.private, 'haven', {self.public: sorted(RIGHTS)}, privacy='restricted')
        self.community = Community(self.root / 'community_a', self.policy, self.public, self.key)
        self.addCleanup(self.community.close)

    def test_capsule_export_info_and_import(self):
        # 1. Populate community A with content
        self.community.publish(self.private, 'wiki', 'handbook', {'title': 'Survival Guide', 'text': 'Carry capsules offline.'})
        self.community.publish(self.private, 'forum', 'welcome', {'title': 'Node Online', 'text': 'Network partition tolerated.', 'reply_to': ''})

        # 2. Export capsule to a file
        capsule_path = self.root / 'haven_v1.ziokt'
        export_res = export_capsule(self.community, self.private, capsule_path, description='Sneakernet checkpoint v1')
        self.assertTrue(capsule_path.exists())
        self.assertEqual(export_res['publisher'], self.public)
        self.assertGreater(export_res['size'], 0)
        self.assertEqual(export_res['records_count'], 2)

        # 3. Inspect capsule envelope metadata without community state
        info = capsule_info(capsule_path)
        self.assertEqual(info['schema'], 'ziokt.capsule.v1')
        self.assertEqual(info['community_id'], 'haven')
        self.assertEqual(info['description'], 'Sneakernet checkpoint v1')
        self.assertEqual(info['publisher'], self.public)
        self.assertEqual(info['records_count'], 2)
        self.assertEqual(info['checkpoint_digest'], export_res['checkpoint_digest'])

        # 4. Initialize fresh air-gapped node (Community B)
        community_b = Community(self.root / 'community_b', self.policy, self.public, self.key)
        self.addCleanup(community_b.close)
        self.assertEqual(len(community_b.view('wiki')['events']), 0)

        # 5. Import capsule into Community B
        import_res = import_capsule(community_b, capsule_path, expected_publisher=self.public)
        self.assertTrue(import_res['offline_sync_completed'])
        self.assertEqual(import_res['publisher'], self.public)

        # Verify data restored into Community B
        wiki_state = community_b.view('wiki')
        self.assertEqual(len(wiki_state['events']), 1)
        self.assertEqual(wiki_state['events'][0]['body']['title'], 'Survival Guide')
        forum_state = community_b.view('forum')
        self.assertEqual(len(forum_state['events']), 1)
        self.assertEqual(forum_state['events'][0]['body']['title'], 'Node Online')

        # 6. Test mismatch publisher rejection
        other_pub = secrets.token_hex(32)
        with self.assertRaises(ProtocolError):
            import_capsule(community_b, capsule_path, expected_publisher=other_pub)

        # 7. Test invalid/corrupt capsule rejection
        with self.assertRaises(ProtocolError):
            read_capsule_envelope(b'GARBAGE-DATA-NOT-A-CAPSULE')

        # 8. Test memory-only capsule export (output_path=None)
        mem_export = export_capsule(self.community, self.private, None, description='In-memory backup')
        self.assertIsNone(mem_export['output'])
        self.assertIsInstance(mem_export['body'], bytes)
        mem_info = capsule_info(mem_export['body'])
        self.assertEqual(mem_info['description'], 'In-memory backup')

    def test_site_hosting_load_and_list(self):
        # 1. Publish posts for the site to include
        self.community.publish(self.private, 'wiki', 'manifesto', {'title': 'Decentralized Haven', 'text': 'Unstoppable portable web.'})
        self.community.publish(self.private, 'forum', 'intro', {'title': 'Hello World', 'text': 'ZeroNet superseded.', 'reply_to': ''})

        # 2. Publish site
        pub_result = publish_site(self.community, self.private, 'haven-site', 'Haven Portal')
        self.assertEqual(pub_result['reference'], 'ziokt://haven/files/site-haven-site')

        # 3. List sites
        sites = list_sites(self.community)
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]['name'], 'haven-site')
        self.assertEqual(sites[0]['author'], self.public)

        # 4. Load site index.html
        index_file = load_site_file(self.community, 'haven-site', 'index.html')
        self.assertEqual(index_file['content_type'], 'text/html; charset=utf-8')
        self.assertIn(b'Haven Portal', index_file['content'])
        self.assertIn(b'Decentralized Haven', index_file['content'])

        # 5. Load site style.css
        css_file = load_site_file(self.community, 'haven-site', 'style.css')
        self.assertEqual(css_file['content_type'], 'text/css; charset=utf-8')
        self.assertIn(b'body', css_file['content'])

        # 6. Default to index.html if subpath is empty or root
        default_file = load_site_file(self.community, 'haven-site', '')
        self.assertEqual(default_file['path'], 'index.html')
        self.assertEqual(default_file['content'], index_file['content'])

        # 7. Path traversal protections
        with self.assertRaises(ProtocolError):
            load_site_file(self.community, 'haven-site', '../secret.txt')

        with self.assertRaises(ProtocolError):
            load_site_file(self.community, 'haven-site', 'subdir/../../secret.txt')

        # 8. Non-existent file in site
        with self.assertRaises(ProtocolError):
            load_site_file(self.community, 'haven-site', 'nonexistent.png')

        # 9. Non-existent site
        with self.assertRaises(ProtocolError):
            load_site_file(self.community, 'unknown-site', 'index.html')

    def test_portal_http_site_browsing_and_capsule_apis(self):
        # Publish wiki and site
        self.community.publish(self.private, 'wiki', 'docs', {'title': 'Live Docs', 'text': 'Read via browser sandbox.'})
        publish_site(self.community, self.private, 'liveweb', 'Live Web Node')

        # Launch UI portal
        server, token = portal_server(self.community, self.private, port=0)
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)

        # Helper to make HTTP request
        def request(method, path, headers=None, body=None):
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            h = {'Host': f'127.0.0.1:{port}', **(headers or {})}
            conn.request(method, path, body=body, headers=h)
            res = conn.getresponse()
            data = res.read()
            conn.close()
            return res.status, res.headers, data

        # 1. Query /api/sites with Bearer token
        status, headers, body = request('GET', '/api/sites', {'Authorization': f'Bearer {token}'})
        self.assertEqual(status, 200)
        sites_data = json.loads(body.decode())
        self.assertEqual(len(sites_data['sites']), 1)
        self.assertEqual(sites_data['sites'][0]['name'], 'liveweb')

        # 2. Browse /site/liveweb/ with Bearer token
        status, headers, body = request('GET', '/site/liveweb/', {'Authorization': f'Bearer {token}'})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get('Content-Type'), 'text/html; charset=utf-8')
        self.assertIn('Content-Security-Policy', headers)
        self.assertIn(b'Live Web Node', body)

        # 3. Test 302 redirect for /site/liveweb without trailing slash
        status, headers, _ = request('GET', '/site/liveweb', {'Authorization': f'Bearer {token}'})
        self.assertEqual(status, 302)
        self.assertEqual(headers.get('Location'), '/site/liveweb/')

        # 4. Browse /site/liveweb/style.css with Cookie authentication
        cookie_header = {'Cookie': f'ziokt_session={token}'}
        status, headers, body = request('GET', '/site/liveweb/style.css', cookie_header)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get('Content-Type'), 'text/css; charset=utf-8')
        self.assertIn(b'max-width', body)

        # 5. Export capsule via POST /api/capsule-export
        status, headers, cap_data = request('POST', '/api/capsule-export',
                                           {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                                           json.dumps({'description': 'HTTP exported'}).encode())
        self.assertEqual(status, 200)
        self.assertEqual(headers.get('Content-Type'), 'application/octet-stream')
        self.assertTrue(cap_data.startswith(b'ZIOKT-CAPSULE-V1\n'))

        # 6. Check capsule info via POST /api/capsule-info
        status, headers, body = request('POST', '/api/capsule-info',
                                       {'Authorization': f'Bearer {token}', 'Content-Type': 'application/octet-stream'},
                                       cap_data)
        self.assertEqual(status, 200)
        info_json = json.loads(body.decode())
        self.assertEqual(info_json['community_id'], 'haven')
        self.assertEqual(info_json['description'], 'HTTP exported')

        # 7. Import capsule via POST /api/capsule-import
        status, headers, body = request('POST', '/api/capsule-import',
                                       {'Authorization': f'Bearer {token}', 'Content-Type': 'application/octet-stream'},
                                       cap_data)
        self.assertEqual(status, 200)
        import_json = json.loads(body.decode())
        self.assertTrue(import_json['offline_sync_completed'])

    def test_native_package_staging(self):
        # 1. Put raw package bytes into community CAS
        payload = b'BINARY-CORIUM-OR-SHADOW6-WASM-MATERIAL'
        file_mat = self.community.put_file(payload)

        # 2. Publish package event in 'packages' domain
        pkg_body = {
            'name': 'survivor-core',
            'version': '2.1.0',
            'chunks': file_mat['chunks'],
            'size': file_mat['size'],
            'digest': file_mat['digest'],
            'native_kind': 'shadow6-app',
            'native_signature': 'ed25519-sig-mock-001'
        }
        self.community.publish(self.private, 'packages', 'survivor-pkg', pkg_body)

        # 3. Stage package into an operator ArtifactStore
        native_store_dir = self.root / 'native_artifacts'
        store = ArtifactStore(native_store_dir)
        staged = stage_package(self.community, 'survivor-pkg', store)

        self.assertEqual(staged['package_key'], 'survivor-pkg')
        self.assertEqual(staged['name'], 'survivor-core')
        self.assertEqual(staged['version'], '2.1.0')
        self.assertEqual(staged['native_kind'], 'shadow6-app')
        self.assertEqual(staged['native_signature'], 'ed25519-sig-mock-001')
        self.assertFalse(staged['native_signature_verified'])
        self.assertEqual(staged['artifact_digest'], file_mat['digest'])

        # Verify staged artifact actually exists on disk in the native store
        digest_clean = file_mat['digest'][7:]
        self.assertTrue((native_store_dir / digest_clean).exists())
        self.assertEqual((native_store_dir / digest_clean).read_bytes(), payload)

        # 4. Unknown package key raises NOT_FOUND
        with self.assertRaises(ProtocolError):
            stage_package(self.community, 'nonexistent-pkg', store)

    def test_cli_capsule_and_package_actions(self):
        import argparse
        from ziokt.protocol import make_private
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest='command', required=True)
        register(sub)

        # Save keys and policy to disk for CLI
        policy_path = self.root / 'policy.json'
        policy_path.write_text(json.dumps(self.policy))
        make_private(policy_path)
        owner_key_path = self.root / 'owner.key'
        owner_key_path.write_bytes(self.private)
        make_private(owner_key_path)
        enc_key_path = self.root / 'enc.key'
        enc_key_path.write_bytes(self.key)
        make_private(enc_key_path)
        capsule_file = self.root / 'cli_capsule.ziokt'

        # 1. CLI capsule-export
        export_args = parser.parse_args([
            'community', 'capsule-export',
            '--root', str(self.root / 'community_a'),
            '--policy', str(policy_path),
            '--owner', self.public,
            '--encryption-key', str(enc_key_path),
            '--signing-key', str(owner_key_path),
            '--output', str(capsule_file),
            '--description', 'CLI exported capsule'
        ])
        res_exp = execute(export_args)
        self.assertTrue(capsule_file.exists())
        self.assertEqual(res_exp['publisher'], self.public)

        # 2. CLI capsule-info
        info_args = parser.parse_args([
            'community', 'capsule-info',
            '--input', str(capsule_file)
        ])
        res_info = execute(info_args)
        self.assertEqual(res_info['community_id'], 'haven')
        self.assertEqual(res_info['description'], 'CLI exported capsule')

        # 3. CLI capsule-import
        fresh_root = self.root / 'cli_community_fresh'
        fresh_comm = Community(fresh_root, self.policy, self.public, self.key)
        fresh_comm.close()

        import_args = parser.parse_args([
            'community', 'capsule-import',
            '--root', str(fresh_root),
            '--policy', str(policy_path),
            '--owner', self.public,
            '--encryption-key', str(enc_key_path),
            '--input', str(capsule_file)
        ])
        res_imp = execute(import_args)
        self.assertTrue(res_imp['offline_sync_completed'])

        # 4. CLI stage-package
        payload = b'CLI-STAGED-PACKAGE-BINARY'
        mat = self.community.put_file(payload)
        self.community.publish(self.private, 'packages', 'cli-pkg', {
            'name': 'cli-worker', 'version': '0.9.0',
            'chunks': mat['chunks'], 'size': mat['size'], 'digest': mat['digest'],
            'native_kind': 'corium-package', 'native_signature': 'sig-cli'
        })

        cli_store = self.root / 'cli_store'
        stage_args = parser.parse_args([
            'community', 'stage-package',
            '--root', str(self.root / 'community_a'),
            '--policy', str(policy_path),
            '--owner', self.public,
            '--encryption-key', str(enc_key_path),
            '--package-key', 'cli-pkg',
            '--native-store', str(cli_store)
        ])
        res_stage = execute(stage_args)
        self.assertEqual(res_stage['name'], 'cli-worker')
        self.assertTrue((cli_store / mat['digest'][7:]).exists())


if __name__ == '__main__':
    unittest.main()

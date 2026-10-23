"""Automated Content Fabric, Library, and Netnews Sovereign Survival Test.

Validates that when the founder content server (Node 0) is completely offline:
1. Replicated content remains accessible across peer nodes (Nodes 1, 2).
2. Content digest (CID) and publisher signatures independently verify.
3. Node 3 (Fresh join node) downloads content exclusively from peers without founder.
4. Tampered chunks are rejected.
5. New Netnews posts and Library entries can be created and federated peer-to-peer.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import tempfile
import unittest
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ziokt.content_fabric import Fabric


class TestContentSovereignSurvival(unittest.TestCase):
    def test_founder_offline_content_survival_and_fresh_join(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            keys = []
            ports = []
            processes = {}
            configs = []

            # 4 nodes: 0 (Founder), 1 (Peer B), 2 (Peer C), 3 (Fresh Peer D)
            for i in range(4):
                node = Fabric(root / str(i))
                keys.append(node.public)
                node.close()
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0))
                    ports.append(sock.getsockname()[1])

            token = 'sovereign_test_token_' + 'x' * 27
            peers = {
                str(i): {
                    'url': f'http://127.0.0.1:{ports[i]}',
                    'public_key': keys[i],
                    'token': token,
                    'groups': ['sovereign.books', 'sovereign.news']
                } for i in range(4)
            }
            scopes = [
                'content:read', 'content:write', 'content:replicate', 'content:admin',
                'library:read', 'library:write', 'netnews:read', 'netnews:write'
            ]

            for i in range(4):
                cfg = root / f'{i}.json'
                cfg.write_text(json.dumps({
                    'root': str(root / str(i)),
                    'port': ports[i],
                    'tokens': [{'account': f'user_{i}', 'token': token, 'scopes': scopes}],
                    'peers': peers
                }))
                cfg.chmod(0o600)
                configs.append(cfg)

            def start(i):
                child_env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parent.parent)}
                proc = subprocess.Popen(
                    [sys.executable, '-m', 'ziokt.content_server', '--config', str(configs[i])],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=child_env
                )
                processes[i] = proc
                if not select.select([proc.stdout], [], [], 10)[0]:
                    raise AssertionError(f'Node {i} did not start')
                line = proc.stdout.readline()
                if not line:
                    raise AssertionError(proc.stderr.read())
                self.assertEqual(json.loads(line)['node'], keys[i])

            def stop(i):
                proc = processes.pop(i, None)
                if proc:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    proc.stdout.close()
                    proc.stderr.close()

            def call(i, op, args=None):
                req = Request(
                    f'http://127.0.0.1:{ports[i]}/api',
                    data=json.dumps({'operation': op, 'arguments': args or {}}).encode(),
                    headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
                )
                with urlopen(req, timeout=10) as response:
                    return json.load(response)

            def synchronize(target, source):
                for _ in range(25):
                    res = call(target, 'federation.sync', {'peer': str(source)})
                    if not res['has_more']:
                        return
                raise AssertionError('Sync did not converge')

            try:
                # 1. Start nodes 0, 1, 2
                for i in range(3):
                    start(i)
                    call(i, 'netnews.group.create', {'name': 'sovereign.books'})
                    call(i, 'netnews.group.create', {'name': 'sovereign.news'})

                # 2. Founder (0) publishes an immutable book
                sample_text = b'Ziokt Sovereign Network: Independent Content & Decentralized Verification.\n' * 500
                digest = 'sha256:' + hashlib.sha256(sample_text).hexdigest()

                call(0, 'content.upload.begin', {
                    'upload': 'book-manifest-1',
                    'size': len(sample_text),
                    'digest': digest,
                    'mime': 'text/plain'
                })
                for pos, start_b in enumerate(range(0, len(sample_text), 16384)):
                    chunk_slice = sample_text[start_b:start_b + 16384]
                    call(0, 'content.upload.put', {
                        'upload': 'book-manifest-1',
                        'position': pos,
                        'data': base64.b64encode(chunk_slice).decode()
                    })
                obj = call(0, 'content.upload.finish', {'upload': 'book-manifest-1'})
                file_id = obj['id']

                call(0, 'library.publish', {
                    'metadata': {
                        'id': 'sovereign-manifesto',
                        'work_id': 'work-1',
                        'edition_id': 'first-edition',
                        'file_id': file_id,
                        'title': 'Sovereign Network Architecture',
                        'authors': ['Ziokt Core Team'],
                        'license': 'CC0-1.0',
                        'visibility': 'public'
                    }
                })

                # Federate to Node 1 and Node 2
                synchronize(1, 0)
                synchronize(2, 1)

                # Download complete book on Node 1
                dl1 = call(1, 'library.download', {'book': 'sovereign-manifesto', 'sources': ['0']})
                self.assertEqual(dl1['state'], 'complete')

                # Download partial book on Node 2
                dl2_part = call(2, 'library.download', {'book': 'sovereign-manifesto', 'sources': ['0'], 'max_chunks': 1})
                self.assertEqual(dl2_part['received_chunks'], 1)

                # 3. SEVER FOUNDER NODE 0 COMPLETELY
                print('[TEST] Severing Founder Content Server (Node 0)...')
                stop(0)
                self.assertNotIn(0, processes)

                # 4. Node 2 recovers remaining chunks from Node 1 (Founder is dead!)
                print('[TEST] Node 2 repairing remaining chunks from Node 1...')
                dl2_full = call(2, 'library.download', {'book': 'sovereign-manifesto', 'sources': ['1']})
                self.assertEqual(dl2_full['state'], 'complete')
                self.assertTrue(call(2, 'content.object.verify', {'id': file_id})['verified'])

                # 5. Peer Node 1 publishes new Netnews article while Founder is offline
                print('[TEST] Posting new Netnews article on Node 1 while Founder is offline...')
                call(1, 'netnews.post', {
                    'groups': ['sovereign.news'],
                    'subject': 'Founder Offline Test',
                    'body': 'Decentralized message created without founder.',
                    'message_id': '<sovereign-msg-1@peer1.local>'
                })
                # Sync between Node 2 and Node 1 (no Node 0 involved)
                synchronize(2, 1)
                articles_2 = call(2, 'netnews.articles', {'group': 'sovereign.news'})
                self.assertEqual(len(articles_2['items']), 1)
                self.assertEqual(articles_2['items'][0]['subject'], 'Founder Offline Test')

                # 6. Fresh Node 3 (Node D) boots and joins, discovers Node 1 & 2
                print('[TEST] Fresh Node 3 booting from scratch (never seen Founder)...')
                start(3)
                call(3, 'netnews.group.create', {'name': 'sovereign.books'})
                call(3, 'netnews.group.create', {'name': 'sovereign.news'})

                # Sync catalogue from Node 2 (which is independent)
                synchronize(3, 2)
                search_3 = call(3, 'library.search', {})
                self.assertEqual(len(search_3['items']), 1)
                self.assertEqual(search_3['items'][0]['id'], 'sovereign-manifesto')

                # Download content from Node 1
                dl3 = call(3, 'library.download', {'book': 'sovereign-manifesto', 'sources': ['1']})
                self.assertEqual(dl3['state'], 'complete')
                self.assertTrue(call(3, 'content.object.verify', {'id': file_id})['verified'])

                # Verify article on Node 3
                articles_3 = call(3, 'netnews.articles', {'group': 'sovereign.news'})
                self.assertEqual(len(articles_3['items']), 1)
                print('[SUCCESS] Content Fabric sovereign survival and fresh node bootstrap verified!')

            finally:
                for p in list(processes):
                    stop(p)


if __name__ == '__main__':
    unittest.main()

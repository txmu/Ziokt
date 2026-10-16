"""Exercise the native legacy DCPM implementation, without optional network backends."""
import asyncio
import base64
import contextlib
import hashlib
import http.server
import sqlite3
import subprocess
import threading
from urllib.parse import urlsplit, parse_qs
import json
import os
import pickle
from pathlib import Path
import sys
import tempfile
import unittest
import zlib

SOURCE = Path(__file__).resolve().parents[1] / 'companions/ufsdcpm/src'
sys.path.insert(0, str(SOURCE))
from dcpm_safe import parse_metadata, safe_pickle, decompress_pickle, read_blocks, MAX_BYTES
import dcpm_core
from dcpm_core import Package, DHTNode, get_version_id
from dcpm_poolmemory import Memory


@contextlib.contextmanager
def real_dht_endpoint():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / 'dht.sqlite'
        with contextlib.closing(sqlite3.connect(database)) as db, db:
            db.execute('CREATE TABLE objects (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                url = urlsplit(self.path); query = parse_qs(url.query)
                with contextlib.closing(sqlite3.connect(database)) as db, db:
                    if url.path == '/put':
                        db.execute('INSERT OR REPLACE INTO objects VALUES (?,?)', (query['key'][0], query['value'][0])); result = 'stored'
                    elif url.path == '/get':
                        row = db.execute('SELECT value FROM objects WHERE key=?', (query['key'][0],)).fetchone(); result = row[0] if row else ''
                    else:
                        self.send_error(404); return
                self.send_response(200); self.end_headers(); self.wfile.write(result.encode())
            def log_message(self, *args): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        previous = dcpm_core.CURRENT_NETWORK.dht_nodes; url = f'http://127.0.0.1:{server.server_port}'
        dcpm_core.CURRENT_NETWORK.set_dht_nodes([url])
        try: yield url, Path(directory)
        finally:
            dcpm_core.CURRENT_NETWORK.set_dht_nodes(previous); server.shutdown(); server.server_close(); thread.join()


class NativeDcpmSecurityTests(unittest.TestCase):
    def test_real_package_roundtrip_revalidates_checksum(self):
        package = Package('test', '1.0', {'safe/file': b'actual bytes'}, 'dpkg')
        self.assertEqual(Package.from_bytes(package.to_bytes()).files, package.files)
        data = safe_pickle(package.to_bytes()); data['files']['safe/file'] = b'tampered'
        with self.assertRaisesRegex(ValueError, 'CHECKSUM'):
            Package.from_bytes(pickle.dumps(data))
        for path in ['../escape', '/absolute', 'C:/outside', 'file:alternate']:
            data['files'] = {path: b'x'}
            with self.assertRaisesRegex(ValueError, 'UNSAFE_PATH'):
                Package.from_bytes(pickle.dumps(data))

    def test_executable_pickle_is_rejected_without_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'executed'
            class Attack:
                def __reduce__(self): return os.system, ('touch ' + str(marker),)
            payload = pickle.dumps(Attack())
            with self.assertRaisesRegex(ValueError, 'EXECUTABLE'):
                safe_pickle(payload)
            with self.assertRaisesRegex(ValueError, 'EXECUTABLE'):
                Package.from_bytes(payload)
            with self.assertRaisesRegex(ValueError, 'EXECUTABLE'):
                Memory(1).decompress(zlib.compress(payload))
            self.assertFalse(marker.exists())

    def test_metadata_accepts_inert_legacy_checksum_not_code(self):
        text = "{'checksums': {'a': FileChecksum(md5='m', sha1='s', sha256='h', crc32='c')}}"
        self.assertEqual(parse_metadata(text)['checksums']['a'], ('m', 's', 'h', 'c'))
        for text in ["__import__('os').system('false')", "{'x': (lambda: 1)()}", "{'x': FileChecksum(*[])}"]:
            with self.assertRaises((ValueError, SyntaxError)):
                parse_metadata(text)

    def test_decompression_bound_and_corruption(self):
        memory = Memory(1)
        self.assertEqual(memory.decompress(memory.compress({'bytes': b'hello'})), {'bytes': b'hello'})
        for payload in [zlib.compress(b'x' * (MAX_BYTES + 1)), zlib.compress(pickle.dumps({}))[:-1], zlib.compress(pickle.dumps({})) + b'trailing']:
            with self.assertRaises(ValueError): memory.decompress(payload)

    def test_remote_install_and_uninstall_require_local_authorization(self):
        package = Package('test', '1', {'test.deb': b'bytes'}, 'dpkg')
        with self.assertRaises(PermissionError): asyncio.run(package.install())
        with self.assertRaises(PermissionError): asyncio.run(Package.uninstall('test;echo malicious'))
        with self.assertRaisesRegex(ValueError, 'UNSAFE_PACKAGE_NAME'):
            asyncio.run(Package.uninstall('test;echo malicious', package_manager='dpkg', allow_system_install=True))
        package.files = {'../../escape.deb': b'bytes'}
        with self.assertRaisesRegex(ValueError, 'UNSAFE_PATH'):
            asyncio.run(package.install(allow_system_install=True))

    @unittest.skipUnless(os.name == 'posix', 'fixture executable requires POSIX shebang support')
    def test_installer_uses_real_argv_and_checks_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); binary = root / 'dpkg'; log = root / 'argv.json'
            binary.write_text('#!/usr/bin/python3\nimport json,sys\nfrom pathlib import Path\np=Path(' + repr(str(log)) + ')\np.write_text(json.dumps(sys.argv))\nsys.exit(7 if p.with_suffix(".fail").exists() else 0)\n')
            binary.chmod(0o700)
            previous = os.environ['PATH']; os.environ['PATH'] = directory
            try:
                package = Package('test', '1', {'a;touch malicious.deb': b'bytes'}, 'dpkg')
                self.assertTrue(asyncio.run(package.install(allow_system_install=True)))
                args = json.loads(log.read_text())
                self.assertEqual(args[1:3], ['--install', '--'])
                self.assertEqual(Path(args[3]).name, 'a;touch malicious.deb')
                self.assertFalse(Path(args[3]).exists())
                log.with_suffix('.fail').touch()
                with self.assertRaisesRegex(RuntimeError, 'INSTALL_FAILED:7'):
                    asyncio.run(package.install(allow_system_install=True))
            finally:
                os.environ['PATH'] = previous

    def test_signed_native_publish_download_and_new_process(self):
        from ziokt.security import sign
        with real_dht_endpoint() as (url, directory):
            key = directory / 'publisher.key'; key.write_bytes(os.urandom(32)); key.chmod(0o600)
            public = sign({}, key.read_bytes(), 'test')['public_key']
            package = Package('published', '1', {'safe/file': b'signed real payload'}, 'dpkg')
            result = asyncio.run(package.publish(signing_key=key))
            receiver = Package('published', '1', {}, 'rpm')
            self.assertIs(asyncio.run(receiver.download(authority=public)), receiver)
            self.assertEqual(receiver.files, package.files)
            self.assertEqual(receiver.package_manager, 'rpm')  # chosen locally, not by publisher
            script = "from dcpm_core import Package; import asyncio; p=Package('published','1',{},'dpkg'); asyncio.run(p.download()); print(p.files['safe/file'].decode())"
            env = {**os.environ, 'PYTHONPATH': str(SOURCE) + os.pathsep + str(SOURCE.parents[2]), 'ZIOKT_DCPM_DHT_NODES': json.dumps([url]), 'ZIOKT_DCPM_PUBLISHER_PUBLIC_KEY': public}
            reopened = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(reopened.returncode, 0, reopened.stderr)
            self.assertEqual(reopened.stdout.strip(), 'signed real payload')
            with self.assertRaises(Exception):
                asyncio.run(Package('published','1',{},'dpkg').download(authority='0'*64))
            with self.assertRaisesRegex(ValueError, 'UNSIGNED_METADATA'):
                asyncio.run(Package('published','2',{},'dpkg').download(authority=public))
            node = DHTNode(url)
            version_id=get_version_id('published',public,'1')
            original=asyncio.run(node.get(version_id))
            data=json.loads(base64.b64decode(original.split(':',1)[1])); data['manifest']['signature']='0'*128
            asyncio.run(node.put(version_id,'ziokt.dcpm-package.v1:'+base64.b64encode(json.dumps(data).encode()).decode()))
            from ziokt.protocol import ProtocolError
            with self.assertRaises(ProtocolError): asyncio.run(receiver.download(authority=public))
            asyncio.run(node.put(version_id, "{'signature': b'legacy'}"))
            with self.assertRaisesRegex(ValueError, 'UNSIGNED_METADATA'):
                asyncio.run(receiver.download(authority=public))

    def test_real_block_transport_order_retry_cache_and_integrity(self):
        with real_dht_endpoint() as (url, _):
            node = DHTNode(url); first=b'first'; second=b'second'
            a=hashlib.sha256(first).hexdigest(); b=hashlib.sha256(second).hexdigest()
            asyncio.run(node.put(a, first)); cache={}
            with self.assertRaises(LookupError): asyncio.run(read_blocks(node,[a,b],cache))
            self.assertEqual(cache[a], first)
            asyncio.run(node.put(b, second))
            self.assertEqual(asyncio.run(read_blocks(node,[b,a,b],cache)), b'secondfirstsecond')
            self.assertEqual(cache[b], second)
            cache.clear(); asyncio.run(node.put(a,b'tampered'))
            with self.assertRaisesRegex(ValueError,'BLOCK_INTEGRITY'): asyncio.run(read_blocks(node,[a],cache))
            self.assertNotIn(a,cache)

    def test_unconfigured_network_is_not_success(self):
        previous=dcpm_core.CURRENT_NETWORK.dht_nodes; dcpm_core.CURRENT_NETWORK.set_dht_nodes([])
        try:
            with self.assertRaisesRegex(RuntimeError,'DHT_NOT_CONFIGURED'): asyncio.run(dcpm_core.put_metadata('key','value'))
            with self.assertRaisesRegex(RuntimeError,'DHT_NOT_CONFIGURED'): asyncio.run(dcpm_core.get_metadata('key'))
        finally: dcpm_core.CURRENT_NETWORK.set_dht_nodes(previous)

    def test_native_dht_respects_airgap_before_network(self):
        previous=os.environ.get('ZIOKT_AIRGAP'); os.environ['ZIOKT_AIRGAP']='1'
        try:
            with self.assertRaisesRegex(PermissionError,'AIRGAP_DENIED'):
                asyncio.run(DHTNode('https://must-not-resolve.invalid').get('key'))
        finally:
            if previous is None: os.environ.pop('ZIOKT_AIRGAP',None)
            else: os.environ['ZIOKT_AIRGAP']=previous


if __name__ == '__main__': unittest.main()

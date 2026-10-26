"""Unit tests for Unified Package Lifecycle: SemVer resolution, DAG topological sorting,
cycle detection, authorization, isolated slots, atomic upgrades, rollbacks, uninstalls, and auto-repair.
"""
import hashlib
import secrets
from pathlib import Path
import tempfile
import unittest

from ziokt.package_lifecycle import (
    parse_semver, compare_semver, matches_constraint, resolve_dependencies,
    PackageManager, PACKAGE_DOMAIN
)
from ziokt.protocol import ProtocolError
from ziokt.security import sign


class PackageLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key=secrets.token_bytes(32)
        self.public=sign({},self.key,PACKAGE_DOMAIN)['public_key']
        self.allowlist={self.public}
        self.mgr = PackageManager(self.root, allowlist=self.allowlist)

    def signed(self, manifest):
        return sign(manifest,self.key,PACKAGE_DOMAIN)

    def test_semver_parsing_and_matching(self):
        self.assertEqual(parse_semver('1.2.3'), (1, 2, 3, ''))
        self.assertEqual(parse_semver('2.0.0-rc1'), (2, 0, 0, 'rc1'))
        with self.assertRaises(ProtocolError):
            parse_semver('invalid-version')

        self.assertEqual(compare_semver('1.0.0', '1.0.1'), -1)
        self.assertEqual(compare_semver('2.1.0', '2.0.9'), 1)
        self.assertEqual(compare_semver('1.5.0', '1.5.0'), 0)

        # Constraints
        self.assertTrue(matches_constraint('1.2.3', '*'))
        self.assertTrue(matches_constraint('1.2.3', '>=1.0.0'))
        self.assertTrue(matches_constraint('1.2.3', '>=1.0.0, <2.0.0'))
        self.assertFalse(matches_constraint('2.0.0', '>=1.0.0, <2.0.0'))
        self.assertTrue(matches_constraint('1.5.2', '^1.2.0'))
        self.assertFalse(matches_constraint('2.0.0', '^1.2.0'))
        self.assertTrue(matches_constraint('1.2.8', '~1.2.0'))
        self.assertFalse(matches_constraint('1.3.0', '~1.2.0'))

    def test_dependency_resolution_and_cycle_detection(self):
        registry = {
            'core': [
                {'name': 'core', 'version': '1.0.0', 'dependencies': {}},
                {'name': 'core', 'version': '1.2.0', 'dependencies': {}},
            ],
            'utils': [
                {'name': 'utils', 'version': '1.0.0', 'dependencies': {'core': '^1.0.0'}}
            ],
            'app': [
                {'name': 'app', 'version': '1.0.0', 'dependencies': {'utils': '>=1.0.0', 'core': '^1.0.0'}}
            ]
        }
        # Successful DAG resolution
        resolved = resolve_dependencies([('app', '^1.0.0')], registry)
        names = [p['name'] for p in resolved]
        self.assertEqual(names, ['core', 'utils', 'app'])
        self.assertEqual(resolved[0]['version'], '1.2.0')  # highest satisfying ^1.0.0

        # Cycle detection
        cyclic_registry = {
            'pkgA': [{'name': 'pkgA', 'version': '1.0.0', 'dependencies': {'pkgB': '*'}}],
            'pkgB': [{'name': 'pkgB', 'version': '1.0.0', 'dependencies': {'pkgA': '*'}}],
        }
        with self.assertRaises(ProtocolError) as ctx:
            resolve_dependencies([('pkgA', '*')], cyclic_registry)
        self.assertEqual(ctx.exception.code, 'CYCLIC_DEPENDENCY')

    def test_package_authorization_and_integrity(self):
        content = b'print("hello")\n'
        c_hash = hashlib.sha256(content).hexdigest()
        manifest = {
            'schema': 'ziokt.package.v1',
            'name': 'test-lib',
            'version': '1.0.0',
            'publisher': 'untrusted-pub',
            'files': {'main.py': c_hash}
        }
        files = {'main.py': content}

        # Untrusted publisher rejected
        with self.assertRaises(ProtocolError) as ctx:
            self.mgr.authorize_package(self.signed(manifest), files, publisher='untrusted-pub')
        self.assertEqual(ctx.exception.code, 'UNAUTHORIZED_PUBLISHER')

        # File hash mismatch rejected
        manifest['publisher'] = self.public
        bad_files = {'main.py': b'corrupted data'}
        with self.assertRaises(ProtocolError) as ctx:
            self.mgr.authorize_package(self.signed(manifest), bad_files, publisher=self.public)
        self.assertEqual(ctx.exception.code, 'PACKAGE_INTEGRITY')

        # Authorized successfully
        auth = self.mgr.authorize_package(self.signed(manifest), files, publisher=self.public)
        self.assertTrue(auth['authorized'])

    def test_install_upgrade_and_rollback_lifecycle(self):
        f1_data = b'# v1.0.0 source\n'
        f1_hash = hashlib.sha256(f1_data).hexdigest()
        m1 = {
            'schema': 'ziokt.package.v1',
            'name': 'webapp',
            'version': '1.0.0',
            'publisher': self.public,
            'files': {'index.js': f1_hash}
        }
        files_v1 = {'index.js': f1_data}

        # 1. Install v1.0.0
        rec1 = self.mgr.install(self.signed(m1), files_v1, publisher=self.public)
        self.assertEqual(rec1['action'], 'install')
        self.assertEqual(rec1['version'], '1.0.0')
        active1 = self.mgr.get('webapp')
        self.assertEqual(active1['version'], '1.0.0')
        self.assertEqual(active1['status'], 'active')

        # 2. Upgrade to v1.1.0
        f2_data = b'# v1.1.0 source with new feature\n'
        f2_hash = hashlib.sha256(f2_data).hexdigest()
        m2 = {
            'schema': 'ziokt.package.v1',
            'name': 'webapp',
            'version': '1.1.0',
            'publisher': self.public,
            'files': {'index.js': f2_hash}
        }
        files_v2 = {'index.js': f2_data}

        rec2 = self.mgr.upgrade(self.signed(m2), files_v2, publisher=self.public)
        self.assertEqual(rec2['action'], 'upgrade')
        self.assertEqual(rec2['version'], '1.1.0')
        self.assertEqual(rec2['previous_version'], '1.0.0')

        active2 = self.mgr.get('webapp')
        self.assertEqual(active2['version'], '1.1.0')
        self.assertEqual(active2['previous_version'], '1.0.0')

        # Verify active slot has v1.1.0 content
        active_content = (Path(active2['slot_path']) / 'index.js').read_bytes()
        self.assertEqual(active_content, f2_data)

        # 3. Rollback to v1.0.0
        rec3 = self.mgr.rollback('webapp')
        self.assertEqual(rec3['action'], 'rollback')
        self.assertEqual(rec3['version'], '1.0.0')

        active3 = self.mgr.get('webapp')
        self.assertEqual(active3['version'], '1.0.0')
        self.assertTrue(self.mgr.verify_integrity('webapp')['healthy'])
        rolled_content = (Path(active3['slot_path']) / 'index.js').read_bytes()
        self.assertEqual(rolled_content, f1_data)

    def test_uninstall_with_reverse_dependency_guard(self):
        # Install libA
        fA = b'# libA\n'
        mA = {'schema': 'ziokt.package.v1', 'name': 'libA', 'version': '1.0.0', 'publisher': self.public, 'files': {'lib.js': hashlib.sha256(fA).hexdigest()}}
        self.mgr.install(self.signed(mA), {'lib.js': fA}, publisher=self.public)

        # Install appB depending on libA
        fB = b'# appB\n'
        mB = {
            'schema': 'ziokt.package.v1',
            'name': 'appB',
            'version': '1.0.0',
            'publisher': self.public,
            'dependencies': {'libA': '^1.0.0'},
            'files': {'app.js': hashlib.sha256(fB).hexdigest()}
        }
        self.mgr.install(self.signed(mB), {'app.js': fB}, publisher=self.public)

        # Cannot uninstall libA while appB is active
        with self.assertRaises(ProtocolError) as ctx:
            self.mgr.uninstall('libA')
        self.assertEqual(ctx.exception.code, 'DEPENDENCY_CONFLICT')

        # Uninstall appB first
        rec_un_b = self.mgr.uninstall('appB')
        self.assertEqual(rec_un_b['status'], 'uninstalled')

        # Now libA can be uninstalled cleanly
        rec_un_a = self.mgr.uninstall('libA')
        self.assertEqual(rec_un_a['status'], 'uninstalled')

    def test_fault_detection_and_auto_repair(self):
        f_data = b'# perfect pristine file\n'
        f_hash = hashlib.sha256(f_data).hexdigest()
        m = {'schema': 'ziokt.package.v1', 'name': 'fragile', 'version': '1.0.0', 'publisher': self.public, 'files': {'core.bin': f_hash}}
        self.mgr.install(self.signed(m), {'core.bin': f_data}, publisher=self.public)

        # Integrity passes initially
        audit1 = self.mgr.verify_integrity('fragile')
        self.assertTrue(audit1['healthy'])

        # Simulate file corruption (e.g. disk bitrot or manual tamper)
        slot_file = Path(self.mgr.get('fragile')['slot_path']) / 'core.bin'
        slot_file.write_bytes(b'tampered broken bits')

        audit2 = self.mgr.verify_integrity('fragile')
        self.assertFalse(audit2['healthy'])
        self.assertEqual(audit2['corrupted_files'], ['core.bin'])

        # Auto repair from source
        repair_res = self.mgr.auto_repair('fragile', clean_source_files={'core.bin': f_data})
        self.assertTrue(repair_res['repaired'])
        self.assertEqual(repair_res['restored_files'], ['core.bin'])

        # Audit passes again
        audit3 = self.mgr.verify_integrity('fragile')
        self.assertTrue(audit3['healthy'])


if __name__ == '__main__':
    unittest.main()

"""Unified Package Lifecycle Management: resolution, authorization, install, upgrade, rollback, uninstall, and auto-repair."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time

from .protocol import ProtocolError, encoded, secure_read, strict_json
from .security import verify, sign

PACKAGE_DOMAIN = 'Ziokt/package-lifecycle/v1'

VERSION_RE = re.compile(r'^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$')
ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}\Z')


def parse_semver(v_str):
    if not isinstance(v_str, str):
        raise ProtocolError('INVALID_VERSION', 'version string required')
    m = VERSION_RE.match(v_str.strip())
    if not m:
        raise ProtocolError('INVALID_VERSION', f'canonical semver required: {v_str}')
    major, minor, patch, pre = m.groups()
    return int(major), int(minor), int(patch), pre or ''


def compare_semver(v1_str, v2_str):
    maj1, min1, pat1, pre1 = parse_semver(v1_str)
    maj2, min2, pat2, pre2 = parse_semver(v2_str)
    t1 = (maj1, min1, pat1)
    t2 = (maj2, min2, pat2)
    if t1 < t2:
        return -1
    if t1 > t2:
        return 1
    if not pre1 and pre2:
        return 1
    if pre1 and not pre2:
        return -1
    if pre1 < pre2:
        return -1
    if pre1 > pre2:
        return 1
    return 0


def matches_constraint(version_str, constraint_str):
    """Check if version satisfies constraint expression."""
    c = constraint_str.strip() if isinstance(constraint_str, str) else '*'
    if c in {'*', '', 'any', 'latest'}:
        return True

    # Comma-separated constraints (e.g. ">=1.0.0, <2.0.0")
    if ',' in c:
        return all(matches_constraint(version_str, part.strip()) for part in c.split(','))

    v = parse_semver(version_str)
    # Caret constraint: ^1.2.3 -> >=1.2.3, <2.0.0 (or ^0.2.3 -> >=0.2.3, <0.3.0)
    if c.startswith('^'):
        target = parse_semver(c[1:])
        if compare_semver(version_str, c[1:]) < 0:
            return False
        if target[0] > 0:
            return v[0] == target[0]
        elif target[1] > 0:
            return v[0] == 0 and v[1] == target[1]
        else:
            return v == target

    # Tilde constraint: ~1.2.3 -> >=1.2.3, <1.3.0
    if c.startswith('~'):
        target = parse_semver(c[1:])
        if compare_semver(version_str, c[1:]) < 0:
            return False
        return v[0] == target[0] and v[1] == target[1]

    # Relational constraints: >=, <=, >, <, ==, =
    for op, comp in [
        ('>=', lambda x, y: compare_semver(x, y) >= 0),
        ('<=', lambda x, y: compare_semver(x, y) <= 0),
        ('>',  lambda x, y: compare_semver(x, y) > 0),
        ('<',  lambda x, y: compare_semver(x, y) < 0),
        ('==', lambda x, y: compare_semver(x, y) == 0),
        ('=',  lambda x, y: compare_semver(x, y) == 0),
    ]:
        if c.startswith(op):
            target_str = c[len(op):].strip()
            return comp(version_str, target_str)

    # Exact match
    return compare_semver(version_str, c) == 0


def resolve_dependencies(root_packages, registry):
    """Dependency resolver with SemVer constraints, cycle detection, and topological ordering.

    root_packages: list of (package_name, version_constraint)
    registry: mapping or callable name -> list of available package dicts
    Returns ordered list of packages to install.
    """
    resolved = {}
    visiting = set()
    order = []

    def get_versions(pkg_name):
        if callable(registry):
            return registry(pkg_name)
        return registry.get(pkg_name, [])

    def select_best(pkg_name, constraint):
        available = get_versions(pkg_name)
        candidates = [p for p in available if matches_constraint(p['version'], constraint)]
        if not candidates:
            raise ProtocolError(
                'UNSATISFIABLE_DEPENDENCY',
                f'no available version of {pkg_name} satisfies constraint "{constraint}"'
            )
        # Choose highest version satisfying constraint
        candidates.sort(key=lambda p: parse_semver(p['version']))
        return candidates[-1]

    def visit(pkg_name, constraint, path):
        if pkg_name in visiting:
            cycle = path + [pkg_name]
            raise ProtocolError('CYCLIC_DEPENDENCY', f'cycle detected: {" -> ".join(cycle)}')

        if pkg_name in resolved:
            existing = resolved[pkg_name]
            if not matches_constraint(existing['version'], constraint):
                raise ProtocolError(
                    'VERSION_CONFLICT',
                    f'package {pkg_name}@{existing["version"]} conflicts with required constraint "{constraint}"'
                )
            return

        visiting.add(pkg_name)
        best = select_best(pkg_name, constraint)
        resolved[pkg_name] = best

        deps = best.get('dependencies', {})
        for dep_name, dep_constraint in deps.items():
            visit(dep_name, dep_constraint, path + [pkg_name])

        visiting.remove(pkg_name)
        if best not in order:
            order.append(best)

    for name, constraint in root_packages:
        visit(name, constraint, [])

    return order


class PackageManager:
    """Production-grade package lifecycle manager."""

    def __init__(self, root_dir, allowlist=None, registry=None):
        self.root = Path(root_dir)
        self.slots_dir = self.root / 'slots'
        self.active_dir = self.root / 'active'
        self.db_path = self.root / 'packages.db'
        self.allowlist = set(allowlist) if allowlist else set()
        self.registry = registry or {}
        self.slots_dir.mkdir(parents=True, exist_ok=True)
        self.active_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn as db:
                db.execute('''
                    CREATE TABLE IF NOT EXISTS packages (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        version TEXT NOT NULL,
                        previous_version TEXT,
                        publisher TEXT NOT NULL,
                        installed_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        slot_path TEXT NOT NULL,
                        manifest TEXT NOT NULL,
                        files_manifest TEXT NOT NULL
                    )
                ''')
                db.execute('''
                    CREATE TABLE IF NOT EXISTS package_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        package_name TEXT NOT NULL,
                        version TEXT NOT NULL,
                        action TEXT NOT NULL,
                        timestamp INTEGER NOT NULL,
                        details TEXT
                    )
                ''')
                db.execute('CREATE INDEX IF NOT EXISTS idx_pkg_name ON packages(name)')

    def authorize_package(self, manifest_data, files_dict, publisher=None, allowlist=None):
        """Verify package manifest format, files SHA-256 integrity, and publisher authorization."""
        manifest = manifest_data if isinstance(manifest_data, dict) else strict_json(manifest_data)
        schema = manifest.get('schema')
        if schema not in {'ziokt.package.v1', 'ziokt.dcpm-package.v2', 'shadow6.package.v1'}:
            raise ProtocolError('INVALID_MANIFEST', f'unsupported package schema: {schema}')

        name = manifest.get('name') or manifest.get('id')
        version = manifest.get('version')
        if not name or not ID_RE.fullmatch(name):
            raise ProtocolError('INVALID_PACKAGE_NAME', 'canonical package identifier required')
        parse_semver(version)

        pub = publisher or manifest.get('publisher')
        effective_allowlist = set(allowlist) if allowlist is not None else self.allowlist
        if effective_allowlist and (not pub or pub not in effective_allowlist):
            raise ProtocolError('UNAUTHORIZED_PUBLISHER', f'publisher "{pub}" is not in package allowlist')

        # File hash integrity verification
        expected_files = manifest.get('files', {})
        if isinstance(expected_files, list):
            # List of {path, sha256/digest}
            exp_map = {item['path']: item.get('sha256') or item.get('digest') for item in expected_files}
        else:
            exp_map = expected_files

        for file_path, exp_hash in exp_map.items():
            if file_path not in files_dict:
                raise ProtocolError('PACKAGE_INTEGRITY', f'missing file required by manifest: {file_path}')
            actual_data = files_dict[file_path]
            actual_hash = hashlib.sha256(actual_data).hexdigest()
            clean_exp = exp_hash.removeprefix('sha256:')
            if actual_hash != clean_exp:
                raise ProtocolError('PACKAGE_INTEGRITY', f'file hash mismatch for {file_path}')

        return {
            'authorized': True,
            'name': name,
            'version': version,
            'publisher': pub or 'unknown',
            'manifest': manifest
        }

    def _write_slot(self, name, version, manifest, files_dict):
        slot = self.slots_dir / name / version
        slot.mkdir(parents=True, exist_ok=True)
        # Protect against path traversal and write files
        for rel_path, data in files_dict.items():
            if '..' in rel_path or rel_path.startswith('/') or '\\' in rel_path:
                raise ProtocolError('PATH_TRAVERSAL', f'illegal path in package: {rel_path}')
            target = slot / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        # Write manifest
        (slot / '_manifest.json').write_text(json.dumps(manifest, indent=2))
        return slot

    def _set_active(self, name, version, slot_path):
        active_pointer = self.active_dir / f"{name}.json"
        temp_pointer = self.active_dir / f"{name}.json.tmp"
        data = {
            'schema': 'ziokt.package-active.v1',
            'name': name,
            'version': version,
            'slot_path': str(slot_path),
            'updated_at': int(time.time())
        }
        temp_pointer.write_text(json.dumps(data, indent=2))
        os.replace(temp_pointer, active_pointer)

    def install(self, manifest_data, files_dict, publisher=None, allowlist=None):
        """Install package into isolated slot and set active pointer."""
        auth = self.authorize_package(manifest_data, files_dict, publisher, allowlist)
        name, version, pub, manifest = auth['name'], auth['version'], auth['publisher'], auth['manifest']

        # Dependency check
        deps = manifest.get('dependencies', {})
        for dep_name, dep_constraint in deps.items():
            installed_dep = self.get(dep_name)
            if not installed_dep or installed_dep['status'] != 'active':
                raise ProtocolError('DEPENDENCY_MISSING', f'missing active dependency: {dep_name}')
            if not matches_constraint(installed_dep['version'], dep_constraint):
                raise ProtocolError(
                    'DEPENDENCY_INCOMPATIBLE',
                    f'installed {dep_name}@{installed_dep["version"]} does not satisfy constraint {dep_constraint}'
                )

        now = int(time.time())
        slot = self._write_slot(name, version, manifest, files_dict)
        self._set_active(name, version, slot)

        files_manifest = {p: hashlib.sha256(b).hexdigest() for p, b in files_dict.items()}

        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn as db:
                db.execute('''
                    INSERT OR REPLACE INTO packages
                    (id, name, version, previous_version, publisher, installed_at, updated_at, status, slot_path, manifest, files_manifest)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    name, name, version, None, pub, now, now, 'active', str(slot),
                    json.dumps(manifest), json.dumps(files_manifest)
                ))
                db.execute('''
                    INSERT INTO package_history (package_name, version, action, timestamp, details)
                    VALUES (?, ?, ?, ?, ?)
                ''', (name, version, 'install', now, json.dumps({'slot': str(slot)})))

        return {
            'schema': 'ziokt.package-receipt.v1',
            'action': 'install',
            'name': name,
            'version': version,
            'status': 'active',
            'slot': str(slot),
            'timestamp': now
        }

    def upgrade(self, manifest_data, files_dict, publisher=None, allowlist=None):
        """Upgrade active package to newer version with rollback record."""
        auth = self.authorize_package(manifest_data, files_dict, publisher, allowlist)
        name, new_version, pub, manifest = auth['name'], auth['version'], auth['publisher'], auth['manifest']

        current = self.get(name)
        if not current:
            raise ProtocolError('PACKAGE_NOT_FOUND', f'cannot upgrade uninstalled package: {name}')

        if compare_semver(new_version, current['version']) <= 0:
            raise ProtocolError(
                'UPGRADE_VERSION_INVALID',
                f'upgrade version ({new_version}) must be higher than current ({current["version"]})'
            )

        now = int(time.time())
        slot = self._write_slot(name, new_version, manifest, files_dict)
        self._set_active(name, new_version, slot)

        files_manifest = {p: hashlib.sha256(b).hexdigest() for p, b in files_dict.items()}

        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn as db:
                db.execute('''
                    UPDATE packages SET
                    version = ?, previous_version = ?, publisher = ?, updated_at = ?,
                    status = 'active', slot_path = ?, manifest = ?, files_manifest = ?
                    WHERE name = ?
                ''', (
                    new_version, current['version'], pub, now, str(slot),
                    json.dumps(manifest), json.dumps(files_manifest), name
                ))
                db.execute('''
                    INSERT INTO package_history (package_name, version, action, timestamp, details)
                    VALUES (?, ?, ?, ?, ?)
                ''', (name, new_version, 'upgrade', now, json.dumps({
                    'from': current['version'], 'to': new_version, 'slot': str(slot)
                })))

        return {
            'schema': 'ziokt.package-receipt.v1',
            'action': 'upgrade',
            'name': name,
            'version': new_version,
            'previous_version': current['version'],
            'status': 'active',
            'slot': str(slot),
            'timestamp': now
        }

    def rollback(self, name):
        """Atomically revert package to previous version."""
        current = self.get(name)
        if not current:
            raise ProtocolError('PACKAGE_NOT_FOUND', f'package {name} not found')

        prev_version = current.get('previous_version')
        if not prev_version:
            raise ProtocolError('ROLLBACK_UNAVAILABLE', f'no recorded previous version for {name}')

        prev_slot = self.slots_dir / name / prev_version
        if not prev_slot.exists():
            raise ProtocolError('ROLLBACK_SLOT_MISSING', f'previous slot directory missing: {prev_slot}')

        now = int(time.time())
        self._set_active(name, prev_version, prev_slot)

        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn as db:
                db.execute('''
                    UPDATE packages SET
                    version = ?, previous_version = ?, updated_at = ?, status = 'active', slot_path = ?
                    WHERE name = ?
                ''', (prev_version, current['version'], now, str(prev_slot), name))
                db.execute('''
                    INSERT INTO package_history (package_name, version, action, timestamp, details)
                    VALUES (?, ?, ?, ?, ?)
                ''', (name, prev_version, 'rollback', now, json.dumps({
                    'reverted_from': current['version'], 'reverted_to': prev_version
                })))

        return {
            'schema': 'ziokt.package-receipt.v1',
            'action': 'rollback',
            'name': name,
            'version': prev_version,
            'reverted_from': current['version'],
            'status': 'active',
            'slot': str(prev_slot),
            'timestamp': now
        }

    def uninstall(self, name):
        """Uninstall package after reverse dependency verification."""
        current = self.get(name)
        if not current:
            raise ProtocolError('PACKAGE_NOT_FOUND', f'package {name} not found')

        # Reverse dependency check: ensure no active package depends on this
        all_active = self.list_packages(status='active')
        for pkg in all_active:
            if pkg['name'] == name:
                continue
            manifest = pkg.get('manifest', {})
            deps = manifest.get('dependencies', {})
            if name in deps:
                raise ProtocolError(
                    'DEPENDENCY_CONFLICT',
                    f'cannot uninstall {name}: required by active package {pkg["name"]}@{pkg["version"]}'
                )

        now = int(time.time())
        # Remove active pointer
        active_pointer = self.active_dir / f"{name}.json"
        if active_pointer.exists():
            active_pointer.unlink()

        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn as db:
                db.execute("UPDATE packages SET status = 'uninstalled', updated_at = ? WHERE name = ?", (now, name))
                db.execute('''
                    INSERT INTO package_history (package_name, version, action, timestamp, details)
                    VALUES (?, ?, ?, ?, ?)
                ''', (name, current['version'], 'uninstall', now, json.dumps({'slot': current['slot_path']})))

        return {
            'schema': 'ziokt.package-receipt.v1',
            'action': 'uninstall',
            'name': name,
            'version': current['version'],
            'status': 'uninstalled',
            'timestamp': now
        }

    def verify_integrity(self, name):
        """Audit installed files against recorded SHA-256 manifest."""
        current = self.get(name)
        if not current:
            raise ProtocolError('PACKAGE_NOT_FOUND', f'package {name} not found')

        slot = Path(current['slot_path'])
        files_manifest = current.get('files_manifest', {})
        corrupted = []
        missing = []

        for rel_path, exp_hash in files_manifest.items():
            fpath = slot / rel_path
            if not fpath.exists():
                missing.append(rel_path)
                continue
            actual_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
            if actual_hash != exp_hash:
                corrupted.append(rel_path)

        healthy = (len(corrupted) == 0 and len(missing) == 0)
        return {
            'healthy': healthy,
            'name': name,
            'version': current['version'],
            'checked_files': len(files_manifest),
            'missing_files': missing,
            'corrupted_files': corrupted
        }

    def auto_repair(self, name, clean_source_files=None):
        """Detect and restore missing or corrupted files from clean source."""
        audit = self.verify_integrity(name)
        if audit['healthy']:
            return {'repaired': True, 'action': 'none_needed', 'audit': audit}

        current = self.get(name)
        slot = Path(current['slot_path'])
        restored = []
        unrepaired = []

        if clean_source_files:
            for rel_path in audit['missing_files'] + audit['corrupted_files']:
                if rel_path in clean_source_files:
                    fpath = slot / rel_path
                    fpath.parent.mkdir(parents=True, exist_ok=True)
                    fpath.write_bytes(clean_source_files[rel_path])
                    restored.append(rel_path)
                else:
                    unrepaired.append(rel_path)

        post_audit = self.verify_integrity(name)
        now = int(time.time())
        status = 'active' if post_audit['healthy'] else 'corrupted'

        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn as db:
                db.execute("UPDATE packages SET status = ?, updated_at = ? WHERE name = ?", (status, now, name))
                db.execute('''
                    INSERT INTO package_history (package_name, version, action, timestamp, details)
                    VALUES (?, ?, ?, ?, ?)
                ''', (name, current['version'], 'repair', now, json.dumps({
                    'restored': restored, 'unrepaired': unrepaired, 'post_healthy': post_audit['healthy']
                })))

        return {
            'repaired': post_audit['healthy'],
            'restored_files': restored,
            'unrepaired_files': unrepaired,
            'status': status,
            'post_audit': post_audit
        }

    def get(self, name):
        """Fetch package metadata from local database."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                'SELECT id, name, version, previous_version, publisher, installed_at, updated_at, status, slot_path, manifest, files_manifest FROM packages WHERE name = ?',
                (name,)
            ).fetchone()
        if not row:
            return None
        i, n, v, pv, pub, i_at, u_at, st, slot, man, fman = row
        return {
            'id': i,
            'name': n,
            'version': v,
            'previous_version': pv,
            'publisher': pub,
            'installed_at': i_at,
            'updated_at': u_at,
            'status': st,
            'slot_path': slot,
            'manifest': json.loads(man),
            'files_manifest': json.loads(fman)
        }

    def list_packages(self, status=None):
        """List packages, optionally filtered by status."""
        query = 'SELECT name FROM packages'
        params = ()
        if status:
            query += ' WHERE status = ?'
            params = (status,)
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self.get(r[0]) for r in rows]

    def history(self, name=None):
        """Retrieve package modification history."""
        query = 'SELECT package_name, version, action, timestamp, details FROM package_history'
        params = ()
        if name:
            query += ' WHERE package_name = ?'
            params = (name,)
        query += ' ORDER BY timestamp DESC LIMIT 50'
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(query, params).fetchall()
        return [{'name': r[0], 'version': r[1], 'action': r[2], 'timestamp': r[3], 'details': json.loads(r[4]) if r[4] else {}} for r in rows]

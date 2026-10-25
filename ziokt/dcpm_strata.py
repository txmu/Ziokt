"""dCPM Strata Backend Adapter for Corium Strata System.

Bridges Corium Strata and dCPM decentralized package management:
1. Deterministic Dependency Resolution:
   - Maps between Corium category/package:slot semantics and dCPM publisher/version semantics.
   - Slot isolation: separate slots reside in distinct directories (slots/{name}/{slot}/{version}).
2. Verifiable Publisher & Version Identity:
   - Bounds package declarations to explicit publisher public keys (@publisher_key)
     and content digests to prevent source switching during rebuilds.
3. Transactional Staging & Rollback Coordination:
   - Two-phase staging and activation (stage -> commit), allowing Corium to own
     system-level transactions while dCPM manages file slot projections and atomic rollbacks.
4. Security & Local Authorization:
   - Enforces cryptographic signature verification against locally authorized publisher keys.
   - Strictly unprivileged file extraction without install scripts (install_scripts=False).
"""
from contextlib import closing
import argparse
import base64
import secrets
import tempfile
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time

from .protocol import ProtocolError, secure_read, strict_json, encoded
from .security import sign, verify
from .package_storage import atomic_write, check_files, relative_path, safe_path

DCPM_DOMAIN = "Ziokt/dcpm-strata/v1"

SPEC_RE = re.compile(r'^(?:([a-zA-Z0-9_-]+)/)?([a-zA-Z0-9_-]+)(?::([a-zA-Z0-9_-]+))?(?:#([0-9A-Za-z.-]+))?(?:@([a-f0-9]{64}))?$')


def parse_package_spec(spec_str):
    """Parse Corium-compatible package specification.
    Format: [category/]name[:slot][#version][@publisher_key]
    """
    m = SPEC_RE.fullmatch(spec_str) if isinstance(spec_str, str) and len(spec_str) <= 256 else None
    if not m:
        raise ProtocolError('INVALID_SPEC', f'malformed package spec: {spec_str}')
    category, name, slot, version, publisher = m.groups()
    if version in {".", ".."}:
        raise ProtocolError("INVALID_SPEC", "canonical version required")
    return {
        'category': category or 'app',
        'name': name,
        'slot': slot or '0',
        'version': version or '1.0.0',
        'publisher': publisher or ''
    }


class DCPMStrataManager:
    def __init__(self, root_dir):
        self.root = Path(root_dir).absolute()
        self.dcpm_dir = safe_path(self.root, '.dcpm')
        self.slots_dir = safe_path(self.root, 'slots')
        self.db_path = safe_path(self.dcpm_dir, 'installed.db')
        self.auth_file = safe_path(self.dcpm_dir, 'authorities.json')
        self._ensure_layout()

    def _ensure_layout(self):
        self.dcpm_dir.mkdir(parents=True, exist_ok=True)
        self.slots_dir.mkdir(parents=True, exist_ok=True)
        for d in ('bin', 'lib', 'usr', 'etc', 'var'):
            safe_path(self.root, d).mkdir(parents=True, exist_ok=True)

        if not self.auth_file.is_file():
            atomic_write(self.auth_file, encoded({'trusted_publishers': []}))

        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("""
            CREATE TABLE IF NOT EXISTS installed_packages (
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                slot TEXT NOT NULL,
                version TEXT NOT NULL,
                previous_version TEXT,
                publisher TEXT NOT NULL,
                manifest_hash TEXT NOT NULL,
                status TEXT NOT NULL, -- 'staged', 'active', 'rolled_back'
                installed_at INTEGER NOT NULL,
                files_json TEXT NOT NULL,
                PRIMARY KEY (name, slot)
            )
            """)
            db.execute("""
            CREATE TABLE IF NOT EXISTS package_dependencies (
                package_name TEXT NOT NULL,
                package_slot TEXT NOT NULL,
                depends_on_name TEXT NOT NULL,
                depends_on_slot TEXT NOT NULL,
                constraint_expr TEXT NOT NULL,
                PRIMARY KEY (package_name, package_slot, depends_on_name)
            )
            """)
            db.commit()

    def get_trusted_publishers(self):
        try:
            data = json.loads(self.auth_file.read_text())
            return set(data.get('trusted_publishers', []))
        except Exception:
            return set()

    def authorize_publisher(self, pubkey_hex):
        """Authorizes a publisher public key for local installations."""
        if not re.fullmatch(r'[a-f0-9]{64}', pubkey_hex):
            raise ProtocolError('INVALID_KEY', 'valid 64-char hex ed25519 public key required')
        trusted = self.get_trusted_publishers()
        trusted.add(pubkey_hex)
        atomic_write(self.auth_file, encoded({'trusted_publishers': sorted(trusted)}))

    def stage_package(self, spec_str, files, publisher_key, private_key=None, dependencies=None, signed_manifest=None):
        """Verify an explicitly trusted signature before writing an immutable slot."""
        spec = parse_package_spec(spec_str)
        if not re.fullmatch(r'[a-f0-9]{64}', publisher_key):
            raise ProtocolError('INVALID_KEY', 'Ed25519 publisher key required')
        if spec['publisher'] and spec['publisher'] != publisher_key:
            raise ProtocolError('SIGNATURE_REJECTED', 'pinned publisher mismatch')
        if publisher_key not in self.get_trusted_publishers() and spec['publisher'] != publisher_key:
            raise PermissionError('DCPM_UNTRUSTED_PUBLISHER')
        files = {name: data.encode() if isinstance(data, str) else data for name, data in files.items()}
        check_files(files, reserved={'.dcpm', 'slots', '.corix_strata', '_manifest.json'})
        deps = dependencies or []
        if not isinstance(deps, list) or len(deps) > 128:
            raise ProtocolError('DEPENDENCY_CONFLICT', 'bounded dependency specifications required')
        for dep in deps:
            parse_package_spec(dep)
        manifest = {'schema': 'ziokt.dcpm-package.v1', 'name': spec['name'], 'category': spec['category'],
                    'slot': spec['slot'], 'version': spec['version'], 'publisher': publisher_key,
                    'dependencies': deps, 'files': [{'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
                                                   for path, data in sorted(files.items())], 'install_scripts': False}
        envelope = signed_manifest
        if private_key is not None:
            envelope = sign(manifest, private_key, DCPM_DOMAIN)
        if envelope is None or verify(envelope, publisher_key, DCPM_DOMAIN, maximum=1024*1024) != manifest:
            raise ProtocolError('SIGNATURE_REJECTED', 'matching signed manifest required')
        digest = hashlib.sha256(encoded(manifest)).hexdigest()
        slot_dir = safe_path(self.slots_dir, '/'.join((spec['name'], spec['slot'], spec['version'])))
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT version,publisher,status,category FROM installed_packages WHERE name=? AND slot=?', (spec['name'],spec['slot'])).fetchone()
            if row and (row[1] != publisher_key or row[2] == 'staged' or row[3] != spec['category']):
                raise ProtocolError('PACKAGE_CONFLICT', 'publisher/category change or pending stage rejected')
            if slot_dir.exists():
                raise ProtocolError('PACKAGE_EXISTS', 'immutable package version already exists')
            slot_dir.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.stage-', dir=slot_dir.parent) as temporary:
                stage = Path(temporary)/'payload'; stage.mkdir()
                for path, data in files.items():
                    target = safe_path(stage, path); target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    target.chmod(0o755 if path.startswith(('bin/', 'usr/bin/')) else 0o644)
                (stage/'_manifest.json').write_bytes(encoded(envelope))
                os.rename(stage, slot_dir)
            db.execute('''INSERT INTO installed_packages
                (name,category,slot,version,previous_version,publisher,manifest_hash,status,installed_at,files_json)
                VALUES (?,?,?,?,?,?,?,'staged',?,?) ON CONFLICT(name,slot) DO UPDATE SET
                version=excluded.version,previous_version=excluded.previous_version,manifest_hash=excluded.manifest_hash,
                status='staged',installed_at=excluded.installed_at,files_json=excluded.files_json''',
                (spec['name'],spec['category'],spec['slot'],spec['version'],row[0] if row else None,publisher_key,digest,int(time.time()),json.dumps(list(files))))
        return {'status':'staged','spec':spec_str,'manifest_hash':digest,'slot_path':str(slot_dir)}

    def _manifest(self, name, slot, version, publisher):
        directory = safe_path(self.slots_dir, '/'.join((name,slot,version)))
        envelope = strict_json(safe_path(directory, '_manifest.json').read_bytes(), 1024*1024)
        manifest = verify(envelope,publisher,DCPM_DOMAIN,maximum=1024*1024)
        if (manifest.get('name'),manifest.get('slot'),manifest.get('version'),manifest.get('publisher')) != (name,slot,version,publisher):
            raise ProtocolError('PACKAGE_INTEGRITY','slot identity mismatch')
        for entry in manifest['files']:
            data = safe_path(directory,entry['path']).read_bytes()
            if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
                raise ProtocolError('PACKAGE_INTEGRITY','slot content mismatch')
        return directory, manifest

    def _activate(self, db, name, slot, version, publisher, previous):
        directory, manifest = self._manifest(name,slot,version,publisher)
        old_files = set()
        if previous:
            old_dir, old_manifest = self._manifest(name,slot,previous,publisher)
            old_files = {item['path'] for item in old_manifest['files']}
        deps = [parse_package_spec(value) for value in manifest['dependencies']]
        for dep in deps:
            row = db.execute('SELECT version,publisher,status FROM installed_packages WHERE name=? AND slot=?',(dep['name'],dep['slot'])).fetchone()
            if not row or row[2] != 'active' or row[0] != dep['version'] or (dep['publisher'] and row[1] != dep['publisher']):
                raise ProtocolError('DEPENDENCY_CONFLICT','required active dependency is missing or incompatible')
        for constraint, in db.execute('SELECT constraint_expr FROM package_dependencies WHERE depends_on_name=? AND depends_on_slot=?',(name,slot)):
            dep = parse_package_spec(constraint)
            if dep['version'] != version or (dep['publisher'] and dep['publisher'] != publisher):
                raise ProtocolError('DEPENDENCY_CONFLICT','activation breaks a reverse dependency')
        new_files = {entry['path'] for entry in manifest['files']}
        targets = {}
        for path in sorted(old_files | new_files):
            target = safe_path(self.root,path,leaf_link=True)
            if target.exists() or target.is_symlink():
                if not target.is_symlink() or path not in old_files or target.resolve() != (old_dir/path).resolve():
                    raise ProtocolError('FILE_CONFLICT','projection belongs to another package or operator')
            targets[path] = target
        originals = {path:os.readlink(target) if target.is_symlink() else None for path,target in targets.items()}
        try:
            for path,target in targets.items():
                target.parent.mkdir(parents=True,exist_ok=True)
                if path not in new_files:
                    if target.is_symlink(): target.unlink()
                    continue
                temporary = target.with_name('.dcpm-'+secrets.token_hex(12))
                try:
                    temporary.symlink_to(os.path.relpath(directory/path,target.parent));os.replace(temporary,target)
                finally:
                    if temporary.is_symlink():temporary.unlink()
            db.execute('DELETE FROM package_dependencies WHERE package_name=? AND package_slot=?',(name,slot))
            for dep,raw in zip(deps,manifest['dependencies']):
                db.execute('INSERT INTO package_dependencies VALUES (?,?,?,?,?)',(name,slot,dep['name'],dep['slot'],raw))
            db.execute("UPDATE installed_packages SET version=?,previous_version=?,status='active',manifest_hash=?,files_json=? WHERE name=? AND slot=?",
                       (version,previous,hashlib.sha256(encoded(manifest)).hexdigest(),json.dumps(sorted(new_files)),name,slot))
        except Exception:
            for path,target in targets.items():
                if target.is_symlink():target.unlink()
                if originals[path] is not None:target.symlink_to(originals[path])
            raise
        return {'status':'active','name':name,'slot':slot,'version':version}

    def commit(self, name, slot='0'):
        relative_path(name);relative_path(slot)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT version,publisher,previous_version,status FROM installed_packages WHERE name=? AND slot=?',(name,slot)).fetchone()
            if not row:raise ProtocolError('PACKAGE_NOT_FOUND','no staged package')
            if row[3] != 'staged':raise ProtocolError('PACKAGE_CONFLICT','package is not staged')
            return self._activate(db,name,slot,row[0],row[1],row[2])

    def rollback(self, name, slot='0'):
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT version,publisher,previous_version,status FROM installed_packages WHERE name=? AND slot=?',(name,slot)).fetchone()
            if not row or not row[2]:raise ProtocolError('ROLLBACK_UNAVAILABLE','no previous version')
            return self._activate(db,name,slot,row[2],row[1],row[0] if row[3]=='active' else row[2])

    def uninstall(self, name, slot='0'):
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM package_dependencies WHERE depends_on_name=? AND depends_on_slot=?',(name,slot)).fetchone():
                raise ProtocolError('DEPENDENCY_CONFLICT','package has reverse dependencies')
            row=db.execute('SELECT version,publisher,previous_version,status FROM installed_packages WHERE name=? AND slot=?',(name,slot)).fetchone()
            if not row:raise ProtocolError('PACKAGE_NOT_FOUND','package not installed')
            active_version=row[2] if row[3]=='staged' else row[0]
            if active_version:
                directory,manifest=self._manifest(name,slot,active_version,row[1])
                for entry in manifest['files']:
                    target=safe_path(self.root,entry['path'],leaf_link=True)
                    if target.is_symlink() and target.resolve()==(directory/entry['path']).resolve():target.unlink()
            db.execute('DELETE FROM installed_packages WHERE name=? AND slot=?',(name,slot))
            db.execute('DELETE FROM package_dependencies WHERE package_name=? AND package_slot=?',(name,slot))
            shutil.rmtree(safe_path(self.slots_dir,name+'/'+slot))
        return {'status':'uninstalled','name':name,'slot':slot}

    def list_packages(self, quiet=False, format='tsv'):
        """Lists installed packages. Quiet mode outputs Strata-compatible export format."""
        results = []
        with closing(sqlite3.connect(self.db_path)) as db, db:
            rows = db.execute(
                "SELECT name, category, slot, version, publisher, status FROM installed_packages ORDER BY name, slot"
            ).fetchall()
            for r in rows:
                results.append({
                    'name': r[0],
                    'category': r[1],
                    'slot': r[2],
                    'version': r[3],
                    'publisher': r[4],
                    'status': r[5]
                })

        if quiet:
            # Format: name:slot#version@publisher
            lines = [f"{p['name']}:{p['slot']}#{p['version']}@{p['publisher']}" for p in results if p['status'] == 'active']
            return "\n".join(lines)
        if format == 'tsv':
            lines = [f"{p['name']}\t{p['version']}\t{p['status']}\tdcpm" for p in results]
            return "\n".join(lines)
        return json.dumps(results, indent=2)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(prog="dcpm", description="dCPM Decentralized Package Manager (Strata Backend)")
    parser.add_argument("--root", default=os.getcwd(), help="Target root directory (defaults to current dir)")
    subparsers = parser.add_subparsers(dest="subcommand")

    # init
    init_p = subparsers.add_parser("init", help="Initialize a dCPM strata root")
    init_p.add_argument("path", nargs="?", default=".", help="Root path to initialize")

    # install
    install_p = subparsers.add_parser("install", help="Install a package")
    install_p.add_argument("spec", help="Package specification [category/]name[:slot][#version][@publisher]")
    install_p.add_argument("--bundle", required=True, help="JSON with signed manifest and base64 files")
    install_p.add_argument("--publisher", default="", help="Publisher public key")
    install_p.add_argument("--stage-only", action="store_true", help="Stage without committing projection")

    # commit
    commit_p = subparsers.add_parser("commit", help="Commit staged package")
    commit_p.add_argument("name", help="Package name")
    commit_p.add_argument("--slot", default="0", help="Slot identifier")

    # rollback
    rollback_p = subparsers.add_parser("rollback", help="Roll back package to previous version")
    rollback_p.add_argument("name", help="Package name")
    rollback_p.add_argument("--slot", default="0", help="Slot identifier")

    # uninstall
    uninstall_p = subparsers.add_parser("uninstall", help="Uninstall package")
    uninstall_p.add_argument("name", help="Package name")
    uninstall_p.add_argument("--slot", default="0", help="Slot identifier")

    # list
    list_p = subparsers.add_parser("list", help="List installed packages")
    list_p.add_argument("-q", "--quiet", action="store_true", help="Quiet mode (package spec per line for Strata export)")
    list_p.add_argument("--format", choices=["tsv", "json"], default="tsv", help="Output format")

    # authorize
    auth_p = subparsers.add_parser("authorize", help="Authorize a publisher public key")
    auth_p.add_argument("pubkey", help="Hex encoded ed25519 public key")

    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        sys.exit(1)

    target_root = Path(args.root).resolve()
    if args.subcommand == "init":
        target_root = Path(args.path).resolve()
        mgr = DCPMStrataManager(target_root)
        print(f"Initialized dCPM strata root at: {target_root}")
        sys.exit(0)

    mgr = DCPMStrataManager(target_root)

    if args.subcommand == "authorize":
        mgr.authorize_publisher(args.pubkey)
        print(f"Authorized publisher: {args.pubkey}")
        sys.exit(0)

    elif args.subcommand == "install":
        spec = parse_package_spec(args.spec)
        pubkey = args.publisher or spec['publisher']
        bundle = strict_json(Path(args.bundle).read_bytes(), 1024*1024)
        envelope = bundle['manifest']
        pubkey = pubkey or envelope.get('public_key', '')
        pkg_files = {path: base64.b64decode(data, validate=True) for path, data in bundle['files'].items()}
        res = mgr.stage_package(args.spec, pkg_files, pubkey,
                                dependencies=envelope.get('payload', {}).get('dependencies', []), signed_manifest=envelope)
        if not args.stage_only:
            commit_res = mgr.commit(spec['name'], spec['slot'])
            print(f"Installed and activated {spec['name']}:{spec['slot']} ({spec['version']})")
        else:
            print(f"Staged {spec['name']}:{spec['slot']} at {res['slot_path']}")

    elif args.subcommand == "commit":
        res = mgr.commit(args.name, args.slot)
        print(f"Committed {args.name}:{args.slot} version {res['version']}")

    elif args.subcommand == "rollback":
        res = mgr.rollback(args.name, args.slot)
        print(f"Rolled back {args.name}:{args.slot} to version {res['version']}")

    elif args.subcommand == "uninstall":
        mgr.uninstall(args.name, args.slot)
        print(f"Uninstalled {args.name}:{args.slot}")

    elif args.subcommand == "list":
        out = mgr.list_packages(quiet=args.quiet, format=args.format)
        if out:
            print(out)


if __name__ == "__main__":
    main()

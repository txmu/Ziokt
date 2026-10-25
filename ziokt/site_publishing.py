"""Unified Static Website Publishing: upload, sandboxed preview, domain binding, publishing, and version rollback."""
from contextlib import closing
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time

from .protocol import ProtocolError, encoded, secure_read, strict_json
from .security import sign, verify
from .naming import split_name
from .package_storage import atomic_write, safe_path, check_files

SITE_DOMAIN = 'Ziokt/site-publishing/v1'

SAFE_PATH_RE = re.compile(r'^[a-zA-Z0-9_./-]{1,256}\Z')
DOMAIN_RE = re.compile(r'^[a-zA-Z0-9.-]{1,253}\Z')

# Strict isolated sandbox CSP: allow scripts for client interactivity, but NEVER allow-same-origin
# so content scripts cannot access node management APIs, credentials, or storage.
SANDBOXED_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "media-src 'self'; "
    "connect-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "sandbox allow-scripts;"
)


def validate_file_path(rel_path):
    if not isinstance(rel_path, str) or not (1 <= len(rel_path) <= 256):
        raise ProtocolError('INVALID_FILE_PATH', 'file path length 1..256 required')
    if rel_path.startswith('/') or '\\' in rel_path or '..' in rel_path:
        raise ProtocolError('PATH_TRAVERSAL', f'illegal path traversal in site bundle: {rel_path}')
    if not SAFE_PATH_RE.fullmatch(rel_path):
        raise ProtocolError('INVALID_FILE_PATH', f'invalid characters in file path: {rel_path}')
    return rel_path


def guess_content_type(file_path):
    if file_path.endswith('.html') or file_path.endswith('.htm'):
        return 'text/html; charset=utf-8'
    mime, _ = mimetypes.guess_type(file_path)
    if mime:
        return mime
    if file_path.endswith('.mjs') or file_path.endswith('.js'):
        return 'text/javascript'
    if file_path.endswith('.css'):
        return 'text/css'
    if file_path.endswith('.json'):
        return 'application/json'
    if file_path.endswith('.svg'):
        return 'image/svg+xml'
    return 'application/octet-stream'


class SitePublisher:
    """End-to-end static site publishing manager for ordinary users and independent nodes."""

    def __init__(self, root_dir, signing_key=None):
        self.root = Path(root_dir)
        self.objects_dir = safe_path(self.root, 'objects')
        self.db_path = safe_path(self.root, 'sites.db')
        self.signing_key = signing_key
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()
        self.active_previews = {}

    def _ensure_schema(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn as db:
                db.execute('''
                    CREATE TABLE IF NOT EXISTS site_publications (
                        domain TEXT PRIMARY KEY,
                        active_manifest_digest TEXT NOT NULL,
                        previous_manifest_digest TEXT,
                        version TEXT NOT NULL,
                        owner TEXT NOT NULL,
                        updated_at INTEGER NOT NULL
                    )
                ''')
                db.execute('''
                    CREATE TABLE IF NOT EXISTS site_version_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        domain TEXT NOT NULL,
                        manifest_digest TEXT NOT NULL,
                        version TEXT NOT NULL,
                        action TEXT NOT NULL,
                        published_at INTEGER NOT NULL,
                        details TEXT
                    )
                ''')
                db.execute('''
                    CREATE TABLE IF NOT EXISTS site_previews (
                        token TEXT PRIMARY KEY,
                        manifest_digest TEXT NOT NULL,
                        owner TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        expires_at INTEGER NOT NULL
                    )
                ''')
                db.execute('CREATE INDEX IF NOT EXISTS idx_hist_domain ON site_version_history(domain, published_at)')

    def put_object(self, data):
        if not isinstance(data, (bytes, bytearray)):
            raise ProtocolError('INVALID_OBJECT', 'bytes object required')
        digest = hashlib.sha256(data).hexdigest()
        target = safe_path(self.objects_dir, digest)
        if not target.exists():
            atomic_write(target, data)
        elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ProtocolError('OBJECT_INTEGRITY', 'stored object has been corrupted')
        return f"sha256:{digest}"

    def get_object(self, digest_str):
        if not isinstance(digest_str, str) or not re.fullmatch(r'(?:sha256:)?[a-f0-9]{64}', digest_str):
            raise ProtocolError('INVALID_DIGEST', 'canonical SHA-256 digest required')
        clean = digest_str.removeprefix('sha256:')
        target = safe_path(self.objects_dir, clean)
        if not target.exists():
            raise ProtocolError('OBJECT_NOT_FOUND', f'object {digest_str} not in local store')
        if not target.is_file() or target.stat().st_size > 32 * 1024 * 1024:
            raise ProtocolError('OBJECT_INTEGRITY', 'bounded regular object required')
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != clean:
            raise ProtocolError('OBJECT_INTEGRITY', 'object digest mismatch')
        return data

    def manifest(self, digest):
        value = strict_json(self.get_object(digest), 1024 * 1024)
        if (not isinstance(value, dict) or value.get('schema') != 'ziokt.static-site.v1' or
                not isinstance(value.get('owner'), str) or not value['owner'] or
                not isinstance(value.get('files'), dict) or not 1 <= len(value['files']) <= 4096 or
                value.get('entry') != 'index.html' or 'index.html' not in value['files']):
            raise ProtocolError('INVALID_MANIFEST', 'static site manifest required')
        for path, ref in value['files'].items():
            validate_file_path(path)
            if not isinstance(ref, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', ref):
                raise ProtocolError('INVALID_DIGEST', 'invalid site object reference')
        return value

    def upload(self, files_dict, owner, title="Static Site", version="1.0.0"):
        """Validate and ingest website files, generate and store site manifest."""
        if not isinstance(files_dict, dict) or not files_dict:
            raise ProtocolError('EMPTY_SITE_BUNDLE', 'non-empty dictionary of files required')
        if not isinstance(owner, str) or not owner:
            raise ProtocolError('OWNER_REQUIRED', 'valid site owner required')

        if 'index.html' not in files_dict:
            raise ProtocolError('ENTRY_MISSING', 'index.html entrypoint is required in root of site bundle')

        files_dict = {path: data.encode('utf-8') if isinstance(data, str) else bytes(data) if isinstance(data, bytearray) else data for path, data in files_dict.items()}
        check_files(files_dict)

        stored_files = {}
        total_size = 0
        for path_key, data in files_dict.items():
            clean_path = validate_file_path(path_key)
            if not isinstance(data, (bytes, bytearray)):
                data = str(data).encode('utf-8')
            total_size += len(data)
            if len(data) > 32 * 1024 * 1024:
                raise ProtocolError('FILE_TOO_LARGE', f'file {clean_path} exceeds single file limit (32MB)')
            if total_size > 128 * 1024 * 1024:
                raise ProtocolError('BUNDLE_TOO_LARGE', 'total site bundle exceeds quota (128MB)')

            obj_ref = self.put_object(data)
            stored_files[clean_path] = obj_ref

        now = int(time.time())
        manifest = {
            'schema': 'ziokt.static-site.v1',
            'version': version,
            'title': title,
            'owner': owner,
            'created_at': now,
            'entry': 'index.html',
            'file_count': len(stored_files),
            'files': stored_files
        }
        manifest_bytes = encoded(manifest)
        manifest_digest = self.put_object(manifest_bytes)

        return {
            'schema': 'ziokt.site-upload-receipt.v1',
            'manifest_digest': manifest_digest,
            'version': version,
            'file_count': len(stored_files),
            'owner': owner,
            'created_at': now,
            'manifest': manifest
        }

    def create_preview(self, manifest_digest, owner, ttl=3600):
        """Generate a short-lived token to preview the site in strict isolation."""
        # Verify manifest exists
        manifest = self.manifest(manifest_digest)
        if manifest['owner'] != owner:
            raise ProtocolError('PERMISSION_DENIED', 'caller is not the site owner')
        if type(ttl) is not int or not 1 <= ttl <= 86400:
            raise ProtocolError('INVALID_TTL', 'preview lifetime must be 1..86400 seconds')

        token = secrets.token_urlsafe(24)
        now = int(time.time())
        expires = now + ttl

        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn as db:
                db.execute(
                    'INSERT OR REPLACE INTO site_previews (token, manifest_digest, owner, created_at, expires_at) VALUES (?, ?, ?, ?, ?)',
                    (token, manifest_digest, owner, now, expires)
                )

        return {
            'schema': 'ziokt.site-preview.v1',
            'token': token,
            'manifest_digest': manifest_digest,
            'preview_url': f"/preview/{token}/",
            'expires_at': expires
        }

    def serve_preview(self, token, request_path=''):
        """Serve sandboxed static file with strict no-allow-same-origin CSP."""
        now = int(time.time())
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                'SELECT manifest_digest, expires_at FROM site_previews WHERE token = ?',
                (token,)
            ).fetchone()
        if not row:
            raise ProtocolError('PREVIEW_NOT_FOUND', 'preview token expired or nonexistent')
        manifest_digest, expires_at = row
        if now >= expires_at:
            raise ProtocolError('PREVIEW_EXPIRED', 'preview session has expired')

        manifest = self.manifest(manifest_digest)
        rel_path = request_path.strip('/')
        if not rel_path:
            rel_path = manifest.get('entry', 'index.html')

        files_map = manifest.get('files', {})
        if rel_path not in files_map:
            raise ProtocolError('FILE_NOT_FOUND', f'file {rel_path} not in site manifest')

        obj_digest = files_map[rel_path]
        data = self.get_object(obj_digest)
        content_type = guess_content_type(rel_path)

        headers = {
            'Content-Type': content_type,
            'Content-Length': str(len(data)),
            'Content-Security-Policy': SANDBOXED_CSP,
            'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer',
            'Cache-Control': 'no-store',
            'Cross-Origin-Resource-Policy': 'same-origin'
        }
        return 200, headers, data

    def bind_domain(self, domain, manifest_digest, owner):
        """Validate and associate domain with site manifest."""
        if not isinstance(domain, str) or not DOMAIN_RE.fullmatch(domain):
            raise ProtocolError('INVALID_DOMAIN', f'canonical domain required: {domain}')
        if domain != domain.lower() or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in domain.split('.')):
            raise ProtocolError('INVALID_DOMAIN', 'lowercase canonical domain required')
        manifest = self.manifest(manifest_digest)
        if manifest.get('owner') != owner:
            raise ProtocolError('PERMISSION_DENIED', 'caller is not the owner of this site manifest')
        return {'domain': domain, 'manifest_digest': manifest_digest, 'owner': owner}

    def publish(self, domain, manifest_digest, owner, version=None):
        """Publish site version atomically to domain and record in history."""
        self.bind_domain(domain, manifest_digest, owner)
        manifest = self.manifest(manifest_digest)
        ver = version or manifest.get('version', '1.0.0')
        if ver != manifest['version']:
            raise ProtocolError('VERSION_MISMATCH', 'publication version must match its manifest')

        now = int(time.time())
        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn as db:
                db.execute('BEGIN IMMEDIATE')
                current = db.execute(
                    'SELECT active_manifest_digest, version, owner FROM site_publications WHERE domain = ?',
                    (domain,)
                ).fetchone()
                if current and current[2] != owner:
                    raise ProtocolError('PERMISSION_DENIED', 'domain belongs to another publisher')
                prev_digest = current[0] if current else None

                db.execute('''
                    INSERT OR REPLACE INTO site_publications
                    (domain, active_manifest_digest, previous_manifest_digest, version, owner, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (domain, manifest_digest, prev_digest, ver, owner, now))

                db.execute('''
                    INSERT INTO site_version_history
                    (domain, manifest_digest, version, action, published_at, details)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (domain, manifest_digest, ver, 'publish', now, json.dumps({
                    'previous_digest': prev_digest
                })))

        receipt = {
            'schema': 'ziokt.site-publish-receipt.v1',
            'action': 'publish',
            'domain': domain,
            'manifest_digest': manifest_digest,
            'version': ver,
            'previous_digest': prev_digest,
            'published_at': now,
            'owner': owner
        }
        if self.signing_key:
            return sign(receipt, self.signing_key, SITE_DOMAIN)
        return receipt

    def rollback(self, domain, owner, target_version=None):
        """Revert domain binding to previous or explicitly specified historical version."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                'SELECT active_manifest_digest, previous_manifest_digest, version, owner FROM site_publications WHERE domain = ?',
                (domain,)
            ).fetchone()
        if not row:
            raise ProtocolError('SITE_NOT_FOUND', f'no active publication for domain {domain}')
        active_digest, prev_digest, current_ver, pub_owner = row

        if pub_owner != owner:
            raise ProtocolError('PERMISSION_DENIED', 'caller is not the owner of this domain publication')

        target_digest = None
        target_ver = None
        if target_version:
            # Look up specific historical version
            with closing(sqlite3.connect(self.db_path)) as conn:
                h_row = conn.execute(
                    'SELECT manifest_digest, version FROM site_version_history WHERE domain = ? AND version = ? ORDER BY id DESC LIMIT 1',
                    (domain, target_version)
                ).fetchone()
            if not h_row:
                raise ProtocolError('VERSION_NOT_FOUND', f'version {target_version} not in history for {domain}')
            target_digest, target_ver = h_row
        else:
            if not prev_digest:
                raise ProtocolError('ROLLBACK_UNAVAILABLE', f'no previous version recorded for {domain}')
            target_digest = prev_digest
            target_ver = self.manifest(target_digest)['version']

        self.bind_domain(domain, target_digest, owner)

        now = int(time.time())
        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn as db:
                changed = db.execute('''
                    UPDATE site_publications SET
                    active_manifest_digest = ?, previous_manifest_digest = ?, version = ?, updated_at = ?
                    WHERE domain = ? AND owner = ? AND active_manifest_digest = ?
                ''', (target_digest, active_digest, target_ver, now, domain, owner, active_digest))
                if changed.rowcount != 1:
                    raise ProtocolError('PUBLICATION_CHANGED', 'publication changed during rollback')

                db.execute('''
                    INSERT INTO site_version_history
                    (domain, manifest_digest, version, action, published_at, details)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (domain, target_digest, target_ver, 'rollback', now, json.dumps({
                    'reverted_from_digest': active_digest, 'reverted_from_version': current_ver
                })))

        receipt = {
            'schema': 'ziokt.site-publish-receipt.v1',
            'action': 'rollback',
            'domain': domain,
            'manifest_digest': target_digest,
            'version': target_ver,
            'reverted_from_version': current_ver,
            'published_at': now,
            'owner': owner
        }
        if self.signing_key:
            return sign(receipt, self.signing_key, SITE_DOMAIN)
        return receipt

    def history(self, domain):
        """Retrieve deployment history for a domain."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                'SELECT manifest_digest, version, action, published_at, details FROM site_version_history WHERE domain = ? ORDER BY id DESC LIMIT 50',
                (domain,)
            ).fetchall()
        return [{
            'manifest_digest': r[0],
            'version': r[1],
            'action': r[2],
            'published_at': r[3],
            'details': json.loads(r[4]) if r[4] else {}
        } for r in rows]

    def status(self, domain):
        """Get live domain publishing status, active manifest, and rollback possibility."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                'SELECT active_manifest_digest, previous_manifest_digest, version, owner, updated_at FROM site_publications WHERE domain = ?',
                (domain,)
            ).fetchone()
        if not row:
            return {'domain': domain, 'status': 'unpublished'}
        act_dig, prev_dig, ver, own, upd = row
        manifest = strict_json(self.get_object(act_dig))
        return {
            'domain': domain,
            'status': 'published',
            'active_manifest_digest': act_dig,
            'version': ver,
            'owner': own,
            'updated_at': upd,
            'file_count': len(manifest.get('files', {})),
            'rollback_available': bool(prev_dig),
            'previous_manifest_digest': prev_dig
        }

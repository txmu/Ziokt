# Native UFS HTTP / signed DCPM bridge (2026-10)

## What executes now

`companions/ufsdcpm/src/ufsultra.py` runs its actual HTTP/WebDAV handler. All
methods authenticate before dispatch, including inherited GET/HEAD. Digest uses
SHA-256 with qop=auth, exact method/URI/realm binding, expiring server-authenticated
nonces and atomic nonce-count replay checks. Arbitrary nonce strings, replayed
counts, changed client nonces with reused counts, malformed/duplicate fields and
MD5 downgrade attempts are rejected. This is password authentication, not an
end-to-end file signature; use TLS for remote transport.

File operations retain the configured root as a directory descriptor, traverse
with no-follow directory-relative opens, and reject traversal, symlinks, hidden
components, special files and malformed encodings. PUT reads exactly the declared
bounded length into a random exclusive temporary file, fsyncs and atomically
replaces the destination. EOF, timeout or failure removes temporary data without
replacing the existing file. Concurrent writes serialize complete content and
checksum publication. Directory listing and WebDAV Depth 0/1 are bounded; XML
values are escaped and Content-Length counts UTF-8 bytes. Depth infinity is
explicitly rejected. DELETE removes a regular file or empty collection only.

OPTIONS advertises implemented methods. COPY/MOVE/PROPPATCH/LOCK/UNLOCK remain
unsupported rather than claiming successful WebDAV locking. The earlier
supportedlock property did not have a matching locking implementation and is no
longer advertised. Existing API stats/files/transfers/config/cleanup are actually
routed; config responses exclude credentials and paths. Cleanup requires an
explicitly enabled retention policy and an authenticated administrative POST.
Browser cross-origin requests are rejected. Writes require user/admin role and
upload=true. Native file users share the configured root; this does not add a
per-user filesystem ACL system.

`companions/ufsdcpm/src/dcpm_ufs_integration.py` now exposes actual product APIs:

| API | Operation |
|---|---|
| POST `/api/dcpm/publish` | Accept bounded application/octet-stream bytes of the existing signed Ziokt package format; validate pinned publisher, signature, content hashes and version identity; commit private CAS plus SQLite |
| GET/HEAD `/api/dcpm/package?package_id=…&version_id=…` | Retrieve retained bytes and reverify signature, requested identity and stored SHA-256 |
| GET `/api/dcpm/packages` | Bounded retained package inventory |
| GET `/api/stats` | Explicit actual HTTP/P2P/legacy backend status; no Corium consensus assertion |

The native CLI/Python `publish_package` accepts the same `.zpkg` signed bytes.
`download_package` retrieves local verified state or owner-configured native UFS
HTTP sources using SHA-256 Digest, strict TLS verification for non-loopback
sources, no redirect, and no ambient HTTP proxy inheritance. Downloads are
identity-checked before persistence. Signatures are not replaced when caching
another publisher's package. No network pickle deserialization or automatic
installation scripts occur on these paths.

Persistent package publisher keys are independent Ed25519 keys. The optional
historical P2P transport retains a separate persistent RSA identity. New package
store roots have a version index, immutable content digests, 4,096 record ceiling
and configured byte budget. A failed index transaction can leave orphaned signed
CAS data; it does not return a successful publication. The small early follow-up
index without a size column is migrated by measuring retained regular objects.

## Running

From the Ziokt source root with Python 3.12+ and its normal cryptography dependency:

```
PYTHONPATH=. python3 companions/ufsdcpm/src/ufsultra.py --gen-config
```

Generated credentials/configuration are owner-private (0600). Edit the generated
YAML file, or JSON when PyYAML is absent, then run the same script without
`--gen-config`. YAML support requires PyYAML. psutil optionally provides current
RSS; without it, Unix reports explicitly named peak RSS. JSON/HTTP/package
operation does not require aiohttp/aiofiles/libp2p/IPFS/libtorrent to import.

For the integrated product, provide a private JSON configuration and run:

```
PYTHONPATH=. python3 companions/ufsdcpm/src/dcpm_ufs_integration.py system start --config /absolute/private/config.json
```

Minimal configuration shape (replace the password; do not deploy the literal
example credential):

```json
{
  "p2p": {"enabled": false},
  "ufs": {
    "host": "127.0.0.1", "port": 8000, "ssl": false, "upload": true,
    "auth": {"enabled": true, "users": {
      "admin": {"password": "REPLACE-WITH-A-PRIVATE-RANDOM-PASSWORD", "role": "admin"}
    }}
  },
  "storage": {"cache": "private-cache", "ufs_root": "shared-files"},
  "packages": {"trusted_publishers": [], "http_sources": []}
}
```

Absent integrated configuration is generated once at
`~/.config/dcpm-ufs/config.json` with a random password, then reused. Relative
state/key/log/CA paths resolve against the configuration directory, preserving
identity across working-directory changes. The package publisher key is at
`storage.cache/signed-packages/publisher.key` unless explicitly configured.
A trusted remote source needs an explicitly pinned 64-hex publisher in
packages.trusted_publishers and an owner-configured http_sources entry containing
url, username, password and optional CA path. The source URL is never supplied by
an untrusted HTTP caller.

## Compatibility and security boundaries

- Old unauthenticated GET/HEAD behavior is intentionally closed. Old MD5/no-qop
  Digest responses do not authenticate; clients must honor the SHA-256 challenge.
- Configuration with secrets must be an owner-controlled private regular file.
  Weak default admin123 is removed; minimum password length defaults to 12.
- Standalone defaults use a dedicated ufs-data directory, loopback whitelist,
  upload=false and retention deletion disabled. Non-loopback plaintext listeners
  are refused. TLS private material, logs, configuration and package key/cache
  storage must remain outside the served root.
- Existing signed package bytes and IDs remain unchanged. Same version ID with
  different content is refused. Package storage is owner-private filesystem
  storage; it is not represented as an encrypted Vault. Ziokt's existing
  Vault/Community publication path remains separate and encrypted.
- Dynamic request policy can reload. Root/listener/TLS/concurrency/bucket changes
  require restart, avoiding a mixed policy generation while requests are active.
- A successful local package receipt reports replica_count=1,
  network_published=false and chain_confirmed=false. Requested redundancy greater
  than retained copies reports replication_satisfied=false. DHT publication is
  not described as durable replication or consensus acceptance.
- p2p.enabled and ufs.legacy_file_chain are explicit opt-ins. The legacy native
  P2P dependency stack, UFSBlockchain file metadata replication, IPFS and
  BitTorrent were not validated here. Disabled legacy file-chain routes return
  501. Their original mechanisms remain present; this follow-up does not certify
  their complete behavior or silently replace them with a single-node chain.
- Secure descriptor confinement requires the platform's directory-relative and
  no-follow APIs. Unsupported platforms, including the current Windows backend,
  fail closed and their native UFS tests skip explicitly. This is not a claim of
  complete cross-platform native UFS support.
- ZIOKT_AIRGAP refuses native listeners and native HTTP-source downloads.
  Local signed package storage remains available without a listener.

## Evidence

`tests/test_ufs_native_http.py` exercises real local HTTP and pinned-certificate
TLS, authentication and replay/expiry/type negatives, traversal/symlinks/FIFO,
exact/truncated/empty/oversized/concurrent uploads, UTF-8 WebDAV, read-only/guest
permissions, browser origin rejection, unsafe configuration and AirGap startup.

`tests/test_ufs_dcpm_native_integration.py` starts two actual IntegratedSystem
instances with independent private state, uses their product HTTP routes to
exchange existing Ziokt signed packages, stops the source, reopens persistent
state and keys, and rejects corruption, unknown publishers, unsigned input,
version conflicts and wrong requested identity. It does not substitute a test
HTTP implementation for the product endpoint.

Commands:

```
PYTHONPATH=tests:. .venv/bin/python -m unittest test_ufs_native_http test_ufs_dcpm_native_integration -q
python3 -m py_compile companions/ufsdcpm/src/ufsultra.py companions/ufsdcpm/src/ufs_http_security.py companions/ufsdcpm/src/dcpm_ufs_integration.py companions/ufsdcpm/src/dcpm_ufs_packages.py
```

Final Linux run with the minimal Ziokt venv (cryptography present, optional YAML
and psutil absent): **12 passed, 0 failed, 0 skipped, 8.344 seconds**. Python
syntax compilation and the scoped whitespace check also passed. Tests include
mmap downloads, correctly framed gzip, a real wall-clock deadline closing
incomplete slow headers, storage-budget rejection before CAS insertion, and the
actual one-shot native CLI publishing while the product's HTTP port is already
occupied. These checks do not invoke a system package installer or modify host
packages. CLI install/uninstall require `--allow-system-install` and a local
manager selection; unresolved dependencies still return an explicit native DCPM
error instead of a successful installation claim.

Connections have both a per-read timeout and a total wall-clock budget (default
30 seconds, configurable up to 300). Active requests drain on server shutdown;
shared token buckets and connection slots bound concurrent transfer work.

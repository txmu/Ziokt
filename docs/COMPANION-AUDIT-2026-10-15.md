# Companion audit supplement — 2026-10-15

This supplement records new findings after `verification-current.json`'s existing
CI evidence. It does not replace that report or assert a complete new audit of
all companions.

## Fixed: WATChat durable acknowledgement

`companions/watchat/WATChat-code/backend/server.js` previously inserted a message
into memory before saving the encrypted store. If the save failed, retransmitting
the same ID followed the duplicate branch and acknowledged an unsaved message.
Similarly, a later malformed frame in a federation pull could leave earlier
frames in memory; a retry could acknowledge them without persisting them. Pulled
messages were also delivered to connected browsers before the store was saved.

Changes:

- Failed local inserts remove their message and outbox entry before returning an
  error. Failed federation inserts remove their message.
- Duplicate messages are saved before acknowledging, including during federation
  pull; each new pulled frame is saved before delivery and before `chat.ack`.
- Atomic encrypted store replacement flushes the parent directory on Unix. Node's
  Windows API cannot open directory handles this way; Windows retains file fsync
  and atomic replacement, with no newly claimed power-loss guarantee.
- Temporary save files are cleaned on failure.
- Both endpoints must remain mutual local contacts; the authorization is checked
  again after asynchronous attachment retrieval, before accepting the message.

The real gateway test renames the data directory to cause a genuine write
failure, checks no acknowledgement and no memory-only history entry, restores the
filesystem, retransmits, decrypts the actual persisted store, and starts a fresh
server process to verify the recovered history.

## Fixed: SIM Manager concurrent first-save key replacement

`companions/sim-manager/src/utils/stateStore.ts` performed a separate key lookup,
asynchronous key generation and unconditional key write. Two tabs could each
create a key, overwrite the other's persisted key and make the final stored
ciphertext undecryptable.

Key creation now uses an IndexedDB readwrite transaction: it rechecks the key and
selects the existing key, or inserts its candidate if still absent. The key's
format, database version, AES-GCM AAD and ciphertext format are unchanged. Existing
sealed state with a missing key fails explicitly with `SIM_KEY_MISSING`; it does
not silently create a replacement key. No data migration is needed.

`tools/sim_storage_race_smoke.cjs` transpiles the actual TypeScript source and uses
two real Chromium tabs sharing IndexedDB. Deliberate crypto timing forces the
old key-replacement race. The test verifies both tabs can read the final state,
missing-key rejection, and a quota failure during legacy migration preserving the
original localStorage input until a subsequent successful encrypted save.

## Commands actually run

From the Ziokt repository:

```
node --check companions/watchat/WATChat-code/backend/server.js
node --test companions/watchat/WATChat-code/test/*.test.js
node tools/sim_storage_race_smoke.cjs
```

From `companions/sim-manager/src`:

```
node node_modules/typescript/bin/tsc --noEmit
```

Results: Node **6 passed, 0 failed, 0 skipped**; browser scenario **1 passed**;
TypeScript and JavaScript syntax commands exited **0**. No Rust compilation or
unrelated full regression was run in this supplement.

## Integration scope and remaining verification

Source review confirmed the existing `ApplicationRouter` routes Shadow6/Corium to
native providers, ETP to the digest-pinned gateway, and companions to scoped
`CompanionBridge` instances. `ufsdcpm.py` verifies signed manifests, bounded file
sets, SHA-256, noncolliding virtual paths and rejects installation scripts. These
checks retain the previous test evidence; they are not a newly executed full
network/package lifecycle test.

The new test exercises WATChat's real local persistence failure and restart. It
does not independently exercise a two-installation WATChat federation pull with
a malformed trailing frame; that branch was corrected by source inspection and
still needs that dedicated end-to-end failure scenario. Full original UFS/DCPM
service interoperability, mobile push delivery, platform-specific filesystem
power-loss behavior, and all-companion concurrent partition recovery were not
newly verified here. Missing-key detection cannot recover a lost key. Browser
nonextractable keys protect stored bytes against ordinary inspection, not an
attacker controlling the web origin or browser profile.

## Additional ETP anonymous transport and SideChannel fixes

The external anonymity facade previously used a literal `if true` to select mixed
Tor/UDP transport. Unmapped addresses therefore silently used clearnet UDP even
with external anonymity enabled. `DeepProfile.allow_clearnet_fallback` now defaults
to `false` during construction and deserialization. External anonymity uses only
`TorDynamicTransport`, and onion registration works in that mode. The pre-existing
mixed transport remains available only with the explicit field set to `true`.
Old configurations require no format migration, but their implicit direct UDP
traffic is intentionally refused until the owner explicitly permits mixed mode.

The `allow_dynamic_side_channels=false` branch previously called the same
implicitly registering receive function as the enabled branch. The engine now
passes the actual permission to the SideChannel manager: unregistered IDs are
rejected before creating state; locally registered IDs remain usable.

Three Rust tests were added for strict external transport and SideChannel
permissions. They use real local sockets and manager state, including an occupied
UDP bind address and no-packet/no-proxy-dial checks. They were parsed with rustfmt;
**they have not been compiled or executed locally**. CI must execute them with the
`anonymity` feature (already in the normal full feature set).

## Additional native UFS/DCPM hardening

This work modifies the actual `companions/ufsdcpm/src` implementation, separately
from the already signed Ziokt adapter. Archived `original` files are unchanged.

- Network metadata no longer uses `eval`. A bounded literal reader handles the
  existing inert Python representation, including precisely the legacy
  `FileChecksum` namedtuple representation; arbitrary calls are rejected.
- Package and memory-pool pickle readers reject executable globals and persistent
  references. Only the existing `FileChecksum` constructor is allowed. Input,
  opcode count, nesting and expanded zlib data have explicit bounds. Existing
  primitive-data pickles remain readable; executable/custom-object pickles are
  intentionally incompatible and must be exported as primitive data by a trusted
  offline legacy process.
- Native `Package.from_bytes` validates exact fields, file paths, counts, sizes,
  dependency labels and recalculated checksums instead of trusting serialized
  checksums. The broken CRC32 conversion and missing cryptography imports were
  corrected. Optional transport imports are deferred to their use sites.
- Native system install/uninstall uses argument arrays and private temporary
  directories, checks the actual exit status, and requires the explicit local
  `allow_system_install=True` grant. Remote stream handlers do not supply that
  grant. `uninstall` additionally requires an explicit `package_manager`. This
  closes shell injection and remote automatic package execution. Dependencies
  without a configured resolver raise an error before native system changes;
  they are not reported as successfully installed. Existing system-manager
  scripts remain the responsibility of that explicit local grant. Multi-package
  OS package-manager rollback is not claimed.
- The memory-pool example is retained behind `if __name__ == '__main__'`, so importing
  the component no longer allocates example state or prints demo output.

New native tests use the real Package and memory-pool classes: binary roundtrip,
checksum tampering, path traversal, malicious pickle reduction with an execution
marker, literal-call attacks, zlib expansion/truncation/trailing data, default
install authorization, and a real harmless local executable proving exact argv,
cleanup and nonzero-exit rejection. The executable fixture uses a POSIX shebang
and is explicitly skipped on non-POSIX hosts.

Command:

```
python3 -m unittest discover -s tests -p test_dcpm_native_security.py -v
```

The original DCPM network was not complete after this first hardening pass. The
subsequent signed publication/transport work below supersedes the earlier
findings about default example nodes, Package publisher identity and signature
coverage. Unverified optional P2P backend APIs remain a separate limitation.

Native DCPM targeted result on this Linux host: **6 passed, 0 failed, 0 skipped**,
0.252 seconds. Python compile checks for the four changed native modules and the
new test exited 0. These counts are separate from the earlier six Node tests.


## Native DCPM signed publication and real transport follow-up

`dcpm_signed.py` now shares the **existing** Ziokt package format and signature
domain (`ziokt.dcpm-package.v1` / `Ziokt/DCPM/package/v1`) between native core and
P2P publication/download. It does not introduce a new signature algorithm or
trust protocol. The native DHT text value is a base64 transport representation
prefixed `ziokt.dcpm-package.v1:`. Legacy unverified metadata is explicitly
rejected on signed download; the inert legacy reader is for inspection only.

Native publication requires a persistent owner-private 32-byte Ed25519 key file
via `publish(signing_key=...)` or `ZIOKT_DCPM_SIGNING_KEY`. It never generates or
replaces that key on import/restart. Download requires a pinned publisher public
key via `download(authority=...)` or `ZIOKT_DCPM_PUBLISHER_PUBLIC_KEY`. The publisher
is included in package and version identifiers; different versions have separate
DHT entries, while the package entry names the latest published version. The
signed manifest binds name, version, dependencies and file content. The native
system package manager remains a local choice; network metadata cannot select it.
Legacy RSA helper functions remain available only with explicit keys and are not
the trust root for signed package download.

`ZIOKT_DCPM_DHT_NODES` is a JSON list, maximum eight URLs, default `[]`; the test
network also defaults to no peers. No example node is treated as a live service.
Missing peers raises `DCPM_DHT_NOT_CONFIGURED`. The existing HTTP GET-based DHT
client now uses standard-library HTTP with encoded parameters, bounded responses,
timeouts and no redirects; HTTPS certificate verification retains the system
trust store. Binary values use a declared `dcpm-bytes-v1:` base64 representation.
Configured HTTP is explicit clear transport and does not claim confidentiality.
Provider failures allow trying the next configured provider; publishing reports
failure if all providers fail. A successful DHT response is not proof of durable
multi-node replication or blockchain confirmation. The old incorrectly framed
TCP/UDP paths now fail explicitly; they must not truncate a SHA-256 key to 16
bytes or pretend a TCP connection is UDP. The native HTTP path refuses AirGap
before any network attempt.

`read_blocks` is shared by the native P2P file and content readers. It follows
manifest order including repeated hashes, caches actual verified bytes, validates
each SHA-256, limits block/aggregate sizes and block count, and times out each
fetch. Integer progress from the old cache is refetched rather than appended to
bytes. A missing/corrupted block raises and preserves earlier valid cached blocks
for a later explicit retry. The cache remains in memory; after process restart a
new download re-fetches rather than claiming a saved resumable transfer.

The targeted test now runs native `Package.publish/download` against a real
loopback HTTP endpoint backed by SQLite and downloads the signed package in a
fresh Python process. This verifies the client's actual socket transport, format,
key reuse/pinning and content, not deployment of an independent native DHT server.
It also checks signature tampering, wrong version/publisher, rejection of legacy
unsigned metadata, missing-block retry, repeated-block order, real binary HTTP
values and corrupted block rejection. The endpoint is an isolated protocol test
service; it does not substitute for untested native DHT server code.

Remaining limits: the original optional libp2p/TLS/proxy backends still have
unverified imports/APIs, handshake and direct-stream methods. No full native P2P
service startup or native multi-node consensus is claimed. The legacy local
`Blockchain` remains an in-memory demo and is not Corium consensus. Existing
GET-based servers may enforce a request-line limit below the package format's
maximum; such publication returns a real HTTP error, and a production peer must
explicitly provide an adequate compatible endpoint. Transport-level acknowledgement
does not establish durable replication. Dependencies require owner configuration;
the installer refuses unresolved dependencies rather than inventing a resolver.

Final native DCPM follow-up result: **10 passed, 0 failed, 0 skipped** in 1.834
seconds using the same targeted unittest command. Compile checks exited 0. This
supersedes the earlier six-test DCPM result; the six Node tests remain separate.
ETP Rust runtime tests still require CI and are not counted as passed here.

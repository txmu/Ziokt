# ZKN private delivery v2

## Implemented path

The existing signed ZKN transaction, one-time receiving key/address, encrypted
receipt, native ownership transition and transaction-hash deduplication are
unchanged. `GiftRPC` now defaults to delivery v2 and the real `/zfcp` receiver
understands both versions. This is connected to `ziokt zkn deliver`, including
keyless multihop routing and durable retry; it is not an unused alternate class.

Each individual RPC uses a fresh random 256-bit delivery ID and new grant nonce.
The delivery ID and exact provider request are bound into the existing signed
grant digest. The outside capsule contains only version, delivery ID, payload and
random padding, with no clear token, owner, recipient, transaction hash or
operation ID fields. Both requests and responses are exactly 32768 bytes. The
response must echo the current delivery ID. Oversized frames fail explicitly;
there is no silent size class change or automatic legacy downgrade.

**The capsule uses the existing end-to-end mTLS connection for encryption and
integrity. Base64 encapsulation is not encryption.** Each actual call establishes
fresh TLS transport state, wraps the current signed grant and random padding,
and retains existing certificate pinning, principal authorization and persistent
replay checks. No new cipher, anonymous signature or zero-knowledge protocol is
introduced. Keyless relay nodes cannot read the capsule through that TLS
connection, but the authenticated destination can read the RPC and identify its
client principal. The new capsule does not replace the asset owner's transaction
signature or the signed one-time receiver offer.

## Persistent mixed scheduling

New `GiftOutbox` rows default to `privacy_mode='mixed'`: an initial random delay
of 1–8 seconds, persistent next-attempt time, shuffled ready entries, bounded
work per cycle (default eight, maximum sixteen), randomized retry intervals and
shuffled route selection. Entries aged sixty seconds receive oldest-first
priority before a bounded batch is shuffled, preventing random selection alone
from starving an individual entry. Delivery still requires a worker to run and
an available approved route and native provider; this is not a guaranteed
wall-clock delivery SLA or a cover-traffic network.

An operation ID is random when a new intent is enqueued and remains unchanged
across every retry and process restart. It no longer embeds a transaction-hash
prefix. A lost acknowledgement triggers native fact reconciliation before any
further prepare/commit, using the identical signed transaction and operation
intent. The native transaction hash remains the authoritative deduplication key;
relays never become asset holders. Route failures choose another admitted path;
`GiftRPC` rejects a route without the required keyless multihop carrier rather
than dialing directly.

The signed transaction body remains AES-GCM encrypted in the private SQLite
outbox. Operation ID, scheduling metadata and the transaction-hash index are
local metadata, protected by the owner-private database permissions; this is not
a claim that the entire SQLite file is encrypted. The existing outbox encryption
key is unchanged. The schema migration adds operation ID and delivery-mode
columns and leaves original ciphertext bytes intact. Existing rows remain marked
legacy and preserve the most recent old operation intent; no asset or key is
silently reissued. New mixed rows retain their schedule after restart.

Outboxes retain the 4096-row limit and now enforce a 256 MiB allocation budget
for new databases, a bounded signed body size and enqueue headroom. Existing
larger databases remain available for status/reconciliation and may not grow;
new enqueue requests require archival when the byte budget is exhausted. Startup
checks file type, ownership and permissions using an opened descriptor rather
than reading the entire database. SQLite cache is limited to 2 MiB with mmap
disabled; selecting a batch reads metadata first and loads only the selected
bounded ciphertexts. A real database larger than the old 32 MiB reopen limit is
covered by the migration test.

## Explicit compatibility

- `GiftRPC(..., delivery_version=1)` retains the previous padded mTLS format.
- `GiftOutbox(..., privacy_mode='legacy')` permits immediate initial scheduling.
- CLI `zkn gift --legacy-delivery` chooses legacy scheduling for new rows;
  `zkn deliver --legacy-delivery` explicitly selects wire v1 for an older server.
- New clients do not retry with a weaker format when a v2 call fails.
- Ordinary Community/Bridge/native mTLS requests continue to use their existing
  envelope and grant digest. The fixed-size gift wrapper is not forced onto them.

## Observed evidence and limits

The actual two-hop integration test sends through one route, drops the commit
acknowledgement after native submission, stops its ingress, switches to another
two-hop route, confirms the transaction and checks exactly one native ledger
transaction. Sender-side observation records the actual outbound HTTP frames
without replacing socket or native execution: every v2 frame has fixed size and
a distinct delivery ID. The same real route rejects a replayed grant and a
changed delivery ID, and explicitly selected wire v1 remains interoperable.

The unit tests check fixed frame shape, malformed capsules, queue delay,
operation-intent reuse after restart, old-schema ciphertext preservation and a
real 33 MiB database reopening. This does not prove anonymity against global
observers, colluding relays or a compromised endpoint. Endpoint addresses,
connection timing, TLS metadata, packet counts and public on-chain token/owner
transitions can remain correlatable. Low traffic does not magically create an
anonymity set, and withholding packets cannot be made impossible.

## Cross-process delivery leases

The outbox now atomically claims each ready row using a random durable lease
token and a five-minute deadline. Separate processes/connections cannot both
enter delivery for the same unexpired lease. Each external RPC checks and renews
its ownership before and after the call. A worker that loses its lease stops
before any subsequent prepare/commit; final row updates require the same token,
so an old worker cannot overwrite a replacement worker's result.

After a process crash the signed ciphertext and operation intent remain
unchanged. Another worker can claim an expired lease and reconciles the native
fact before considering submission. Lease expiry cannot retract an RPC already
sent: native operation idempotency and transaction-hash deduplication remain
required. No exactly-once network delivery or larger anonymity set is claimed.
The additive migration preserves old ciphertext and intent. Queue insertion and
schema migration use SQLite write transactions to serialize separate writers.

Three focused tests cover separate SQLite workers, a genuinely terminated child
process, and a stale worker losing its lease. The recovery deadline is explicitly
expired by test fault injection rather than a fabricated wall-clock wait.
Controlled failure callbacks in these unit tests are not native delivery success
evidence; the actual encrypted multihop integration remains separately tested.

`zkn.fact` is an authenticated observation returned by the configured native
provider through pinned local/native or mTLS calls. The native query checks its
chain data/signatures; an arbitrary external JSON object containing
`inclusion.assurance='native-signed-inclusion'` is **not** a portable cryptographic
proof. Neither the capsule nor Ano decisions upgrade an untrusted JSON fact into
one. Users must retain the configured trusted provider boundary and actual native
confirmation checks.

Commands run for affected paths:

```
PYTHONPATH=tests python3 -m unittest test_collectibles.Collectibles test_collectible_network.CollectibleNetwork -v
PYTHONPATH=tests python3 -m unittest test_collectibles.Collectibles test_community_network test_remote_native -v
python3 -m py_compile ziokt/collectibles.py ziokt/collectibles_cli.py ziokt/remote.py
```

The first command passed **9 tests, 0 failures, 0 skipped** in 16.332 seconds.
Additional regression results are reported separately after execution. No local
native compilation was performed.

The ordinary transport compatibility regression passed **23 tests, 0 failures,
0 skipped** in 19.695 seconds: eight collectible unit tests, fourteen Community
network tests and one real native mTLS/replay test. This overlaps the unit tests
in the nine-test command; the counts must not be added as distinct tests.

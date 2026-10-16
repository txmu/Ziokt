# Native Forum gateway and persistent application session

The existing `ziokt_gateway` JSONL executable can optionally host Forum v2. The
old configuration and four existing methods remain accepted. Without a `forum`
configuration it creates no Forum DB or plugin; without the Rust `persistence`
feature every `etp.forum.*` method returns `METHOD_UNSUPPORTED` and creates no DB.
Full/integrated builds support the configured implementation. Method names alone
are not a capability proof: the Python adapter checks the actual native response.

`examples/etp-forum-gateway.json` shows the added optional object. Replace its
placeholders with operator-generated keys and approved addresses. Keep the
configuration owner-private (0600). The DB path must be absolute, contain no
symlinks, and point to an owner-private directory (0700); its parent must already
exist. Unsafe writable ancestors are rejected except sticky directories such as
`/tmp`. Platforms without the implemented ownership check fail explicitly when
Forum is configured. IPC requests cannot select a database path, seed or binary.
At most eight named Ed25519 identities and 64 subscriptions are accepted.

Identity names select seeds already in this private configuration. Seeds are
never returned. Forum author NodeIDs derive from Ed25519 public keys and are
distinct from Noise transport NodeIDs. There is no automatic Community bridge,
blockchain action, or external message publication.

| Method | Exact params | Result |
|---|---|---|
| `etp.forum.identity` | `{"name":"author"}` | Public name and author NodeID |
| `etp.forum.subscribe` | `{"topic":"native-forum"}` | Topic hash and persisted subscription acknowledgement |
| `etp.forum.publish` | `{"topic":"native-forum","content":"text","author":"author","parent_id":null}` | Post ID, `stored:true`, `state:"stored_locally"`, DHT enqueue status, `gossip:"best_effort"`, `delivery_confirmed:false` |
| `etp.forum.get` | `{"id":"64_hex_digits"}` | Validated retained post or `post:null` |

For anonymous publication `author` must explicitly be `null`. Omitting it is an
error. `parent_id` may be omitted or null. Content is bounded to 32768 UTF-8 bytes;
topics to 256 bytes; names to 64 ASCII letters/digits/underscore/hyphen. Unknown
fields and identity names are rejected. Publication signs and flushes the real
sled store before acknowledging local persistence. Gossip is best effort, and
DHT enqueue is not remote replication confirmation. Large posts exceed native
DHT's 2048-byte object budget but remain stored and available to peer sync.

`get` returns IDs as hex, author null or hex, timestamp, immediate parent status,
base64 signature, and `content_base64` as a list of at most eleven base64 chunks
(each at most 4096 characters). This preserves full 32 KiB content while obeying
Python's strict JSON string budget. The native store verifies ID/proof/TTL before
returning a post; the Python adapter additionally validates the result shape and
bounds. `missing_or_expired` never claims a complete thread.

Subscriptions, including dynamic IPC subscriptions, are flushed into the
configured sled DB and loaded again after restart. The gateway binds Forum to
Composite stream 3, starts only approved peer connections, and relays bounded
Forum network and DHT queues through the existing real Engine handle.

## Keep the explicitly started process alive for peer synchronization

Grant the desired `etp.forum.*` methods under the existing application router's
`components.etp.methods`; retain its pinned binary digest and private config.
Use the common owner-started stdin/stdout entry:

```
python3 -m ziokt companion app serve --bridge-config /absolute/private/router.json
```

Each newline-terminated input is exactly `{"target":"etp","method":
"etp.forum.identity","params":{"name":"author"}}` (on one line). Each output
is `{"ok":true,"result":...}` or a typed `{"ok":false,"error":{"code":...}}`.
The entry opens no listener or anonymous port. It accepts at most 4096 frames,
131072 bytes per frame, and closes cached backends at EOF. Existing native
Shadow6/Corium CLI forwarding reaches this same app entry. A long-lived Python
`ApplicationRouter` also caches the same ETP subprocess across calls and offers
`close()` plus context-manager cleanup. Configuration changes invalidate and
close the cached backend.

The one-shot `app call`/`etp call` commands close their gateway after the result.
Their publication result guarantees only local persistence and best-effort
submission; it does not establish cross-call P2P delivery. Keep `app serve` or a
long-lived adapter open for live pushes, synchronization, and reconnection.
Adapter close requests native `etp.shutdown`, waits briefly, and terminates an
unresponsive child. Successful store/subscribe acknowledgements already flushed
before this shutdown. No implicit detached daemon is created.

## Verification evidence

Locally executed Python checks cover six adapter tests and two real app-serve
subprocess tests. The latter execute real Ano arithmetic/defence, method grants,
bounded frames and EOF cleanup; a pinned helper subprocess measures ETP IPC
lifecycle and response validation, not native networking.

`ci/etp_gateway_smoke.py` now explicitly requires Forum for integrated builds and
requires `METHOD_UNSUPPORTED` for minimal builds. The real-native section defines
two pinned-key UDP gateways (one reached through the actual ApplicationRouter
and its cached native backend), signed 32 KiB publication, independent Ed25519 proof
verification, dynamic subscription persistence, same-address process restart,
and a return reply. Native execution results must come from CI; no local cargo
build/check/test was run. This document does not mark that pending native smoke
as passed.

## Chat feature compatibility discovered during native CI

CI exposed a historical `cfg(feature="sled")` gate that hid Chat even with the
real `persistence` feature. The gate now uses `persistence`; the obsolete
OnionCrypto tuple calls use its existing versioned full-packet API, and the
required Debug implementation no longer exposes key fields. Chat v3 signs its
sender, receiver, message ID, timestamp, MIME and content under an explicit domain.
Old v2 proofs are rejected. On open, old/unverifiable inbox, outbox and history
records move in a sled transaction into `quarantined_chat_v2`; each value encodes
`(source_tree_name, original_key, original_bytes)`, preserving historical bytes.
No historical record is silently authenticated or deleted. The Forum cross-domain
regression signs an actual ChatMessage's canonical bytes.

This fixes the discovered feature/API/signature path; it does not claim the
remaining historical Chat SYNC, retry/DHT delivery, full message fragmentation,
or application trust-extension placeholders have been completed.

## Authenticated restart versus rekey: IK4

The native same-address restart CI found that preserving a stopped peer's stream
offsets and ACK/deduplication state hides new offset-zero messages indefinitely.
The Engine now explicitly negotiates the runtime incarnation inside Noise IK.
Its 32-byte authenticated hello is `ETPIK4\0\0`, UTC seconds (big endian u64),
and a random 16-byte Engine boot ID. The authenticated response is
`ETPR4\0\0\0` followed by the responder's 16-byte boot ID. The boot ID is never
an additional plaintext header or public identity. It is generated independently
for each Engine instance; Noise still creates a fresh ephemeral key per handshake.

The existing trusted-static-key pin, ACL, 30-second hello freshness and replay
response cache are enforced before replacing a session. Existing-session traffic
first attempts normal transport authentication; only a failed 128-byte record
is considered as an initial IK flight. Valid transport frames of that length
continue through normal decoding.

Same-boot rekeys retain stream offsets/reliability so previously established
stream sequences continue. A different authenticated boot ID creates fresh
stream offsets and packet/ACK state and emits close/open callbacks outside the
session lock. Old pending plaintext, old ACKs and old in-flight reliability state
are not copied to the new peer runtime. The application must retry using its
own durable state; Forum's reconnect inventories recover retained posts. A
local enqueue acknowledgement is still not a remote delivery acknowledgement.
The fresh session is installed before its handshake response is sent, so fast
transport packets cannot race an old map entry. Session replacement does not
increment the live-session counter a second time.

IK3 is explicitly rejected: both peers must upgrade to IK4. Node configuration,
pinned long-term keys and Forum's post format do not change. There is no implicit
legacy fallback that pretends restart continuity.

Two added Rust regression definitions check discarded old plaintext/ACK queues
and actual UDP same-port replacement of a complete Engine, bidirectional
zero-offset traffic, same-boot rekey continuation, session counts and rejection
of a genuinely Noise-authenticated obsolete IK3 hello. The Rust test retains a
bound real socket to avoid port-allocation races; the existing native gateway CI
smoke separately closes and rebinds a real process on the same address. Neither
new regression was executed locally; cargo remains restricted to CI.

### Final Chat safety follow-up

Inbox inserts and message-ID indexes now update atomically and flush before any
UI event or ACK. Conflicting IDs and the 4096-message capacity fail without an
ACK. Delivery history/outbox removal is atomic and flushed. ACK acceptance
requires an active session and an Engine-authenticated route for the exact signed
receiver/target NodeID; an unresolved or different peer cannot mark delivery.
The signed receiver is the destination Engine NodeID, distinct from the author's
Ed25519 identity.

Retries use bounded existing channels (no per-packet spawned task), send only to
cached Engine-verified connected routes, and persist successful attempt counts.
Missing routes remain pending. Native DHT requests obey the serialized-value
hash key, 2048-byte maximum and 86400-second TTL. Closed/full queues or oversized
objects do not become `SentToDHT`; even successful enqueue stays Pending because
it is not remote delivery. Historical valid `SentToDHT` entries return to Pending
on reopen. Chat SYNC is explicitly reported unsupported; no DHT GET/inbox
inventory implementation is claimed.

Three added Rust negative/contract definitions use real sled and channels:
capacity failure emits neither UI nor ACK; closed DHT/oversized payload remains
pending across reopen; successful DHT enqueue has the actual native key/size/TTL
but does not claim delivery. They were not run locally. Full Chat peer-identity
ACK/retry end-to-end verification and persistence I/O fault injection remain
unverified; the real capacity failure test is not a disk-failure simulation.

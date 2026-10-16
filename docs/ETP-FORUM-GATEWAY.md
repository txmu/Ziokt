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

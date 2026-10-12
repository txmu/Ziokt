# ZFCP/1 native-v1

Canonical source is split into provider, operation, data, native transport,
recovery and governance runtimes. tools/sync_providers.py vendors the same code
into S, embeds it in C's one production file, and generates Ziokt's zipapp-safe
runtime. --check detects drift. Native projects do not need this checkout.

Requests have exactly protocol/request_id/federation_id/provider_id/method/params/
deadline_ms/nonce. One JSONL record plus EOF; duplicate keys, floats, unknown fields,
non-NFC strings and excess bounds are rejected. Local nonce correlates the request;
remote use requires the separate mTLS API and scoped persistent replay grants.

Read methods: capabilities.get, status.get, objects.list, operation.status,
events.list, and C-owned content.get/governance.fact. Write methods:
operation.prepare/commit/abort/reconcile, additionally gated by native action and
resource policies. Operations retain original ownership; no arbitrary argv,

64 KiB requests; 256 KiB responses; depth 16; strings 8 KiB; safe integers;
30 second control deadlines; 4096 inventory objects/native journal entries;
32-step workflows, 250..30000 ms native prepare leases. Snapshot cursors reject
changed inventory. A native crash after an effect leaves durable unknown, with
explicit action-specific reconciliation and committed scoped outbox receipts.

Data consumes the original stream/message application boundary. Directional
AES-GCM, native C signatures/identity pins, bounded fragments and retries,
authenticated version/AAD and optional record-budget padding are identical for
all families. No family selector or Core wire translation is added.

See docs/operations.zh-CN.md for exact native actions, binding/configuration,
workspace, cold recovery, fencing, governance and remote grant use. Stored
metadata, verified signed inclusion, current readiness and actual application
completion are distinct observations.

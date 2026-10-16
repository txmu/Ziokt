# Universal messenger v3 repair

The obsolete inner `sled` feature gate hid this exported module despite the
actual `persistence` feature being enabled. It now uses the real feature.
This is the existing UniversalMessengerFlavor, not a Community state or chain
consensus adapter. Existing APIs and delivery strategy structures remain.

Version/capability 3 signs the complete sender identity, destination/strategy,
message ID, timestamp, content, resource links and options with an explicit
`ETP/UNIVERSAL/MESSAGE/v3` domain. V2 signatures are never silently trusted.
Historical invalid/old bytes move atomically to `quarantined_universal_v2`.
`export_quarantined` writes records as big-endian u64 key length, u64 value
length, raw key and raw value, without authenticating or executing them.
Operators must explicitly archive that history; it is outside the active quota.

Actual execution fixes:

- authenticate before modifying replay state; UUID conflicts reject;
- atomic message/topic writes and flush, 4096 active records;
- bounded decoding, 1024-byte engine frames, 8 topics, 100 peers, 512 incoming
  packets/minute and bounded channels; larger data uses resource references;
- connected broadcast peers replace the invalid `0.0.0.0:0` destination;
- synchronous callbacks enqueue actual packets rather than dropping unpolled
  async futures; sync requests cannot expose direct/private stored messages;
- malformed Bloom filters and excessive control vectors reject;
- rotating exact inventory supplements Bloom false positives, with bounded queues
  and no unconditional synchronization time guarantee;
- owner-reviewed `register_peer` mappings are required for direct/managed routing;
  missing routes return an explicit locally-stored error;
- DHT enqueue uses the existing hash(value)/2048-byte/86400-second contract and
  reports queue failure. Enqueue is not durable remote replication;
- burn-on-read deadlines persist on actual history reads, survive restart and
  expire through poll/reads without spawning one sleeping task per message.
  `try_fetch_history` exposes storage errors; the legacy Vec API logs failures.

Direct messages target the Ed25519 author ID returned by `local_id`, distinct
from a Noise transport ID. Managed relays require explicit destination mappings;
managed plaintext messages require trust in that service. Use the existing
onion/recipient encryption boundary for confidentiality from relays. DeadDrop
publishes through the configured existing KNS domain; local publication is not
proof of remote discovery, retrieval, storage or receipt. No automatic Community
bridge, private-key sharing or transaction mechanism is added.

Two new test definitions cover real UDP signed delivery/replay rejection and
real sled read-deadline cleanup/malformed control rejection. Native Rust tests
must run in CI; local work used rustfmt parsing only. Full multi-node managed/
KNS recovery and every optional resource provider are not claimed verified by
these tests.

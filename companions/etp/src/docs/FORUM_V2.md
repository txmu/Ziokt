# Forum v2

Forum wire version and negotiated capability are now `2` and
`etp.flavor.forum.v2`. Version 1 messages are deliberately incompatible: their
post IDs omitted topic and parent, and their author signatures were not verified.
Existing records are never trusted merely because they are present in sled.
Reads validate v2 IDs/signatures/TTL. On open and during cleanup, untrusted
historical/malformed records move atomically into `quarantined_posts_v1`, retaining
the exact original key and bytes. No old post is deleted or automatically trusted.
`ForumStore::export_quarantined_posts(writer)` exports each record as an eight byte
big endian length followed by bincode `(Vec<u8> key, Vec<u8> value)`. Export is
repeatable and does not delete or republish records. Only expired structurally valid
v2 records follow the ordinary 30 day TTL removal policy.

The canonical bytes are `ETP/FORUM/POST/v2\0`, topic (32 bytes), timestamp
(big endian i64), author presence byte and optional NodeID (32), parent presence
byte and optional parent (32), content length (big endian u64), and UTF-8 content.
The ID is BLAKE3 of these bytes. Signed posts contain an Ed25519 public key (32)
and signature (64) in the existing signature vector; author NodeID must equal
BLAKE3(public key). Anonymous means both absent author and empty proof.
Use `publish_signed_post` with a signing key for authenticated publication.
Attach an existing `EtpIdentity` using `new_with_identity`; the original
`publish_post(..., Some(author))` API signs with that identity when NodeIDs match.
Without an attached identity, the API rejects authored publication because a
NodeID alone cannot sign. `local_author_id()` exposes the attached author ID.
The remote node example derives a stable, domain separated Ed25519 author seed
from its persisted Noise key and constructs the existing `AnchorIdentity`.
The author NodeID and transport NodeID are intentionally different. This attached
identity interface is available with `extensions`; raw SigningKey publication
also works with `persistence` alone. The `calculate_id` API now takes `&self` to
cover every routing field. The example registers Forum v2 as a capability as well
as binding it to the composite's Forum stream.

Connected peers receive immediate pushes. Every 60 seconds, and after reconnect,
all subscribed topics exchange Bloom offers over the full 30 day retention
window. The Bloom budget is 32768 bits with five hash functions (about 2.2%
false positives at the 4096-post cap); it uses 4 KiB before metadata/framing.
Exact inventory (command 4) rotates through up to 32 IDs per offer and
FETCH_REQ retrieves absent posts, so Bloom false positives do not permanently
hide posts. Queue admission failure leaves the inventory cursor unchanged.
Missing parents trigger FETCH_REQ from the sender; periodic topic inventories
retry missing retained posts. A retained child remains valid when its parent
expires; `parent_status` returns `MissingOrExpired` rather than claiming a complete
thread. It reports only the immediate parent, not an authenticated whole tree.
For a stable topic with 4096 posts, a complete exact-inventory rotation needs
128 successfully admitted offers at 32 IDs each. With one successful round per
60 seconds this is about 128 minutes; packet loss, budgets, missing responses,
subscription churn or backpressure can take longer. There is no unconditional
time bound during a continuing partition or overload.
Cross-topic parents are only accepted if their
topic is subscribed. There is no DHT lookup API in FlavorContext; FETCH_REQ is
peer fallback, not a claimed DHT read implementation.

The Engine accepts app-data frames up to 1024 bytes. Forum command 5 fragments
larger packets into 850 byte pieces plus a version, command, full-message BLAKE3
hash, and big endian u16 index/count. Receivers bound reassembly to 128 messages,
40 pieces each, and 60 seconds. Reordered and duplicate pieces are accepted;
conflicting pieces and invalid final hashes are rejected. Incomplete messages
are retried by ordinary synchronization. Complete messages undergo the same
bounded decoding and author verification as direct packets.

Storage caps: 4096 posts, 32 KiB content per post, 30 day TTL, five minute future
clock allowance. Posts and topic indexes update in one sled transaction and
successful writes flush before acknowledgement. Duplicate IDs with different
serialized records are rejected. Subscription count is capped at 64 and active
peer synchronization state at 100. Network admission uses the existing bounded
channel without spawning unbounded tasks. A bounded 512-frame outbox retries
backpressure on poll; per-peer topic cursors resume interrupted topic rounds.
This also handles a caller channel with only one slot without repeatedly losing
the second fragment. Each peer is limited to 512 packets
and 2 MiB in each direction per 60 second window (100 bounded budget entries). Cleanup runs at most once per minute.
Native DHT STORE requires key=BLAKE3(serialized value), at most 2048 bytes and
TTL at most 86400 seconds. Forum now follows that existing contract; its canonical
post ID is distinct from the DHT object key. Larger posts still persist and gossip,
but publishing returns an explicit DHT size error. DHT enqueue failures also state that the post is already
persisted locally; gossip still proceeds. Successful enqueue does not mean that
remote DHT replication has been acknowledged by the existing DHT interface.

Tests in `forum.rs` cover real IdentityManager signing, signature tampering, anonymous proof rules, malformed
Bloom filters, bounded decoding, durable reopen/deduplication, TTL rejection,
DHT channel failure, and actual loopback UDP transport of push, missing-parent
fetch, saturated Bloom inventory recovery, periodic sync, reconnection, reordered
and duplicate fragments, native DHT request limits, and lossless legacy export. They are intended
for CI. No local cargo build/check/test was run; only rustfmt parsing was used.

## Verification boundaries

These test definitions are not an executed acceptance matrix. Full Engine Noise
handshake plus Forum stream routing, Windows/macOS filesystems, crash injection
between transaction/flush, 4096-post capacity pressure, long partitions and
repeated peer churn, DHT remote replication, and any cross-implementation v2
interoperability remain unverified here. This protocol deliberately rejects v1
wire packets; it does not claim v1 peer interoperability. CI must compile and run
the Rust tests. Local checks were rustfmt parsing and whitespace review only.

`network/node.rs` calls poll through session Flavor/CompositeFlavor; session
removal and shutdown now invoke on_connection_close to retire Forum peer state.

## Rust acceptance definitions (all pending CI execution)

| Test | Defined coverage |
|---|---|
| signatures_bind_identity_topic_parent_and_content | Author/key binding, signed field tampering, anonymous proof and legacy proof rejection |
| transactional_store_deduplicates_reopens_and_expires | Atomic store path, duplicate, conflicting invalid record, reopen, inclusive timestamp, expired admission |
| retained_child_reports_expired_parent_without_claiming_complete_thread | Child retention and explicit missing/expired immediate parent |
| legacy_records_are_quarantined_and_exported_without_loss | Raw legacy bytes retained and repeatable export |
| peer_packet_and_byte_budgets_are_bounded | Packet/byte admission budgets and window reset |
| malformed_bloom_and_oversized_post_are_rejected | Malformed Bloom safety, oversized content, trailing-byte decode rejection |
| loopback_push_fetch_reconnect_and_false_positive_recovery | Real UDP two-node push, missing-parent fetch, periodic synchronization, saturated Bloom inventory, reconnect |
| loopback_fragmentation_and_native_dht_store_contract | 32 KiB post over <=1024 byte UDP frames, reverse/duplicate fragments, small-object DHT key/value/TTL, oversized DHT error |
| loopback_single_slot_channel_does_not_starve_fragments | UDP synchronization and publication through capacity-one outgoing channels |
| identity_manager_signs_original_publish_api | Existing ETP identity signing, author mismatch and Ghost rejection (`extensions` only) |
| dht_failure_reports_local_persistence | Closed DHT channel reports partial outcome without losing local post; forged author rejected |

None of these definitions has a local Rust pass result. In particular the suite
does not yet include full-capacity pressure, concurrent writer/poll stress,
malformed fragment hash/count permutations, persistence I/O fault injection,
whole-engine shutdown/rekey regression, or the complete requested acceptance
matrix. Quarantine retains historical bytes separately from the 4096 active-post
budget; operators must explicitly export/archive it to reclaim historical disk
space. This change does not silently truncate historical records to meet quota.

## Additional mandatory definitions (also pending CI execution)

| Test | Defined coverage |
|---|---|
| bloom_budget_has_no_false_negatives_and_bounded_fixture_false_positives | All 4096 inserted IDs present; deterministic 4096 absent-ID fixture stays below 6.25% false positives; 32768 bits/five hashes fixed |
| real_sled_capacity_boundary_preserves_all_admitted_posts | 4096 actual save/flush operations, duplicate at cap, rejected 4097th post, reopen retains all admitted posts/indexes |
| concurrent_publish_uses_real_sled_atomic_indexes | 16 Tokio publishers/128 real API publications on four threads; full post/index counts and durable reopen |
| corrupted_lengths_and_bytes_are_quarantined_across_reopen | Corrupt bincode string length and truncated garbage preserve exact original bytes in quarantine through two reopens |
| cross_protocol_signatures_and_retargeted_parent_proofs_are_rejected | Valid actual ChatMessage signature cannot authenticate Forum; signed parent target cannot be changed; invalid parent cannot appear available |
| independent_engines_route_forum_over_real_noise_udp_streams | Two separately configured real Engine instances, pinned Noise keys, actual UDP sockets, Composite stream 3 routing, initial synchronization, fragmented signed reply, return publication, graceful close callbacks |

The Forum Rust suite now defines 17 tests (16 when `extensions` is disabled).
None was executed locally. The real Engine test is a test definition, not a
claim that Noise/Forum interoperability has already passed. The earlier list of
unverified acceptance areas continues to apply until CI or an authorized native
runner supplies actual execution evidence. Full-capacity and concurrent tests
are now defined, so their remaining gap is execution rather than missing code.

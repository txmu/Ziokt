# Community validation and recovery follow-up (2026-10)

This review covers the existing Community event/checkpoint interfaces. It does
not create a bridge to ETP Forum or place Community posts on the Corium chain.

## Corrections

- A persistent delivery receipt records a past acknowledgement. It cannot prove
  that a peer still retains the event after database loss or backup restoration.
  `push_remote` now suppresses uploads only after a fresh authenticated status
  reports the same complete inventory. A different inventory causes bounded,
  idempotent retransmission of this writer's current-policy events. Writers
  without replication permission retransmit without using privileged status.
  Existing receipt rows remain readable; no database migration is necessary.
- Event admission and checkpoint import validate reconstructed plaintext file
  length and SHA-256 against the signed manifest, in addition to ciphertext
  addressing and AEAD authentication. Import rejects inconsistent manifests
  before inserting records or staging their content. File limits are taken from
  the event's signed policy, so smaller limits in a later policy do not erase
  valid historical records.
- Signed malformed policy references and parent/checkpoint identifier lists
  reject non-string entries with a protocol error rather than an unhandled
  unhashable-value exception. Policy privacy values receive the same type check.
- Historical keys temporarily adopted while validating a checkpoint roll back
  on rejection, preserving the finite receiver keyring budget.
- A historical identity record remains available for audit after revocation,
  but automatic mailbox lookup rejects a recipient absent from current policy.
  Stale local handles also reject lookup after policy advancement.

## Existing boundaries retained

Events retain separate signature domains, community/policy scope, immutable
ciphertext identities, causal parent validation, and per-domain author rights.
Deleting another author's data requires explicit moderation permission; deletion
is a signed head, not erasure of history. Concurrent heads are retained until an
explicit merge. Checkpoints require a currently authorized recovery signer;
ordinary submission does not acquire recovery authority. All members holding a
community encryption key can decrypt that epoch's shared community ciphertext;
revocation cannot retroactively revoke copied keys or plaintext. Confidentiality
rotation must distribute a new independent key to retained members.

A matching inventory proves matching local retained objects at observation time.
It is not a promise of future availability, independent failure domains, or chain
consensus. Mismatched inventories may retransmit already stored events; storage
admission remains idempotent and does not discard concurrent versions.

## Added evidence

- Real isolated mTLS exchange: acknowledgement lost after durable event admission;
  replay does not duplicate the event. The peer's records are then removed and
  its database reopened with the same node origin; the retained sender restores
  the missing event despite prior successful receipts.
- Actual signatures and encrypted frames: malformed parent/checkpoint lists,
  inconsistent file length/digest, and current signed policy file-size limits
  are rejected without importing invalid records.
- Forum moderation rejects unauthorized edits/deletion and retains both an
  authorized deletion head and a concurrent offline edit for explicit resolution.
- Revoked mailbox bindings remain in signed history while both current and stale
  recipient lookup paths reject access.

These tests exercise Community's Python implementation with temporary SQLite/CAS
storage and local TLS sockets. They do not establish ETP propagation, Corium
consensus continuity, or resistance to global traffic analysis.

## Three-node controlled fault matrix

`test_three_node_fault_matrix_partition_reorder_restart_and_checkpoint` adds
three real TLS listeners, three independent SQLite/CAS roots and authenticated
checkpoint/event traffic. Nodes run as separate services within one test
process, using the fixture's authorized recovery principal. A real local SOCKS
forwarder injects path failure; no external Tor or internet service participates.

| Scenario | Observed/asserted behavior |
|---|---|
| Baseline replication | All three retain the signed ancestor and encrypted file |
| All configured paths partitioned | All six directed synchronization attempts fail; local editing remains available |
| Offline concurrent changes | Each node creates a distinct branch; no branch is silently overwritten |
| Child delivered before parent | Receiver returns `MISSING_PARENT`, retaining its prior head |
| Reconnection and duplicates | Causal retransmission succeeds; duplicate event adds zero records |
| Partition recovery | All inventories converge with three concurrent forum heads intact |
| Peer service/database outage | Synchronization reports failure rather than claiming retained availability |
| Same-endpoint service/database restart | Retained inventory is recognized after restart |
| Cold checkpoint recovery | Another temporary database recovers matching inventory and original file bytes |
| Corium block confirmation | Not asserted; restored state still requires native application and grants no global consensus claim |

This complements the existing keyless-relay and native collectible multihop
failure tests. It does not test every companion under partition or model
independent physical failure domains.

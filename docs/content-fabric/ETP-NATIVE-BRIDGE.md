# Native ETP Forum / Netnews content adapter

`ziokt.content_etp.EtpNews` consumes the pinned native `EtpGateway` (or the
existing application router's approved ETP methods). It does not implement an
ETP Forum, signer, DHT, transport or file store in Python. Native signed-post
readback is mandatory after publication; local admission never claims remote
peer delivery.

## Mutual authorization

An ETP identity signs a one-day maximum offer addressed to a particular Content
Fabric public key/account, public newsgroup and native topic. The receiving
account must explicitly accept it. Acceptance verifies the native signature via
the original Forum store, checks topic/account/service scope, and signs a local
authorization record with the existing node key. Revocation and expiration stop
subsequent imports/exports; identity rotation requires a fresh offer.

For a source native identity and a different target content node:

```python
source = EtpNews(source_fabric, source_pinned_gateway)
offer = source.offer_authorization(
    "target-account", "configured-native-author", "native-topic", "news.group",
    target=target_fabric.public, expires=expiry, allow=True)
# Transfer the offer reference through the native mesh; availability must be checked.
target = EtpNews(target_fabric, target_pinned_gateway)
grant = target.accept_authorization("target-account", offer["native_proof"], allow=True)
target.ingest("target-account", grant["id"], native_post_id)
```

Local native identities can authorize both directions with `authorize(...)`.
Only the configured native signer matching the grant may export. A remote grant
cannot make the receiver sign as somebody else's ETP identity. Private groups
are rejected by this initial public-content profile.

## Content and recovery

Outgoing articles retain Message-ID, subject/body, references and the original
Content Fabric signed event. The native post carries that typed reference;
large file bytes are not copied into Forum text. Receiving nodes require pinned
Content Fabric source keys and verify its source signature/digest/body in
addition to the native author/topic grant. Plain signed native Forum posts are
imported with deterministic Message-IDs and explicit native-author attribution.

Replies wait for parent mappings instead of silently losing thread references.
Duplicate native IDs and Message-IDs are checked. Imported content is not
exported back to its native origin. All mappings, native timestamps, immutable
publication bytes, failures and grants persist locally. A readback interruption
can be retried with identical native timestamp/content, yielding the same signed
native ID. Changed source events become explicit conflicts during recovery.

`recover(owner, grant)` retries bounded prepared/failed jobs and reports each
outcome. It never converts a newer source version into success for an older job.
`revoke(owner, grant)` records local revocation without deleting existing native
posts. Withdrawal publishes a signed append-only withdrawal notice referencing
the original native post; an authorized receiver applies its own local tombstone.
The immutable original native Forum post is not physically deleted. Arbitrary
native applications need to understand withdrawal notices to hide them.

Attachment references are carried on export. Import refuses attachments until
native object source authorization and retrieval complete; it does not claim
successful attachment synchronization. ETP FileShare/DHT file-source adaptation,
automatic native topic scanning/cursors, edit-conflict reconciliation and a public
GUI/API binding remain incomplete. This adapter is an opt-in local library API,
not an automatically enabled bridge on production services.

## Persistence and verification

Adapter migration 7 creates additive `etp_content_grants`, `etp_content_jobs` and
`etp_content_links` tables only when the adapter is explicitly instantiated.
Nested Content Fabric mutations now use savepoints so importing a post and its
mapping commits atomically. Existing application protocols and ETP canonical
post format are unchanged. The native publication API accepts an optional signed
timestamp; ordinary callers retain the original current-time behavior and the
native store retains its original TTL/signature validation.

Back up the content root and native ETP state together. To roll back, stop the
bridge, retain all journals/tombstones, and use a pre-bridge application build;
independent ETP and Library/Netnews remain available. Do not erase failed jobs or
revoked grants to manufacture a clean synchronization state.

CI extends the existing actual two-node ETP mesh smoke with two separate Content
Fabric stores, native authorization offers, article/reply exchange, withdrawal,
revocation, loop suppression and an injected readback interruption followed by
actual native retry. Its result must be obtained before marking native interop
verified. Local unit tests cover denial and transaction rollback, not native mesh
success.

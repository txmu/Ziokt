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

## Authenticated application API and MCP binding

The independent content service optionally accepts:

```json
{
  "native_etp": {
    "gateway": {
      "binary": "/owner/native/ziokt_gateway",
      "digest": "sha256:APPROVED_BINARY_DIGEST",
      "config": "/owner/private/etp.json"
    },
    "accounts": {
      "alice": {
        "aliases": ["author"],
        "topics": ["native-topic"],
        "groups": ["news.group"],
        "remote_authors": ["APPROVED_REMOTE_NATIVE_AUTHOR_ID"]
      }
    }
  }
}
```

The supplied binary/config use the existing pinned native process boundary.
Activation is lazy: an offline/missing ETP component does not prevent independent
Library/Netnews operation or reading local adapter status/revoking local grants.
Each authenticated account has explicit native signer/topic/group/remote-author
allowlists. A content token does not grant access to another account's native
signers. Offers to remote Fabric services require pinned target services.

The shared authenticated HTTP/MCP registry now exposes `content.etp.status`,
`authorize`, `offer`, `accept`, `export`, `ingest`, `revoke`, and `recover`.
Read status requires `content:read`; mutations require `content:write` plus the
actual per-account native delegation. Caller-supplied account overrides are not
accepted; `target_account` on an offer names the explicitly intended remote
recipient and requires that recipient's independent acceptance.

Missing adapters/offline native files return explicit unavailable errors;
unauthorized aliases, groups, authors and grants are denied. Native keys never
enter HTTP/MCP arguments or Content Fabric state. The adapter's server-owned
native process is closed with that application server. An existing independently
managed native service is not reconfigured or stopped.

The native mesh CI additionally invokes the real authenticated content HTTP API,
publishes a real Netnews article to the same already pinned native node, observes
it on the other real native peer, and tests API revocation. Local API tests cover
unassigned aliases and an actually missing native executable; these are denial
and offline tests, not simulated native success.

## Bounded native inventory and durable polling cursors

`etp.forum.scan` now obtains a signed/TTL-validated topic-and-author inventory
from the **original native Sled store**, with pages of at most 64 IDs and a
versioned BLAKE3 snapshot identifier. It creates no duplicate Forum index or
transport. The original store's 4096-post cap bounds scanning. A changed snapshot
returns an explicit reset state; timestamps are not used as arrival cursors, so
late arrivals carrying older valid timestamps are discovered on the next scan.

`content.etp.sync` admits each native page and its cursor into a durable local
queue transaction. Replies waiting for unmapped parents stay pending and retry
fairly. Authorization records are typed non-content records. Applied, ignored,
waiting-parent, waiting-attachment, rejected and failed items remain distinct;
`scan_complete` never implies `content_complete` when queued work remains.
Snapshot resets and partial processing never return content-complete success.
Each completed cycle restarts inventory discovery, while persisted IDs/mappings
prevent duplicate articles. Fresh grants in the same account/topic/group can
recognize previously imported native identities without silently changing scope.

Migration 8 adds `etp_scan_cursors` and `etp_scan_queue`. Preserve these journals
and adapter migration 7 during rollback; automatic background polling is still
an explicit operator scheduling responsibility. Native capability is established
by actually invoking the scan endpoint, not merely by finding configuration.
The CI suite tests original-store late arrivals, actual cross-node snapshot
reset, unmapped-parent errors and eventual durable queue convergence.

## 原生断连恢复补强

原生网关的 Forum 发送队列不再因单个 send_stream 失败而退出整个消费循环；仅对已固定公钥的配置对端尝试重新连接，同一对端最多每 5 秒一次，每次等待上限 1 秒。内容仍由原生 Sled/inventory/anti-entropy 处理，不创建替代 Forum。测试保留真实远端帖子断言，等待窗口覆盖原生 60 秒 anti-entropy 周期（75 秒），不把本地发布或调用返回当成远端同步成功。

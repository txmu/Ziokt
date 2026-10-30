# DNA 原生消费组件 / Native DNA consumer

`ziokt/dna_consumer.py` implements an optional, persistent RNA inbox and confirmed
local Corium chain consumer. It never interprets a message as a shell command.
The default installer delegates **status.get only**, to existing native providers.
Corium and Shadow6 remain independently runnable.

## Trust and execution

The operator pins the native SQLite chain path, genesis, confirmation count and
start height in `chain_source`. This is the local native validator's database,
not an arbitrary remote SQL feed. Only `ziokt_content` transactions listed in the
corresponding confirmed block, with content type
`application/vnd.ziokt.rna+json`, are eligible. Their `text` contains the RNA frame.
The RNA chain domain is the independent recovery declaration ID from native DNA
work proofs; its policy domain is the native work policy commitment. A shared
historical genesis alone does not distinguish the DNA chain from the main chain.
Each consumed block must match both pinned domains and the DNA proof schema.
A consumed-block reorganization halts ingestion and dispatch for operator review.
There is no automatic rollback of already committed external effects.

RNA frames require the pinned secp256k1 sender, chain and policy domains, increasing
sequence, payload commitment and 120-second validity window. The consumer checks
signature and stored-command integrity again before dispatch. Producer revocation
and native provider authorization are checked at execution time. Expired queued
commands are rejected. Previously dispatched uncertain writes stay `unknown` and
are reconciled using the deterministic native operation ID; they are never
reported as successful merely because the inbox accepted them.

The 120-second window also applies to chain-delivered commands. Slow inclusion or
confirmation can cause rejection. Do not extend freshness or skip confirmations
to make an acceptance test pass. A sender must allow sufficient time for both.

States distinguish `queued`, `completed_read`, `native_committed`, `unknown`,
`retry` and `rejected`. Native commitment does not establish application readiness.
The consumer always reports `application_ready:false`. Completed reads contain
the actual native status response. Journal quota is 4096 jobs; exhaustion pauses chain cursor advancement. Retention requires
operator archival, never silent deletion of replay protection.

## Installation

Run as the intended service account, against an already approved federation:

```sh
python3 tools/deploy_dna_consumer.py --root /private/dna-consumer \
  --federation /private/federation.json --chain-database /native/blockchain/chain.db
```

The tool writes a reviewable systemd unit and isolated runtime. Enable it with the
normal service manager. It preserves an existing consumer configuration on rerun.
Its generated producer key stays mode 0600 on its originating host; it is a new
component credential, not a replacement for production chain or app keys. The
consumer binds only `127.0.0.1:8189`. `/rna` requires the full signed envelope;
`/status` exposes aggregate queue counts only. Browser-origin requests are denied.

`tools/probe_dna_consumer.py --root /private/dna-consumer` obtains genuine native
read receipts through signed loopback RNA ingress. It explicitly does **not**
claim chain inclusion, public connectivity or cross-host delivery.

For mutations, the generic dispatcher uses existing native prepare/commit/
reconcile gates for `content.publish`, `wiki.create` or `artifact.stage`, only if
both producer delegation and native policy explicitly allow them. The deployed
status-only configuration does not grant these actions. Package execution and
financial operations are not supported consumer actions.

## Verification and rollback

```sh
PYTHONPATH=.:tests python3 -m unittest test_dna_consumer -q
```

The six targeted tests cover real native status RPC, real RNA signatures,
persistent replay/duplicates, revocation, expiry, journal tampering and confirmed
source/reorg handling, plus repeat installation over a read-only runtime without credential rotation. The chain-source unit test uses an isolated SQLite fixture;
it is not evidence of public mainnet acceptance.

Rollback: `systemctl disable --now ziokt-dna-consumer`; keep its private state,
producer key and config for audit/replay protection. Remove only its dedicated
unit/runtime after archival. No consensus rule, production key, asset semantics or
existing service needs changing to remove this optional component.

## 本轮部署证据 / Deployment evidence

2026-10-30：两端均部署独立 `ziokt-dna-consumer` 服务，默认只读。
本机已通过真实 DNA 交易、确认区块、RNA 验签及 Corium 原生读取的完整路径；
对端已通过真实签名 RNA 收件和 Corium 原生状态读取。
具体交易及高度见独立验收记录；DNA 两端同步与跨节点链上消费仍需另行验收。
停止并禁用消费服务即可回滚，不修改链共识或应用生产密钥。

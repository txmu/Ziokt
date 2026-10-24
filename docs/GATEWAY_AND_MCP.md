# Native gateway and MCP delivery

This implementation follows `ZIOKT_GATEWAY_ARCHITECTURE_AND_ROADMAP.md`.
Native compilation belongs to GitHub Actions. Local deployment uses interpreted
Corium/Python and exact-digest native ETP products from a successful CI run.

## Entry points

- `python -m ziokt gateway bootstrap --root RUNTIME --state-root CORIUM_STATE --corix CORIX --network NETWORK --publish --install`
- `python -m ziokt gateway publish-file --config RUNTIME/config/gateway.json FILE`
- `python tools/configure_mcp_gateway.py --root RUNTIME/mcp --issuer https://DOMAIN --federation RUNTIME/config/federation.json --gateway RUNTIME/config/gateway.json --bridge watchat=EXISTING_BRIDGE --bridge sim-manager=EXISTING_BRIDGE`
- `python -m ziokt mcp serve --config RUNTIME/mcp/mcp.json`
- `python -m ziokt mcp telegram-worker --config RUNTIME/mcp/mcp.json`
- `python -m ziokt mcp stdio --config RUNTIME/mcp/mcp.json` with an explicit
  `ZIOKT_MCP_CLIENT` and `ZIOKT_MCP_TOKEN` in the process environment.
- `python -m ziokt mcp catalog --config RUNTIME/mcp/mcp.json`
- `python tools/package_joint_source.py --output /PRIVATE_OUTPUT/joint-source.zip`

The network must first be initialized with native Corium tooling. Bootstrap
publishes standard NNS/DApp objects; changes to owned NNS names produce signed,
owner-checked `nns_update` transactions. Missing names use native registration
and require sufficient contribution balance. Bootstrap never invents balances,
changes existing owners, or bypasses consensus. New defaults appear locally
following signed submission; finality still depends on the native chain.

`gateway/caddy/Caddyfile.template` and `gateway/systemd/` are versioned deployment
inputs. Merge the gateway routes into an existing Caddy site before restarting
Caddy. Set its domain explicitly. The production host retains its existing TLS,
chat, simulation, UFS and Effort sites. MCP adds `/mcp`, `/oauth/*`, and the two
OAuth discovery endpoints; all backend listeners bind to loopback.

## MCP protocol and authorization

The bridge implements MCP **2026-07-28**, including `server/discover`, per-request
protocol/capability metadata, mirrored header/body validation, `resultType`,
stateless JSON Streamable HTTP, tools, and resources. It also accepts the
**2025-11-25**, **2025-06-18** and **2025-03-26** initialization and tool/result shapes. Optional SSE notifications,
tasks, sampling and elicitation are not advertised. GET/DELETE on `/mcp` return
405. Unsupported versions return `-32022`; mirrored headers use `-32020`.

Sources: [transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http),
[authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization),
[official schema](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2026-07-28/schema.ts).

OAuth uses registered exact redirect URIs, explicit node-administrator consent,
PKCE S256, state and issuer validation in the browser, 120-second single-use
authorization codes, 15-minute access tokens, rotating one-day refresh tokens,
resource-bound token hashes, discovery, revocation, and read/write/action scopes.
Client removal and scope revocation are checked against the current private
configuration. Native writes recheck grants and token expiration between steps.
Tokens are never accepted in query strings or forwarded to component backends.
The administrative `issue-token` command is local owner-only; redirect its output
to a mode-0600 file. It is intended for headless operator provisioning.

The browser portal uses the registered `ziokt-browser` client. The headless
`ziokt-reader` and `ziokt-operator` clients default to a fixed loopback callback;
operators can explicitly register other exact redirect URIs in private config.
Administrator consent is required even for the browser client. Public forum
users separately sign posts with browser-owned, non-extractable Ed25519 keys.

Native Shadow6/Corium tools preserve provider digest pins and native mutation
policy. Per-action `*_plan` tools produce caller-owned workflows; apply requires
the exact plan digest and `confirm: true`. Mutating MCP calls automatically derive a transport request key. For retries across
requests, supply `idempotency_key` or `_meta["ziokt/idempotencyKey"]` (16–128 safe
characters); duplicates reuse the result, conflicting inputs fail, and uncertain
outcomes require reconciliation. Annotations reflect
mutations, including local inbox imports. Tools accept fixed typed operations,
never arbitrary host commands, paths, SQL or target URLs.

A private SQLite journal stores token hashes, request digests, idempotency state
and audit outcomes. Payloads and bearer tokens do not enter request logs.
Per-client requests are rate-limited, HTTP concurrency and message/result sizes
are bounded, and invalid Origin/Host headers fail closed. Revoked refresh-token
reuse is rejected; this server does not implement refresh-family compromise
tracking or externally federated OAuth identity providers.

## Component paths

All eleven component identities have separate signing/mailbox keys and pinned
recipient grants. Existing WATChat and SIM bridges retain their application state
and vault keys. A shared encrypted exchange community supplies recipient-only
component offers; exchange adapters write received artifacts into the intended
application vault. Receipt import does not execute code or activate a service.

The catalog exposes native provider reads and reviewed operations; encrypted
vault put/get/publish; recipient-scoped send/receive; signed DCPM build/verify;
Tri projects; SIM reminders; opaque WATChat messages/acknowledgments; Ano/ZDA
calculations; bounded TC-16 execution; signed forum publishing; file manifests;
and explicitly configured ETP onion/forum operations. Unsupported inbox and
application-specific methods are omitted. The catalog only advertises native
ETP methods when an exact-digest native binary/configuration is configured.

## FileShare v2

- Normalized gear-based CDC uses 1 MiB minimum, 4 MiB target and 8 MiB maximum.
- `ziokt.manifest.v2` is a bounded, hierarchical 128-child Merkle tree. Publishing
  retains O(tree depth × fanout) metadata rather than a whole-file index.
- SHA-256 addresses preserve Corium interoperability; ETP v1's existing BLAKE3
  wire format remains compatible. V2 travels through native ETP encrypted
  records, with 56 KB segments and a four-request window per object.
- Gateway download uses a bounded ordered chunk window, verifies each object,
  retries alternate configured HTTP peers or ETP paths, and never stages a
  downloaded file. Only publication intentionally persists content.
- `/stream/HASH` supports normal, open-ended and suffix byte ranges, 206/416,
  HEAD, ETag/If-None-Match and If-Range. One range is served per request; multipart
  ranges are rejected. Missing later objects close the stream so clients can
  resume with Range. Object-size limits bound memory, not total file size.
- Native `/chunk/HASH` verifies local ranges in two passes without a download
  temporary file. Historical signed aliases use a bounded compatibility verifier.

`tools/configure_etp_bulk.py` configures v2 from a supplied CI binary and reviewed
SHA-256. Its initial four-node loopback topology exercises three real native hops;
operators must supply actual remote peer configurations for multi-host redundancy.
The gateway accepts additional explicit client/source routes. HTTP Swarm origins
are operator-pinned; there is no silent direct fallback for an ETP-only route.

Public-media playback uses browser-native Range support. Encrypted-media Wasm
codecs and MSE format adapters remain optional extension work: no fake decoder or
unsupported confidentiality claim is shipped. The Python stream is bounded and
avoids disk assembly, but it is not a kernel `sendfile` zero-copy implementation.

## Validation and packaging

Gateway/MCP tests exercise real SQLite, HTTP, Ed25519, OAuth PKCE/replay/revocation,
scopes, durable idempotency, Merkle subtree reads, alternate-peer recovery and
zero download disk writes. The browser smoke covers actual WebCrypto signatures,
escaped content, language switching, mobile layout, OAuth callback, tool execution
and revocation. Native ETP smoke transfers a 2 MiB object through three actual
native hops and checks that no download object was written.

`gateway.yml` runs the focused tests and browser flow. The existing companion
workflow builds/tests native ETP in CI. The federation workflow checks pinned
native sources, runs the full native suites, and emits the joint text-only source
archive alongside native artifacts. Unchanged Shadow6 Core products retain their
existing verified CI reuse path; no local heavyweight build is necessary.

The joint-source packager includes the current tracked and nonignored source
state of all three repositories, including vendored companions. It excludes
build products, environments and private runtime state, applies Shadow6's UTF-8
`.txt` exchange contract in a temporary tree, runs `archive_preflight.py`, then
atomically installs the archive and writes a SHA-256 sidecar. A provenance file
records exact commits and working-tree changes. Production credential/data
backups are intentionally separate from the source exchange artifact.

## Production ChatGPT connection

Canonical MCP endpoint: **https://mcp.ziokt.com/mcp**. In ChatGPT custom MCP/app
settings, add that URL and select OAuth with Client ID Metadata Document (CIMD).
No pasted client secret is needed. The server accepts the official ChatGPT client
metadata URL, validates its exact client ID and official redirect, requires PKCE,
and shows a node-administrator authorization form. Use the owner token stored
locally in `RUNTIME/config/admin_token.key`; never put it in a URL or source archive.
Completing authorization in the user's ChatGPT account remains an account action.
Public deployment verification tests TLS, the real ChatGPT metadata document,
PKCE authorization, native tools, writes, deduplication and token revocation.

Provision separate domains with `--portal-origin https://cor-web.ziokt.com`.
Both exact hosts are pinned while the MCP issuer stays canonical.
The browser portal uses an exact registered callback on the portal origin and
explicit CORS with the canonical MCP issuer. The authorization document preserves
a same-origin form Origin and its CSP permits only the exact registered callback
in addition to the issuer, including Chromium redirect enforcement. The CI browser
fixture runs portal and issuer on separate origins; the operator-only
`tools/gateway_public_browser_smoke.cjs PORTAL_ORIGIN MCP_ORIGIN TOKEN_FILE`
validates the actual public HTTPS cross-origin flow without printing credentials. Owner-approved OAuth grants include
all enabled tools. Production native Corium and Shadow6 provider mutation policy
is explicitly enabled for that owner; distributed default builds keep their
original least-privilege policy. `ziokt_audit_read`, `ziokt_client_revoke` and
`ziokt_client_restore` require `ziokt:admin`; reader grants exclude that scope.
CBB tools invoke the original signed, expiring Corium emergency bulletin verifier,
native bulletin broadcast/sync and signed game state/actions. CBB is not consensus
finality. Phoenix proposal/notarization routes use the original native verifier.

## Owner-approved chain and PoUW weight registration

Public application form: `/gateway-assets/registry.html`. Anyone can create a
browser-owned Ed25519 identity and submit an exact-schema, network-bound,
five-minute signed application. Nonces reject replay; IP/signer limits and pending
application quotas bound submissions. No anonymous read creates a registration.
Public `GET /api/gateway/registrations` returns only approved entries. Public signed
POST uses `/api/gateway/registrations`; node-owner bearer authorization also
supports submission and `/api/gateway/registrations/decide`.

MCP tools are `corium_registration_submit`, `corium_registration_list` and
`corium_registration_decide`. Submission and reads have separate scopes; only
`ziokt:admin` can approve/reject/revoke with `confirm: true`, registration ID and
exact immutable digest. Non-administrators can see approved entries and their own
pending/rejected applications, never other applicants' private pending requests.
The owner can inspect all requests through the existing Corium MCP console.

Entries require `kind`, `target` (lowercase stable identifier), `description`, and
integer `weight` (1–1,000,000). `external_chain` additionally requires `genesis_hash`
and `verifier_hash`; `pouw_engine` requires native `pkg_id`, `compute_program_hash`
and `verifier_script_hash`. All hashes are 64 lowercase hexadecimal characters.
External-chain approved weights are a Gateway eligibility registry, not a change
to Corium's consensus fork-choice weight or automatic trust in external proofs.

PoUW approval submits a real node-signed `propose_new_compute_engine` transaction
and records its transaction hash. Native contribution eligibility, validator vote
and enactment delay remain mandatory before execution becomes active. Native
transaction application now persists `reward_weight`; scheduled governance now
actually activates the engine while preserving the approved integer weight. The
existing native reward arithmetic/units are retained. Registry `effective` means
owner whitelist eligibility; `activation: native-governance-required` explicitly
distinguishes it from chain activation. Revoking registry membership removes it
from Gateway eligibility; it does not rewrite finalized chain state or deactivate
an already activated native engine. Those changes require native governance.

A durable `submitting` state prevents blind replay after uncertain native writes.
The owner must reconcile the native mempool/chain and registry journal for such
cases; no automatic second proposal is emitted. Applications, immutable digests,
actor transitions and native receipts live in the private mode-0600 registry DB.
Tests cover unauthorized approval, malformed weights/hashes, digest substitution,
duplicate targets, revocation, real browser signatures/replay and native scheduled
engine activation against real SQLite.

## Telegram Bot MCP integration

For ChatGPT compatibility, the endpoint accepts unauthenticated MCP `initialize`
and `tools/list` bootstrap requests and declares OAuth per tool. Other protected
operations still require a valid scoped bearer token.

Telegram is optional and disabled until an owner supplies a BotFather token and an explicit numeric chat allowlist. Configure an existing production MCP server without putting the token in shell history or command-line arguments:

```bash
cd /home/admin/Ziokt
python3 tools/configure_telegram_bot.py \
  --config /home/admin/.local/share/ziokt-production/mcp/mcp.json \
  --chat-id YOUR_NUMERIC_CHAT_ID
```

The script reads the token without echo, verifies the bot with Telegram, stores it in `mcp/telegram/bot.token` with mode `0600`, adds `telegram:read` and `telegram:write` only to the operator/browser grants, installs and starts `ziokt-telegram-bot`, restarts `ziokt-mcp`, and checks both services. Add one `--chat-id` for every allowed private chat or group; groups also need explicit `--user-id` sender grants. The token file and Telegram configuration are runtime secrets and are excluded from source packages; the sanitized configuration reference has no live bot credential. Do not configure a Telegram webhook for this polling integration; `telegram_bot_status` reports whether an existing webhook prevents polling.

The MCP catalog provides bot/webhook status, filtered updates, chat and member reads, text send/edit/delete, allowlisted forwarding/copying, Telegram `file_id` photo/document sending, location and poll sending, callback answers, pin/unpin, and group title/description changes. The API host and method set are fixed; there is no arbitrary URL, file path, token, or Bot API method input. Read tools require `telegram:read`; all remote writes require `telegram:write`, normal MCP write enablement, and idempotency. Every source and destination chat is checked against the allowlist. Media tools accept Telegram `file_id` values and do not upload arbitrary local files or fetch user-supplied URLs.

Telegram Bot API reference: https://core.telegram.org/bots/api

The owner can also use Telegram as a live command surface. `ziokt-telegram-bot`
long-polls only configured chats and allowed sender IDs, persists accepted updates
for the MCP inbox, and replies to `/start`, `/help`, `/status`, and `/tools`.
Common short tool names are installed in Telegram's command menu; every catalog
tool remains callable as `/mcp TOOL_NAME {JSON}` (or directly as `/TOOL_NAME`
when its name fits Telegram's command rules). `/tools`
paginates the full catalog and `/help TOOL_NAME` shows its schema. Mutating tool
calls return a one-time confirmation code and execute only after `/confirm CODE`.
For private chats the numeric chat ID is also the owner user ID; group deployments
must separately configure `allowed_user_ids`. Other senders receive no response.


### OpenCI签名回执同步（2026-10-22）

复用既有 `ziokt_components` 和 `ziokt://components`，返回当前冻结源码版本及 `source_features.openci` 的回执格式、签名域、任务/输入/租约/产物绑定字段和原生dCPM来源记录能力。该字段明确是源码能力：Controller实际在线、远端Worker与恢复不据此认定；链上共识结算标为not_implemented。未新增重复工具或放宽读写scope，工具总数仍462，目录从真实Service重新生成。TG使用同一MCP源码版本，未发送测试消息。详见 `openci/WORKER-RECEIPTS.md`。

Persistent RNA/OpenCI state uses the MCP state's private protocol.sqlite. Configure
`protocol_state.signing_key` with this node's existing SECP256K1 owner key and
`protocol_state.ownership_db` with its native NNS database; replay sequences survive
restarts. Native genesis reservations with zero expiry retain their explicit
perpetual semantics. Other expired ownership records are rejected. Pin chain_id
and policy_id to the actual configured protocol domain; source declarations alone
do not activate a new main chain.

With `protocol_state.publish=true`, a durable outbox publishes signed public RNA
records and explicitly requested OpenCI evidence commitments through the pinned
native DHT and content.publish journal. RNA anchors do not overwrite the NNS
website target or its service/delegation manifest. Evidence anchors contain hashes
and a local signature, excluding private result contents; neither is a substitute
for independent worker observations. Publication status distinguishes queued,
peer acknowledged, submitted and actually included in a canonical block. Retries
reuse the same native operation ID. The record's public discovery, local ownership
admission and native content inclusion remain separate facts.

`tools/observe_deployed_chain.py` creates a portable, node-signed observation of
actual canonical checkpoint headers and public recovery authorization fields. It
excludes local database/backup/key paths. Configure `chain_observation` in the
Gateway to display the document alongside live chain identity and work proof;
Gateway verifies its signature and compares every checkpoint header with its own
canonical database. An observation is distinct from an independently replayed
history or activation of the source-defined recovery/DNA networks. Every node can
produce its own observation with its own identity; observing does not grant a
validator role or privileged network authority.

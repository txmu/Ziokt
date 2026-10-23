# Native migration implementation and acceptance boundary

Native source revision is pinned by `native-sources.lock.json`; generated
OpenCI and work verifier sources are checked by `tools/sync_providers.py --check`.

## Implemented, not production activated

- Native testnet governed Work v2 block producer, signed canonical work headers,
  accepted-parent cumulative weight, reorganization validation, DHT proof
  serialization and Phoenix independent replay hooks. Additive block_work table.
- Explicit prior-policy commitment, activation height, full native governance
  delay and governance checkpoint. Mainnet cannot activate these testnet rules.
- Native OpenCI governed bounty receipt validation and ten-block challenged
  settlement to contribution scores, with reward weight bound to signed proposal.
- Controller/CLI `/v1/contributions/prepare` / `contribution-prepare`: export two
  current approved signed Worker receipts into a native submission plan. This
  neither approves governance nor submits or settles the transaction.

## Evidence and remaining gates

Local targeted OpenCI predicate tests: 4 passed. Native contribution exporter:
2 passed (real Ed25519 and SQLite; these tests do not execute OCI containers).
The native CI matrix runs actual governance chains and independent replay for
both OpenCI and Work v2. Workflow submission is not evidence of passing CI.

OpenCI test accounting includes existing IBC postage from automatically emitted
nickname synchronization transactions, read from confirmed native queue entries.
Do not remove those debits or assert a fabricated reward balance.

Still required: passing full native chain CI, real OCI receipt to native chain
combined acceptance, peer partition/reorganization and upgrade compatibility,
difficulty calibration, anonymity migration and its recovery/leakage acceptance.
No mainnet rule switch, shielded ownership activation, token reward or production
settlement is claimed. Production Gateway/MCP/effort deployment remains the
previous frozen revision until replacement acceptance passes. Effort relay and
Engine Zero work are distinct from Work v2 block mining and native OpenCI bounty
settlement. `all_requested_features_complete` remains false.

## Shared user entry points

`/api/explorer/upgrades` reads a bounded snapshot of confirmed native governance
records and completed bounty rows without publishing transaction bodies, source
receipts, private keys or proposal descriptions. The response explicitly leaves
business validation, remote verification and anonymity guarantees unassessed.
Both the effort page and the cor-web portal link to the shared explorer view.
The existing MCP components resource reports the same experimental implementation
boundary without adding or renaming tool IDs. This is source capability discovery,
not a claim that the production controller or consensus has been activated.

The combined CI path now executes two actual OCI tasks, checks artifact bytes,
exports current signed receipts through the authenticated Controller API, then
uses those receipts in the native proposal/vote/settlement/replay flow. Both OCI
containers execute on the same CI host: logical approval domains are not evidence
of independent physical workers. Run 39870216695 is pending full native acceptance.

Wallet recovery additionally rejects future-dated spend images and malformed
canonical head hashes. Six encrypted wallet recovery tests pass, including
rollback rescan and secret-free CLI output. The new upgrade browser view passed
Chromium Chinese/English mobile UI contract checks; its fixture is not native
chain evidence. The API has a separate actual native SQLite read-only test.

Native OpenCI admission now rejects duplicate pending/completed bounty claims,
while allowing only the original transaction to be rechecked or settled
idempotently. Five affected native predicate tests pass. The long CI workflow
queues subsequent revisions instead of cancelling a running chain replay.

## Observed results on 2026-10-23

- OpenCI native acceptance: run 39870919662, job 120145202585, **8 tests
  passed**. Actual OCI receipts entered native governance, ten-block settlement
  and independent Phoenix replay. Corium revision 07281d9.
- Work native acceptance: run 39871283042, job 120148279400, **5 tests passed**.
  Corium de8fae5 differs from the preceding revision only in the corrected
  snapshot contract assertion. These are single-node native chain/replay tests,
  not multi-node partition or mainnet activation evidence.
- Source 43d4e40 deployed to Gateway, MCP, Telegram, Content, OpenCI Controller
  and effort service. Production native entrypoint remains
  sha256:617b76f9b2564ca934fd04ce3e2544e81152e849898c0551326f6167fd09de58.
- `/api/explorer/upgrades` responds on the effort service. The cor-web native
  portal update was submitted as a normal NNS transaction; pending consensus
  confirmation is distinct from a deployed namespace update.
- Frozen deployment execution permissions were found to be lost. The freezer
  now preserves executable files as 0555 and data files as 0444; actual executable
  invocation and SQLite backup preservation pass targeted regression tests.

Separate failures remain: real Tor onion access timed out despite successful
bootstrap (no direct fallback occurred); integrated ETP Forum anti-entropy did
not converge. The portable invitation test randomly wrote an unchanged last
ciphertext byte; deterministic bit-flip now guarantees corruption and its
negative authentication test passes. None of these failures is converted into
an acceptance success. Mainnet work/shielded rules remain unchanged.

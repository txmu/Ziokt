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

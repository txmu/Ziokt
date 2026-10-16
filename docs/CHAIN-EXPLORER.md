# Local canonical chain explorer

Set `"explorer": true` in the owner-private `ziokt.effort-web.v1` configuration.
The existing HTTPS service then serves `/explorer/`, with Chinese and English
UI, twenty-block pages, height/hash lookup, transaction lookup and shareable
fragment links. The effort landing page retains its single computation button.
The explorer page does not start workers or request mining jobs.

The database is selected from the configured Corium provider's state root and
network. Browser input cannot select a path, RPC, SQL query or signing identity.
Connections use SQLite `mode=ro`, `query_only`, a consistent read transaction,
two-second busy timeout and a bounded progress handler. The HTTP service limits
parallel requests and applies a separate 600/minute explorer query budget. The
worker job/proof budget remains separate. Behind a reverse proxy, the budget
currently aggregates requests at its backend address.

Fixed GET endpoints:

- `/api/explorer/summary`
- `/api/explorer/blocks?before=HEIGHT` (twenty rows)
- `/api/explorer/block/HEIGHT_OR_HASH` (at most 100 transaction summaries)
- `/api/explorer/transaction/HASH`

Responses show network, local tip, block references, timestamps, transaction
kind, payload length, inclusion and confirmation depth. They omit transaction
bodies, encrypted gift receipts, public signing keys and signatures. No sender
or receiver address search index is created. `view=local-canonical` and
`irreversible_finality=false` are explicit: a local database view is not an
independent inclusion proof, and confirmation depth may decrease after a fork.
The native authenticated fact interfaces remain available for proof verification.
Missing or corrupt data produces a real error, never an empty successful chain.

For large existing databases, operators should add the native additive index:

```sql
CREATE INDEX IF NOT EXISTS transactions_block_height_hash ON transactions(block_height, hash);
```

The explorer itself never creates the index. Native fresh database initialization
includes it. No signed record, payload or existing schema version is rewritten.

Verification executed: `python3 -m unittest discover -s tests -p test_explorer.py -v`
— **2 passed, 0 failed, 0 skipped**, 4.876 seconds. Tests use a real native Corium
fixture, signed transaction and block production, real HTTP listener, invalid
queries, database damage, readonly state comparison and payload nondisclosure.
Affected effort regression: **4 passed**, 4.428 seconds.

Public deployment also passed real Chromium checks in Chinese/English at a
360px viewport: trusted HTTPS, block and transaction navigation, fragment links,
48px controls, no horizontal scroll, no browser errors, no external requests and
no computation requests. The actual public URL and service details are recorded
in `/home/admin/fendou.txt` on the deployment host.

## Additional read-only features (2026-10-16)

The interface includes genesis/previous/next block navigation, pending and all
transaction views, cursor pagination, the latest 20 blocks' transaction counts,
explicit refresh, and export of the displayed bounded JSON query. Search accepts
heights or normalized digest strings. No address index, private payload, receipt,
signing key, RPC control or mining action is exposed.

`GET /api/explorer/transactions?pending=1&after=<hash>` uses 20-row keyset pages;
`pending=0` (default) lists retained transactions in hash order, not time order.
`GET /api/explorer/block/<height-or-hash>?after=<hash>` continues 100-row block
pages. `GET /api/explorer/activity` reads at most the latest 20 canonical heights.
All queries retain read-only transactions and the existing SQLite work budget.
The browser supports Fetch/Worker-era browsers, feature-detects AbortController,
avoids relying on replaceChildren, handles BFCache restore, and uses accessible
mobile controls. Chromium/Firefox/WebKit UI tests run separately from genuine
Corium database tests; browser fixtures do not establish chain correctness.

# Historical evidence recovery attempt — 2026-10-24

The operator selected evidence recovery before considering any canonical fork.
This attempt is read-only. It does not authorize or perform a recovery branch,
rewrite existing blocks, inject historical state, backdate governance, or resume
consensus. The existing safety hold remains active.

## Search scope and observations

The local search inspected 40 SQLite files: 12 chain databases, 14 forum databases,
and 14 DHT databases, including the production chain, deployment/privacy backups,
the safety-hold backup, and the isolated-transaction backup from October 18.
The available chain snapshots end at heights 57, 59, 61, 782, or 784. All 12 contain
the same height-51 header. These are local copies, not independent witnesses.

None of these chain databases contains a signed canonical block committing either
activation proposal:

- Work v2: `442e314873cb7649ea6b5e8df82a09cb62943c7ef44ed97d6aa0268b9a2835e6`
- OpenCI: `f474e162a8d25ffb47e379cbe2b107f86830f527ea430a03e14d2d3c1ea6100a`

A proposal's own signature or a cached `block_height=1` cannot establish block
inclusion. The height-1 signed transaction list does not contain these hashes.
Restoring their database rows would not fix the activation commitment.

The first application replay failure remains height 51, transaction
`8755a7b527b92125613b1c1fb019d5c454936f7d00dd7ff294dfd89fd44ffddf`.
No scanned chain contains `nns_register` transactions for the nine affected
non-genesis domains: explorer, forum, fileshare, onion, zda, safefs, ufsdcpm, tc16,
and blockchain. The production and saved genesis files are byte-identical
(SHA-256 `6f8cdc6a29994866a90f818996742faa0e692a63db61cf57b61d5c85e5f2cd60`).
Their signed Nomen reservation payload names only corium, nomen, status, and ziokt.
The 20 separately archived isolated transactions are pending NNS updates, not
registrations or governance activation evidence. The restoration script was not run.

Older forum snapshots already contain the missing domains as `ecosystem_app`
rows. These are derived database records without the missing signed registration
history. Git history supplies a plausible explanation for local-only state:
Ziokt commit `f4c9733` adds direct `INSERT INTO nns_records` fallback publication;
commit `00e6d74` removes that fallback and optimistic updates. The earlier published
bootstrap also updated local targets directly. Those source changes explain how
service-visible state could depart from replayed state; they do not prove the
exact code deployed when a particular block was accepted.

Corium commit `2c40b77` adds explicit NNS-update ownership validation and projection.
An archived native script with SHA-256
`0ca16359087e7d45591c9af2f6de526fc48cc6a7110d4694dcc841ef9b5e514a`
already contains that ownership check. An older archived script
`cd68d0c7318379703a94b6c77f5cbf61d0e107b2aff990bc3203d8d64d25cfab`
has no explicit NNS-update branch. Falling through an old unknown-transaction
validator does not reconstruct registrations or define an authenticated historical
activation schedule. Commit dates, archive directory labels, and application
availability cannot substitute for that schedule.

## Result and decision boundary

The search found evidence explaining the divergence but did not recover the
missing canonical registration/governance commitments. Under the current rules,
native application replay has been checked through height 50; legacy headers and
signatures through height 63 were separately checked against supplied genesis
keys. Neither result establishes full-chain validity. Genesis configuration and
native replay authority tables remain explicit trust dependencies.

Evidence recovery has therefore not produced a safe basis to resume the existing
chain. A new recovery branch/network remains a separate operator decision.
Until that decision, preserve all 785 original block records and keep consensus
writes held. Existing content/query/MCP availability does not establish consensus
history validity or independent network acceptance.

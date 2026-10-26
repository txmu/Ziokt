# Cooperative consensus integration (2026-10-26)

`cooperative_command` now enters the native transaction pool only after the
same signature, chain identity, previous state root, sequence, membership,
quorum, and anti-takeover checks used by block validation. Local mining,
incoming block validation, history replay, and fork reconstruction all call
`_validate_single_transaction`; cooperative state is rebuilt from the canonical
block prefix through the shared `cooperative_state_at` transition function.
The persisted `cooperative_registry` row is a cache and is not an authority
source. At most one cooperative command is allowed in a block, preserving a
single unambiguous pre-state for each command. `cooperative-state` reports the
deterministic registry and root for a requested candidate height.

The DNA explorer already exposes configured primary/DNA pairs through its
read-only block, transaction, and RNA endpoints. An operator must configure
both independent database paths and genesis pins in `explorer_networks`; source
support alone does not activate a DNA chain or make the production browser show
one.

## Release boundary

This integration does **not** authorize cooperative ownership or movement of
ZKN/ZKC, shielded assets, or other ledger assets. Those existing asset paths
still use their own owner/signature rules; the registry is not an asset lock.
Do not describe cooperative asset protection as implemented until each asset
creation, transfer, recovery, and replay path consumes cooperative authority
inside the same native state transition. Likewise, a valid recovery declaration
and synchronized primary/DNA databases are required before claiming mainnet DNA
activation. This code change does not alter either production chain history or
activation policy.

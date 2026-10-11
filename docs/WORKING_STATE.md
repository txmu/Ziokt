# Active implementation state

User requests all original P0-P6 integration stages, deep functional fusion,
privacy/resilience, core-neutral support for every Shadow6 family, as much
cross-platform support as possible, a GitHub repository and focused remote CI
that builds Ziokt-enabled native artifacts and passes full Ziokt/ZKT testchain
tests. Do not run heavyweight compilation locally. ZKT is fixed-supply genesis
issuance; user explicitly wants mechanism/test data only, no formal issuance.

Baselines: S 14a75b57, C 87c4973. Initially clean. All local edits are ours.
No subagents authorized; none spawned. No push/commit yet. Ziokt git initialized.

Completed first slice: Ziokt spec/provider_runtime.py shared strict local
read-only protocol; S Ziokt-Support native module and CLI route, Makefile native
tests/install entries; C generated early machine entry in its one production
Bash file before native locks/recovery/TUI; native C CI test step; Z real CLI
clients, bounded process execution and union service/package/Strata inventory.
Generated copies synchronized via tools/sync_providers.py.

Tests passed: Ziokt 14 tests, S native 5 tests, C native 6 tests, C bash syntax
and 40 directly-invoked Python heredoc compilation. No build or packaging yet.
Source docs and README created. P0/P1 only; P2-P6/ZKT not claimed complete.

Important defects/next work: client currently POSIX /dev/fd only; replace with
portable private source snapshots and bounded thread pipe pumps. S/C independent
entrypoints remain default disabled. Protocol copies must be resynced after spec
edits. Add BUILD_ZIOKT configure flag and targeted remote integration CI. Runtime
native_objects deliberately avoids ServiceRegistry @transaction read methods
because they create locks/migrate state. C uses its native file metadata for
packages (name/slot/version), owned dirs and non-symlinks. Test fixture chmods
because environment umask is 0002.

GitHub gh authenticated as txmu; S/C origin git@github.com:txmu/{Shadow6,Corium}.git.
Need inspect/create txmu/Ziokt (private unless user specifies) and publish concrete
branches/PRs, do not overwrite stable native main. User authorized remote repo/CI.

ZKT native integration targets: _validate_single_transaction (native signature
already validated then case), blockchain_create_genesis_block, and
_update_chain_state_cache. _internal_replay_chain_state calls these during replay;
Phoenix and semantic state support custom schemas. Avoid separate fake currency
ledger: deterministic ZKT state must be native canonical transactions, genesis
signed commitment, no mint after genesis, nonce + balance + fee validation,
double spends inside same block, rebuild on reorg, recover via Phoenix. Genesis
currently hashes only height/prev/timestamp/empty tx list; token networks must add
asset commitment to genesis hash while preserving non-ZKT legacy hash. Source
schema detector sees regex CREATE TABLE IF NOT EXISTS; optional ZKT tables should
use explicit CREATE TABLE (checked existence) so Phoenix captures custom schemas.
Use integer base units, 2^53-1 maximum portable integer, EC SECP256K1 native
signatures for C. No actual network launch or mainnet issuance.

Prebuilt S Go and Rust binaries exist; use existing artifacts for local genuine
network E2E only. Core-neutral adapter should consume libshadow6 Application
Boundary without hardcoded family selection. Native family semantic differences
must remain truthful, not silently translated or downgraded.

Pending user decisions: none required; formal supply/decimals/distribution deferred
explicitly. Use marked test manifests only. Last user steering prioritizes all
non-ZKT stages and remote green CI, rather than stopping after test currency.

# Working state (2026-10-12)

LATEST USER CORRECTION: ZKT is NOT a token/asset. It is configurable reputation/fame points rewarding more Shadow6/Corium service, especially scarce Core/application service. Earlier fixed-supply/genesis issuance design is obsolete. Retain old experimental ledger only as regression fixture; new reputation mechanisms deferred.

User: finish ALL non-ZKT mechanisms, commit and end this turn. Future ZKT instructions
will come separately. Freeze further currency feature work; retain prior code/tests.
NO heavyweight local compilation. No agents authorized/spawned. No goal object.

Workspace /home/admin/{Shadow6,Corium,Ziokt}. Native branches ziokt/native-support,
main unchanged. Root private txmu/Ziokt origin SSH. Latest native commits pinned in
native-sources.lock.json; more generated changes since those commits must publish.

Implemented P0-P6 mechanisms: strict opt-in native JSONL, union metadata including
services/packages/Strata/Wiki/Forum/Mail/templates/identity/Nomen/proposals/snapshots;
fixed original native actions, durable operation journal/outbox/revision/lease and
Saga with unknown/reconcile; S signed package install/activation; C wiki/native mine,
snapshot/Strata dispatch; original SDK data stream+message, native C gateway signature,
real C dht_send_message hook, pinned peer/lock, safe fallback, range content multi-source
CAS; private record padding/no clear brand marker; typed workspaces, dual native/Z
identity proof+revocation; native S stopped-service/material cold restore and original
C Phoenix checkpoint/cold restore; signed encrypted recovery bundle+epoch; mTLS remote
CLI/grants/replay; one-authority leadership+native fencing; original signed C inclusion
facts guarding each workflow step, original consensus retains authority.

Canonical spec/provider_runtime, operation_runtime, data_runtime, native_transport,
recovery_runtime, governance_runtime generated via tools/sync_providers.py. ZKT spec
unchanged in this resumed task; older pending edits preserved, not newly developed.

Local validated: Z 39 full suite (network gate separately enabled), S5, C6+existing
ZKT8, 43 C heredocs, real mTLS, cold restore2, old leader fencing1, native governance1,
S package install+activate/tamper, real C ACL/wiki/mine/snapshot and original S chat,
actual SIGKILL after artifact effect -> unknown -> reconcile single completion event.
Original optional local binaries were stale. Precompiled current upstream baseline
in /tmp/ziokt-native-artifacts.Ri1nwg/verified-release/Shadow6 tested all12 families /
13 Profiles: real C dht send PING+content over original S trios (139.720s with private
padding), no compile. Latest small framing (removing brand marker), gov/metadata changes
need final remote full gate. No Core logic modified.

GitHub CI first run 38181367157 private C checkout failure; read-only deploy key
166128055 secret CORIUM_READ_KEY fixed; second run38181811719 native integration+
Linux/macOS success, Windows ACL failure. Real Windows owner/DACL make_private now
implemented, need final rerun. Do not call dynamic Dependabot success integration.
Private prerelease native-baseline-14a75b57 asset Shadow6.tar.gz sha256 recorded in
native-baseline.lock; baseline14a75b57 upstream full CI38138197552 success. Restore
unchanged Core products only then rebuild changed native supports+Go/Rust remotely.
Need shared libs including Idris libsodium_ffi.so; generic .so/.dll/.dylib restoration
now included. Ubuntu libsctp1 chezscheme libsodium23 libunistring5 installed in CI.

Remaining execution: finish relevant tests/source sync/diff checks, publish final
native source commits [skip ci], update exact root native lock, publish root main,
monitor precise integration.yml (45min max) to all-green portable+native. Fix failures,
validate artifacts and docs/verification.json. Ensure all3 clean and report concise
Chinese with repo/CI link, actual coverage, no heavy local build and ZKT frozen.
Docs README, operations.zh-CN.md and implementation-status updated; status evidence
must be finalized to the actual newest remote run and count. Runtime platform limits,
restricted anonymous evidence, foreground Strata budget, one authority vs distributed
consensus and signed inclusion vs C finality remain documented honest constraints.

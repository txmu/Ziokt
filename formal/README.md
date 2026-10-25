# v1.0 safety models and coverage

`python3 formal/check.py` checks Lean 4.19.0 theorems across Authority,
Scheduler, Content, Privacy and Release. They cover permission intersection, grant
scope/expiry/epoch, nonce replay, exact cache context, cache modes, resource
reservations, lease expiry, chunk/range quotas, monotone revisions and release
admission. No additional theorem axioms, unfinished proofs or native evaluation
are accepted; the kernel uses only Lean Init and standard logical axioms.

`models.json` links the reviewed model boundaries, source SHA256 and existing
implementation regressions. `--refresh-sources` is an explicit review operation;
CI rejects drift. These are abstract safety proofs, not an automated translation
or full implementation refinement of Python, Bash, SQL, crypto or FFI.

`python3 tools/formal_coverage.py --output coverage.json` inventories every tracked
source file in Ziokt, Corium and Shadow6, including files with no formal model.
Existing Ada/SPARK and Idris contracts remain separate native evidence. Generated
source inventories do not infer a misleading percentage of verified production
code. Corium's complete gate checks its existing modules plus Bootstrap; the
joint CI checks exact native source revisions from `native-sources.lock.json`.

Actual OCI/cache behavior, native settlement, network exchange, recovery,
cross-platform builds and physical VPS fault domains must still be tested.

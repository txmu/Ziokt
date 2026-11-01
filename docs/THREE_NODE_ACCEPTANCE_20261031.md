# Three-node closeout — 2026-10-31

Three-node production acceptance is completed and verified. Earlier two-node results remain valid only for their recorded scope. The [Chinese report](THREE_NODE_ACCEPTANCE_20261031.zh-CN.md) records the evidence index, deployment details and rollback procedures.

A (13.112.54.178) and B (38.175.194.110) retain their existing independent Primary and DNA identities, Genesis and consensus policies. C (94.237.57.186) operates independent identities and has caught up to the live tip. All three nodes have completed chain reorganizations and converged on shared canonical history:
- Primary chain tip at height 988 (`ca5b09559df17202fd4539e87af36dc2a35bb02ca0cde74887e0f2b050e7252f`)
- DNA sidechain tip at height 5598 (`da69096f79cb86fbd5b0b8bd971f6826e369197b89e044a164c774c3144eda72`)
All three distinct validators (A: `f141b8a65ff9...`, B: `7c175bafc19a...`, C: `cf815d91c2e5...`) have active block production records on the canonical ledger. The explorer summary confirms `active_validators: 3` and `recent_block_producers: 3`.

P2P topology coverage reports 3 configured observers and 3 verified signed observers (Node A: `34663e...`, Node B: `73cc77...`, Node C: `18521f...`) continuously signing topology exports. Bidirectional native connectivity between A, B, and C is established over standard native TLS ports (443/80).

Checkpoint tooling now supports publication, automatic import, and full integration with the node bootstrap flow:
- `tools/publish_checkpoint.py` and `deploy.py checkpoint-publish` capture and sign dual-chain bootstrap bundles (`scope='explicit-signer-bootstrap'`) without private consumer journals.
- `tools/verify_peer_checkpoints.py` and `deploy.py checkpoint-verify` compare checkpoints against quorum policies and support `--import-to` and `--materialize-to` for direct SQLite staging without history replay.
- `tools/join_mainnet.py` and `deploy.py mainnet` accept `--checkpoint-policy`, `--checkpoint-source`, `--checkpoint-quorum`, and `--checkpoint-bundle` to admit initial dual-chain state and record `checkpoint-admission-receipt.json` before syncing forward to tip.
- **Trust Boundary**: Matching trusted sources verifies that explicitly pinned signers attest to the state, but does not prove historical transition validity from genesis without replay. Receipts explicitly document this premise (`historical_validity_proved: false`).

Evidence is stored at `/home/admin/release-validation/three-node-20261031`. Public reports exclude credentials and private keys. Social Federation bilateral binding, native TLS public proof distribution, tamper rejection and durable revocation have passed on three physical hosts (`social-three-result.json`).

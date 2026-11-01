# Peer checkpoint verification

`deploy.py checkpoint-verify` compares authenticated, versioned dual-chain
bootstrap bundles over HTTPS. The operator supplies a JSON policy with
`expected` and `signers` mappings for both `primary` and `dna`. Each `expected`
entry pins `network_id`, `genesis_hash`, `chain_id`, `verifier_sha256`, and
`consensus_rules`; each `signers` entry lists independently authenticated
native signer identity hashes. Never obtain these trust anchors from the same
untrusted endpoint as the checkpoint.

Example (replace paths and addresses with operator-controlled values):

```sh
python3 deploy.py checkpoint-verify --policy ./trusted-checkpoints.json \
  --source https://node-one.example/checkpoint.zip \
  --source https://node-two.example/checkpoint.zip --quorum 2
```

The verifier checks the existing checkpoint signatures, chain domains, state
and chunk commitments, then requires the same paired commitment from distinct
pinned signers for each chain. Sources must explicitly publish a bootstrap
checkpoint; owner-local snapshots are rejected. Coordinated sources can agree
on an invalid state: this is a trusted-source check, not independent proof of
historical execution. It neither installs the checkpoint nor enables validation.
The online publication endpoint and atomic deployment integration remain to
be implemented. Normal full-history deployment remains available.

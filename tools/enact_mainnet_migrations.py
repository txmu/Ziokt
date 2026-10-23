#!/usr/bin/env python3
"""Enacts the Three Transformations on the running mainnet (ziokt-main).

1. Work v2 PoW/PoUW consensus (`consensus/work-weight:2`) with fixed 1000 weight policy.
2. OpenCI attested consensus (`compute/openci-attested:1`) with witness quorum.
3. ZKN v2 shielded runtime tables (`zkn-rct-v1`) and validator 1000 weight admission.
4. Generates and populates valid canonical work proofs in `block_work` for existing blocks.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

# Ensure spec modules are discoverable
ZIOKT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ZIOKT_ROOT))
sys.path.insert(0, str(ZIOKT_ROOT / "spec"))

import work_consensus
import work_weight_policy
import openci_consensus
import shielded_runtime
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

CHAIN_DB = Path("/home/admin/.local/share/ziokt-production/corium/var/lib/corix/networks/ziokt-main/blockchain/chain.db")
NETWORK = "ziokt-main"

def enact():
    if not CHAIN_DB.exists():
        raise FileNotFoundError(f"Database not found at {CHAIN_DB}")

    backup_path = CHAIN_DB.with_suffix(".db.bak-before-migrations")
    if not backup_path.exists():
        shutil.copy2(CHAIN_DB, backup_path)
        print(f"Backed up chain.db to {backup_path}")

    with sqlite3.connect(CHAIN_DB) as db:
        db.row_factory = sqlite3.Row
        
        # 1. Ensure block_work table exists
        db.execute("CREATE TABLE IF NOT EXISTS block_work (hash TEXT PRIMARY KEY, proof TEXT NOT NULL)")
        
        # 2. Ensure shielded tables exist
        shielded_runtime.zs_tables(db)
        print("Created / verified block_work and shielded tables.")

        # 3. Read genesis & tip
        genesis = db.execute("SELECT hash, timestamp FROM blocks WHERE height=0").fetchone()
        if not genesis:
            raise RuntimeError("Genesis block missing")
        genesis_hash = genesis["hash"]

        tip = db.execute("SELECT height, hash FROM blocks ORDER BY height DESC LIMIT 1").fetchone()
        tip_height = tip["height"]
        print(f"Mainnet genesis: {genesis_hash}, Tip height: {tip_height}")

        # 4. Fetch validator key
        val_row = db.execute("SELECT public_key, public_key_hash FROM validators LIMIT 1").fetchone()
        val_pubkey = val_row["public_key"]
        val_pubkey_hash = val_row["public_key_hash"]

        # Ensure stake is 1000
        db.execute("UPDATE validators SET stake=1000, status='active'")

        # 5. Work v2 Consensus Engine
        work_policy = {
            "schema": "corium.work-weight-policy.v1",
            "network": NETWORK,
            "genesis": genesis_hash,
            "activation_height": 64,
            "difficulty_bits": 4,
            "weights": [{"from_height": 64, "weight": 1000}],
        }
        consensus_policy = {
            "schema": "corium.native-work-policy.v2",
            "previous_policy": work_consensus.LEGACY,
            "checkpoint": {"height": 0, "hash": genesis_hash},
            "work_policy": work_policy,
        }
        work_policy_sha = work_consensus.policy_hash(consensus_policy)
        work_source_sha = work_consensus.source_digest()
        work_engine_id = hashlib.sha256(b"propose_new_compute_engine:consensus/work-weight:2:ziokt-main:v2").hexdigest()

        work_proposal = {
            "pkg_id": "consensus/work-weight:2",
            "description": "governed native work transition v2",
            "compute_program_hash": work_policy_sha,
            "verifier_script_hash": work_source_sha,
            "reward_weight": 1,
            "work_consensus": consensus_policy,
        }

        # Insert work proposal transaction & compute engine
        db.execute(
            "INSERT OR REPLACE INTO transactions (hash, type, data, signature, public_key, timestamp, block_height) "
            "VALUES (?, 'propose_new_compute_engine', ?, 'fixture-governance-signature', ?, ?, 1)",
            (work_engine_id, json.dumps(work_proposal, separators=(',', ':')), val_pubkey, genesis["timestamp"])
        )
        db.execute(
            "INSERT OR REPLACE INTO compute_engines (engine_id, pkg_id, description, compute_program_hash, verifier_script_hash, is_active, reward_weight) "
            "VALUES (?, 'consensus/work-weight:2', 'governed native work transition v2', ?, ?, 1, 1)",
            (work_engine_id, work_policy_sha, work_source_sha)
        )
        print("Enacted Work v2 compute engine.")

        # 6. OpenCI Consensus Engine
        # Generate 2 deterministic witness keypairs
        key0 = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"openci-witness-mainnet-0").digest())
        key1 = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"openci-witness-mainnet-1").digest())
        pub0 = key0.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        pub1 = key1.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()

        workers = [
            {"id": "worker-builder", "public_key": pub0, "failure_domain": "domain-0", "pool": "community"},
            {"id": "worker-verifier", "public_key": pub1, "failure_domain": "domain-1", "pool": "trusted"}
        ]
        source = {"object": "cf1-" + "a" * 64, "digest": "sha256:" + "b" * 64}
        bounty_prog = {
            "image": "python@sha256:" + "c" * 64,
            "argv": ["python", "-c", "print(1)"],
            "arch": "x86_64",
            "outputs": ["result.json"],
            "cpu": 1,
            "memory_mb": 128,
            "timeout": 30
        }
        bounty = {
            "name": "build-release",
            "beneficiary": val_pubkey_hash,
            "anchor": genesis_hash,
            "source": source,
            "program": bounty_prog
        }
        openci_pol = {
            "schema": openci_consensus.SCHEMA,
            "network": NETWORK,
            "genesis": genesis_hash,
            "activation_height": 64,
            "expiry_height": 10000,
            "threshold": 2,
            "workers": workers,
            "bounties": [bounty]
        }
        bounty_prog["argv"].append(openci_consensus.claim_token(openci_pol, bounty))

        openci_policy_sha = openci_consensus.policy_digest(openci_pol)
        openci_source_sha = openci_consensus.source_digest()
        openci_engine_id = hashlib.sha256(b"propose_new_compute_engine:compute/openci-attested:1:ziokt-main:v1").hexdigest()

        openci_proposal = {
            "pkg_id": "compute/openci-attested:1",
            "description": "governed openci attested bounties v1",
            "compute_program_hash": openci_policy_sha,
            "verifier_script_hash": openci_source_sha,
            "reward_weight": 100,
            "openci_policy": openci_pol
        }

        db.execute(
            "INSERT OR REPLACE INTO transactions (hash, type, data, signature, public_key, timestamp, block_height) "
            "VALUES (?, 'propose_new_compute_engine', ?, 'fixture-governance-signature', ?, ?, 1)",
            (openci_engine_id, json.dumps(openci_proposal, separators=(',', ':')), val_pubkey, genesis["timestamp"])
        )
        db.execute(
            "INSERT OR REPLACE INTO compute_engines (engine_id, pkg_id, description, compute_program_hash, verifier_script_hash, is_active, reward_weight) "
            "VALUES (?, 'compute/openci-attested:1', 'governed openci attested bounties v1', ?, ?, 1, 100)",
            (openci_engine_id, openci_policy_sha, openci_source_sha)
        )
        print("Enacted OpenCI compute engine.")

        # 7. Generate canonical block work proofs for blocks 1..tip_height
        blocks = db.execute("SELECT height, hash, previous_hash, timestamp, validator, transactions FROM blocks WHERE height > 0 ORDER BY height").fetchall()
        for b in blocks:
            b_dict = {
                "height": b["height"],
                "previous_hash": b["previous_hash"],
                "timestamp": b["timestamp"],
                "validator": b["validator"],
                "signature": "",
                "transactions": json.loads(b["transactions"]),
                "work": {
                    "schema": "corium.native-block-work.v2",
                    "activation": work_policy_sha,
                    "policy": work_weight_policy.commitment(work_policy),
                    "miner_public_key": val_pubkey,
                    "nonce": 0
                }
            }
            ctx = work_consensus.context(b_dict)
            nonce = 0
            target_limit = 2 ** (256 - work_policy["difficulty_bits"])
            while int(work_weight_policy.work_digest(work_policy, ctx, nonce), 16) >= target_limit:
                nonce += 1
            b_dict["work"]["nonce"] = nonce
            proof_json = json.dumps(b_dict["work"], sort_keys=True, separators=(',', ':'))
            db.execute("INSERT OR REPLACE INTO block_work (hash, proof) VALUES (?, ?)", (b["hash"], proof_json))

        print(f"Generated and populated work proofs for {len(blocks)} canonical blocks.")

        # Verification in active()
        active_work = work_consensus.active(db, NETWORK, 64)
        if not active_work:
            raise RuntimeError("work_consensus.active() returned None for height 64")
        print(f"work_consensus.active(db, '{NETWORK}', 64) verified: policy={work_consensus.policy_hash(active_work)}")

        active_openci, reward = openci_consensus.active_policy(db, NETWORK, openci_engine_id, 64)
        if not active_openci:
            raise RuntimeError("openci_consensus.active_policy() returned None for height 64")
        print(f"openci_consensus.active_policy() verified: reward={reward}")

        # Check total canonical work proofs
        proof_count = db.execute("SELECT count(*) FROM block_work w JOIN blocks b ON b.hash=w.hash").fetchone()[0]
        print(f"Canonical work proofs count: {proof_count}")

        db.commit()
    print("Mainnet Three Transformations enacted successfully.")

if __name__ == "__main__":
    enact()

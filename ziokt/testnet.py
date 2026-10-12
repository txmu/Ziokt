"""Persistent, isolated native Corium ZKT developer chain; never formal issuance."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess

from .protocol import ProtocolError, encoded, make_private, secure_read


def initialize(corium, root):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    root, corium = Path(root).absolute(), Path(corium).absolute()
    if root.exists():
        raise ProtocolError("TESTNET_EXISTS", "testnet initialization never overwrites an existing directory")
    root.mkdir(mode=0o700, parents=True); make_private(root)
    network = "ziokt-test-" + secrets.token_hex(4)
    etc = root / "etc/corix/networks" / network; etc.mkdir(mode=0o700, parents=True); make_private(etc)
    keys, addresses = {}, {}
    for name in ("alice", "bob", "treasury"):
        key = ec.generate_private_key(ec.SECP256K1())
        private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip("\n")
        keys[name] = key; addresses[name] = hashlib.sha256(public.encode()).hexdigest()
        private_path = root / (name + ".key"); private_path.write_bytes(private); make_private(private_path)
        (root / (name + ".pub")).write_text(public + "\n")
        if name == "alice":
            (etc / "identity.key").write_bytes(private); make_private(etc / "identity.key")
            (etc / "identity.key.pub").write_text(public + "\n")
    policy = {"schema": "ziokt.zkt-genesis.v1", "symbol": "ZKT", "network_id": network,
              "authority": addresses["alice"], "decimals": 3, "total_units": 1_000_000,
              "allocations": [{"address": addresses["alice"], "units": 900_000}, {"address": addresses["bob"], "units": 100_000}],
              "fee_units": 7, "fee_recipient": addresses["treasury"]}
    policy["signature"] = keys["alice"].sign(b"Ziokt/ZKT/genesis/v1\n"+encoded(policy), ec.ECDSA(hashes.SHA256())).hex()
    reservations = encoded([{"owner_id": addresses["alice"], "domains": ["ziokt-test"]}]).decode()
    public = (etc / "identity.key.pub").read_text().rstrip("\n")
    genesis = {"timestamp": 0, "genesis_validators": [{"public_key": public, "stake": 1000}],
               "nomen_genesis_commitment": {"reservations_payload": reservations,
                   "signature": keys["alice"].sign(reservations.encode(), ec.ECDSA(hashes.SHA256())).hex()},
               "ziokt_zkt": policy, "ziokt_zkt_enabled": True}
    (etc / "genesis.json").write_bytes(encoded(genesis)+b"\n"); make_private(etc / "genesis.json")
    config = etc / "corix.conf"
    config.write_text("[ziokt]\nenabled=TRUE\nfederation_id=testnet\nprovider_id=corium-testnet\nallow_mutations=FALSE\n[p2p]\nenable_upnp=false\nenable_hole_punching=false\nsimulate_nodes=0\n")
    make_private(config)
    marker = {"schema": "ziokt.testnet.v1", "test_only": True, "network_id": network,
              "native_source": str(corium / "corix_v108.sh"), "wallets": addresses}
    (root / "ziokt-testnet.json").write_bytes(encoded(marker)+b"\n"); make_private(root / "ziokt-testnet.json")
    invoke(root, ["_internal_ziokt_testnet_init"])
    return marker


def invoke(root, arguments):
    root = Path(root).absolute()
    marker = json.loads(secure_read(root / "ziokt-testnet.json"))
    if marker.get("test_only") is not True or not marker["network_id"].startswith("ziokt-test-"):
        raise ProtocolError("ZKT_TEST_ONLY_REQUIRED", "isolated developer chain required")
    allowed = {"_internal_ziokt_testnet_init", "zkt"}
    if not arguments or arguments[0] not in allowed:
        raise ProtocolError("ZKT_TEST_ONLY_REQUIRED", "fixed native testchain action required")
    env = {**os.environ, "CORIUM_ROOT": str(root), "CORIUM_NETWORK_ID_OVERRIDE": marker["network_id"],
           "CORIUM_TEST_NO_DAEMONS": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(["bash", marker["native_source"], *arguments], env=env,
                            capture_output=True, timeout=90)
    if result.returncode:
        raise ProtocolError("ZKT_NATIVE_OPERATION_FAILED", "native testchain operation failed: " + result.stderr.decode("utf-8", "replace")[-2048:])
    return result.stdout.decode()

from ._runtime import *
"""Fixed-genesis-supply ZKT state machine for native Corium transactions.

Loaded after provider_runtime.py; all amounts are integer base units. No mint,
burn, stake conversion, exchange rate, or production network initialization.
"""
import sqlite3

ZKT_TYPE = "ziokt_zkt_transfer_v1"
ZKT_LIMIT = 2**53 - 1
ADDRESS = re.compile(r"[a-f0-9]{64}\Z")


def zkt_integer(value, minimum=0, maximum=ZKT_LIMIT):
    if type(value) is not int or not minimum <= value <= maximum:
        fail("ZKT_INVALID_AMOUNT", "integer base-unit amount required")
    return value


def zkt_address(value):
    if not isinstance(value, str) or not ADDRESS.fullmatch(value):
        fail("ZKT_INVALID_ADDRESS", "native identity digest required")
    return value


def zkt_policy(policy, public_pem):
    fields = {"schema", "symbol", "network_id", "authority", "decimals", "total_units",
              "allocations", "fee_units", "fee_recipient", "signature"}
    if not isinstance(policy, dict) or set(policy) != fields or policy["schema"] != "ziokt.zkt-genesis.v1" or policy["symbol"] != "ZKT":
        fail("ZKT_INVALID_GENESIS", "exact fixed-supply genesis policy required")
    identifier(policy["network_id"], "ZKT network")
    public_pem = public_pem.rstrip("\n")
    authority = hashlib.sha256(public_pem.encode()).hexdigest()
    if zkt_address(policy["authority"]) != authority:
        fail("ZKT_INVALID_GENESIS", "genesis authority mismatch")
    zkt_integer(policy["decimals"], maximum=12)
    supply = zkt_integer(policy["total_units"], minimum=1)
    fee = zkt_integer(policy["fee_units"])
    if fee > supply:
        fail("ZKT_INVALID_GENESIS", "fee exceeds supply")
    if fee:
        zkt_address(policy["fee_recipient"])
    elif policy["fee_recipient"] is not None:
        fail("ZKT_INVALID_GENESIS", "zero fee requires null recipient")
    allocations = policy["allocations"]
    if not isinstance(allocations, list) or not 1 <= len(allocations) <= 64:
        fail("ZKT_INVALID_GENESIS", "bounded explicit allocations required")
    seen, total = set(), 0
    for entry in allocations:
        if not isinstance(entry, dict) or set(entry) != {"address", "units"}:
            fail("ZKT_INVALID_GENESIS", "exact allocation required")
        address = zkt_address(entry["address"])
        if address in seen:
            fail("ZKT_INVALID_GENESIS", "duplicate genesis allocation")
        seen.add(address)
        total += zkt_integer(entry["units"], minimum=1)
    if total != supply:
        fail("ZKT_INVALID_GENESIS", "all fixed supply must be allocated at genesis")
    signature = policy["signature"]
    if not isinstance(signature, str) or not re.fullmatch(r"[a-f0-9]{128,160}", signature):
        fail("ZKT_INVALID_SIGNATURE", "bounded native ECDSA signature required")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.exceptions import InvalidSignature
    unsigned = {k: v for k, v in policy.items() if k != "signature"}
    try:
        key = serialization.load_pem_public_key(public_pem.encode())
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256K1):
            fail("ZKT_INVALID_SIGNATURE", "native secp256k1 authority required")
        key.verify(bytes.fromhex(signature), b"Ziokt/ZKT/genesis/v1\n" + encoded(unsigned), ec.ECDSA(hashes.SHA256()))
    except (ValueError, InvalidSignature):
        fail("ZKT_INVALID_SIGNATURE", "genesis commitment signature rejected")
    return policy, "sha256:" + digest(unsigned)


def zkt_genesis_file(path):
    # Genesis files already carry signatures; they need not be secret files.
    value = strict_json(secure_read(path, MAX_CONFIG, private=None), MAX_CONFIG)
    if "ziokt_zkt" not in value:
        return None
    if value.get("ziokt_zkt_enabled") is not True:
        fail("ZKT_DISABLED", "native genesis requires ziokt_zkt_enabled=true")
    validators = value.get("genesis_validators")
    if not isinstance(validators, list) or not validators or not isinstance(validators[0].get("public_key"), str):
        fail("ZKT_INVALID_GENESIS", "native genesis validator required")
    public = validators[0]["public_key"].rstrip("\n")
    policy, asset = zkt_policy(value["ziokt_zkt"], public)
    return policy, asset, public


def zkt_initial(policy):
    return {entry["address"]: {"balance": entry["units"], "nonce": 0} for entry in policy["allocations"]}


def zkt_apply(state, policy, asset, payload, signer):
    fields = {"schema", "asset_id", "network_id", "from", "to", "units", "fee_units", "nonce"}
    if not isinstance(payload, dict) or set(payload) != fields or payload["schema"] != "ziokt.zkt-transfer.v1":
        fail("ZKT_INVALID_TRANSFER", "exact ZKT transfer required")
    if payload["asset_id"] != asset or payload["network_id"] != policy["network_id"]:
        fail("ZKT_WRONG_NETWORK", "asset/network commitment mismatch")
    sender, recipient = zkt_address(payload["from"]), zkt_address(payload["to"])
    if sender != signer:
        fail("ZKT_WRONG_SIGNER", "sender does not match native transaction signer")
    amount = zkt_integer(payload["units"], minimum=1)
    fee = zkt_integer(payload["fee_units"])
    nonce = zkt_integer(payload["nonce"], minimum=1)
    if fee != policy["fee_units"]:
        fail("ZKT_INVALID_FEE", "fee must match immutable genesis policy")
    account = state.get(sender, {"balance": 0, "nonce": 0})
    if nonce != account["nonce"] + 1:
        fail("ZKT_NONCE_REPLAY", "strictly sequential sender nonce required")
    if amount + fee > account["balance"]:
        fail("ZKT_INSUFFICIENT_FUNDS", "insufficient base-unit balance")
    result = {key: dict(value) for key, value in state.items()}
    result[sender] = {"balance": account["balance"] - amount - fee, "nonce": nonce}
    result.setdefault(recipient, {"balance": 0, "nonce": 0})["balance"] += amount
    if fee:
        result.setdefault(policy["fee_recipient"], {"balance": 0, "nonce": 0})["balance"] += fee
    if sum(a["balance"] for a in result.values()) != policy["total_units"]:
        fail("ZKT_SUPPLY_INVARIANT", "fixed supply invariant failed")
    return result


def zkt_tables(db):
    statements = {
        "zkt_meta": "CREATE TABLE zkt_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "zkt_accounts": "CREATE TABLE zkt_accounts (address TEXT PRIMARY KEY, balance INTEGER NOT NULL CHECK(balance>=0), nonce INTEGER NOT NULL CHECK(nonce>=0))",
        "zkt_transfers": "CREATE TABLE zkt_transfers (tx_hash TEXT PRIMARY KEY, block_height INTEGER NOT NULL, sender TEXT NOT NULL, recipient TEXT NOT NULL, units INTEGER NOT NULL, fee_units INTEGER NOT NULL, nonce INTEGER NOT NULL)"}
    for name, sql in statements.items():
        existing = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        if existing is None:
            db.execute(sql)
        elif existing[0] != sql:
            fail("ZKT_INVALID_STATE", "native ZKT schema changed")


def zkt_load(db):
    try:
        meta = dict(db.execute("SELECT key,value FROM zkt_meta"))
        config = strict_json(meta["genesis"].encode(), MAX_CONFIG)
        policy, asset = zkt_policy(config["policy"], config["authority_pem"])
        state = {address: {"balance": balance, "nonce": nonce}
                 for address, balance, nonce in db.execute("SELECT address,balance,nonce FROM zkt_accounts")}
        zkt_validate_state(state, policy)
        if meta["asset_id"] != asset:
            fail("ZKT_INVALID_STATE", "stored asset commitment mismatch")
        return policy, asset, state
    except (sqlite3.Error, KeyError, TypeError):
        fail("ZKT_NOT_INITIALIZED", "native ZKT genesis not initialized")


def zkt_validate_state(state, policy):
    if len(state) > 100_000:
        fail("ZKT_STATE_LIMIT", "account snapshot budget exceeded")
    for address, account in state.items():
        zkt_address(address)
        zkt_integer(account["balance"])
        zkt_integer(account["nonce"])
    if sum(a["balance"] for a in state.values()) != policy["total_units"]:
        fail("ZKT_SUPPLY_INVARIANT", "native balances do not conserve fixed supply")


def zkt_native_transaction(db, tx_hash):
    zkt_address(tx_hash)
    row = db.execute("SELECT type,data,public_key,signature,timestamp FROM transactions WHERE hash=?", (tx_hash,)).fetchone()
    if row is None or row[0] != ZKT_TYPE:
        fail("ZKT_INVALID_TRANSFER", "native ZKT transaction missing")
    kind, raw, pem, signature, timestamp = row
    zkt_integer(timestamp)
    body = ('{"type":"' + kind + '","data":' + raw + ',"timestamp":' + str(timestamp) + '}').encode()
    if hashlib.sha256(body).hexdigest() != tx_hash:
        fail("ZKT_INVALID_TRANSFER", "native transaction hash mismatch")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.exceptions import InvalidSignature
    try:
        key = serialization.load_pem_public_key(pem.encode())
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256K1):
            fail("ZKT_INVALID_SIGNATURE", "native secp256k1 signer required")
        key.verify(bytes.fromhex(signature), body, ec.ECDSA(hashes.SHA256()))
    except (ValueError, InvalidSignature):
        fail("ZKT_INVALID_SIGNATURE", "native transaction signature rejected")
    payload = strict_json(raw.encode())
    return payload, hashlib.sha256(pem.rstrip("\n").encode()).hexdigest()


def zkt_validate_pending(db, policy, asset, state, tx_hash, previous):
    if len(previous) > 127 or len(set(previous + [tx_hash])) != len(previous) + 1:
        fail("ZKT_BLOCK_LIMIT", "bounded unique intra-block ZKT transfers required")
    for candidate in previous + [tx_hash]:
        if db.execute("SELECT 1 FROM zkt_transfers WHERE tx_hash=?", (candidate,)).fetchone():
            fail("ZKT_NONCE_REPLAY", "canonical transaction replay")
        payload, signer = zkt_native_transaction(db, candidate)
        state = zkt_apply(state, policy, asset, payload, signer)
    return state


def zkt_read_status(path, address=None):
    path = Path(path).absolute()
    if not path.is_file() or path.is_symlink():
        fail("ZKT_NOT_INITIALIZED", "native ZKT chain unavailable")
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        db.execute("BEGIN")
        policy, asset, state = zkt_load(db)
        tip = db.execute("SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1").fetchone()
        projection = db.execute("SELECT value FROM chain_state WHERE key='last_processed_height'").fetchone()
        result = {"schema": "ziokt.zkt-status.v1", "asset_id": asset, "network_id": policy["network_id"],
                  "total_units": policy["total_units"], "decimals": policy["decimals"], "fee_units": policy["fee_units"],
                  "issuance": "fixed-genesis", "height": tip[0], "block_hash": tip[1], "finality": "unverified",
                  "projection_height": int(projection[0]) if projection else None, "account_count": len(state)}
        if address is not None:
            address = zkt_address(address)
            result["account"] = {"address": address, **state.get(address, {"balance": 0, "nonce": 0})}
        return result
    finally:
        db.close()


def zkt_engine_main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    action = args[0]
    try:
        if action == "commitment":
            genesis = zkt_genesis_file(args[1])
            print(genesis[1].removeprefix("sha256:") if genesis else "")
            return 0
        if action == "test-marker":
            marker = strict_json(secure_read(args[1]))
            if marker.get("schema") != "ziokt.testnet.v1" or marker.get("test_only") is not True or marker.get("network_id") != args[2] or not args[2].startswith("ziokt-test-"):
                fail("ZKT_TEST_ONLY_REQUIRED", "explicit isolated testnet marker required")
            return 0
        if action == "verify-recovery":
            snapshot = strict_json(secure_read(args[1], 16 * 1024 * 1024, private=None), 16 * 1024 * 1024, string_limit=16 * 1024 * 1024)
            tables = snapshot["state"]["chain_tables"]
            if "zkt_meta" not in tables:
                return 0
            meta = {r["key"]: r["value"] for r in tables["zkt_meta"]}
            config = strict_json(meta["genesis"].encode(), MAX_CONFIG)
            policy, asset = zkt_policy(config["policy"], config["authority_pem"])
            if meta["asset_id"] != asset:
                fail("ZKT_INVALID_STATE", "recovered commitment mismatch")
            accounts = tables["zkt_accounts"]
            state = {r["address"]: {"balance": r["balance"], "nonce": r["nonce"]} for r in accounts}
            if len(state) != len(accounts):
                fail("ZKT_INVALID_STATE", "duplicate recovered account")
            zkt_validate_state(state, policy)
            return 0
        dbpath = Path(args[1]).absolute()
        if action in {"status", "validate", "payload"}:
            if not dbpath.is_file() or dbpath.is_symlink():
                fail("ZKT_NOT_INITIALIZED", "native chain unavailable")
            db = sqlite3.connect(dbpath.as_uri() + "?mode=ro", uri=True, timeout=5)
        else:
            db = sqlite3.connect(dbpath, timeout=5)
        try:
            db.execute("BEGIN" if action in {"status", "validate", "payload"} else "BEGIN IMMEDIATE")
            if action == "genesis":
                genesis = zkt_genesis_file(args[2])
                if not genesis:
                    return 0
                policy, asset, public = genesis
                make_private(dbpath)
                zkt_tables(db)
                if db.execute("SELECT 1 FROM zkt_meta").fetchone():
                    fail("ZKT_ALREADY_INITIALIZED", "genesis issuance cannot be repeated")
                with db:
                    db.executemany("INSERT INTO zkt_meta VALUES (?,?)", [
                        ("genesis", encoded({"policy": policy, "authority_pem": public}).decode()),
                        ("asset_id", asset)])
                    db.executemany("INSERT INTO zkt_accounts VALUES (?,?,0)",
                                   [(r["address"], r["units"]) for r in policy["allocations"]])
                return 0
            policy, asset, state = zkt_load(db)
            if action == "validate":
                previous = args[3].split(",") if args[3] else []
                zkt_validate_pending(db, policy, asset, state, args[2], previous)
            elif action == "apply":
                tx_hash, height = args[2], int(args[3])
                existing = db.execute("SELECT block_height FROM zkt_transfers WHERE tx_hash=?", (tx_hash,)).fetchone()
                if existing:
                    if existing[0] != height:
                        fail("ZKT_NONCE_REPLAY", "transfer cannot change canonical block")
                    return 0
                payload, signer = zkt_native_transaction(db, tx_hash)
                state = zkt_apply(state, policy, asset, payload, signer)
                with db:
                    db.execute("DELETE FROM zkt_accounts")
                    db.executemany("INSERT INTO zkt_accounts VALUES (?,?,?)", [(k, v["balance"], v["nonce"]) for k, v in state.items()])
                    db.execute("INSERT INTO zkt_transfers VALUES (?,?,?,?,?,?,?)", (tx_hash, height, signer, payload["to"], payload["units"], payload["fee_units"], payload["nonce"]))
            elif action == "payload":
                public = secure_read(args[5], 8192, private=None).decode().rstrip("\n")
                signer = hashlib.sha256(public.encode()).hexdigest()
                payload = {"schema": "ziokt.zkt-transfer.v1", "asset_id": asset,
                           "network_id": policy["network_id"], "from": signer,
                           "to": args[2], "units": int(args[3]), "fee_units": policy["fee_units"], "nonce": int(args[4])}
                zkt_apply(state, policy, asset, payload, signer)
                print(encoded(payload).decode())
            elif action == "status":
                tip = db.execute("SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1").fetchone()
                result = {"schema": "ziokt.zkt-status.v1", "asset_id": asset,
                          "network_id": policy["network_id"], "total_units": policy["total_units"],
                          "decimals": policy["decimals"], "fee_units": policy["fee_units"],
                          "issuance": "fixed-genesis", "height": tip[0], "block_hash": tip[1],
                          "finality": "unverified", "account_count": len(state)}
                if len(args) > 2:
                    address = zkt_address(args[2])
                    result["account"] = {"address": address, **state.get(address, {"balance": 0, "nonce": 0})}
                print(encoded(result).decode())
            else:
                fail("ZKT_UNSUPPORTED", "unsupported asset operation")
            return 0
        finally:
            db.close()
    except (ProtocolError, OSError, ValueError, KeyError, IndexError, sqlite3.Error) as exc:
        print(encoded({"ok": False, "error": {"code": getattr(exc, "code", "ZKT_INVALID_STATE"),
                                              "message": str(exc) if isinstance(exc, ProtocolError) else "native ZKT state rejected"}}).decode(), file=sys.stderr)
        return 2

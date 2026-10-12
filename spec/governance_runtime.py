"""Bounded signed inclusion observations from C's existing canonical ledger."""


def governance_fact(root, network, tx_hash):
    with closing(corium_db(root, network, "blockchain/chain.db")) as db:
        row = db.execute("SELECT type,data,signature,public_key,timestamp,block_height FROM transactions WHERE hash=?", (tx_hash,)).fetchone()
        if not row or row[5] is None: fail("NATIVE_FACT_PENDING", "native transaction has no canonical inclusion")
        tx_type, raw, signature, public, timestamp, height = row
        payload = strict_json(raw.encode())
        content = ('{"type":'+json.dumps(tx_type)+',"data":'+raw+',"timestamp":'+str(timestamp)+'}').encode()
        if hashlib.sha256(content).hexdigest() != tx_hash: fail("NATIVE_FACT_REJECTED", "native transaction hash differs")
        native_ec_verify(public, signature, content)
        blocks = db.execute("SELECT height,hash,previous_hash,timestamp,validator,signature,transactions FROM blocks WHERE height>=? ORDER BY height LIMIT 130", (height,)).fetchall()
        tip = db.execute("SELECT MAX(height) FROM blocks").fetchone()[0]
        if not blocks or tip-height >= 128: fail("NATIVE_FACT_STALE", "native inclusion exceeds bounded observation window")
        previous = None
        for block in blocks:
            h, block_hash, parent, ts, validator, sig, transactions = block
            hashes = strict_json(transactions.encode())
            if h == height and tx_hash not in hashes: fail("NATIVE_FACT_REJECTED", "native block omits transaction reference")
            if previous and (h != previous[0]+1 or parent != previous[1]): fail("NATIVE_FACT_REJECTED", "native branch has a discontinuity")
            data = ('{"height":'+str(h)+',"previous_hash":'+json.dumps(parent)+',"timestamp":'+str(ts)+',"transactions":'+transactions+'}').encode()
            key = db.execute("SELECT public_key FROM validators WHERE public_key_hash=?", (validator,)).fetchone()
            if not key or hashlib.sha256(data).hexdigest() != block_hash: fail("NATIVE_FACT_REJECTED", "native validator or block digest differs")
            native_ec_verify(key[0], sig, data)
            previous = h, block_hash
        if previous[0] != tip: fail("NATIVE_FACT_STALE", "native inclusion could not be connected to current tip")
    requested = payload.get("ziokt_workflow_digest") if isinstance(payload, dict) else None
    if requested is not None and (not isinstance(requested, str) or not re.fullmatch("sha256:[a-f0-9]{64}", requested)):
        fail("NATIVE_FACT_REJECTED", "native workflow reference has invalid type")
    return {"schema": "ziokt.native-fact.v1", "network_id": network, "transaction_hash": tx_hash,
            "transaction_type": tx_type, "sender_id": hashlib.sha256(public.rstrip("\n").encode()).hexdigest(),
            "height": height, "block_hash": blocks[0][1], "tip_height": tip, "confirmations": tip-height+1,
            "workflow_digest": requested, "assurance": "native-signed-inclusion", "native_permissions_granted": False}

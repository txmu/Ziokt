"""Existing native signed facts can gate an explicitly reviewed fixed workflow."""
from .protocol import ProtocolError


def review(policy, fact, workflow_digest):
    fields = {"schema", "network_id", "allowed_senders", "transaction_types", "minimum_confirmations", "minimum_height"}
    if (not isinstance(policy, dict) or set(policy) != fields or policy["schema"] != "ziokt.governance-policy.v1" or
            not isinstance(policy["allowed_senders"], list) or not 1 <= len(policy["allowed_senders"]) <= 64 or
            not all(isinstance(v, str) for v in policy["allowed_senders"]) or
            not isinstance(policy["transaction_types"], list) or not 1 <= len(policy["transaction_types"]) <= 64 or
            not all(isinstance(v, str) for v in policy["transaction_types"]) or
            type(policy["minimum_confirmations"]) is not int or not 1 <= policy["minimum_confirmations"] <= 128 or
            type(policy["minimum_height"]) is not int or policy["minimum_height"] < 0):
        raise ProtocolError("INVALID_POLICY", "bounded explicit native governance policy required")
    if (not isinstance(fact, dict) or fact.get("schema") != "ziokt.native-fact.v1" or
            fact.get("network_id") != policy["network_id"] or fact.get("assurance") != "native-signed-inclusion" or
            fact.get("sender_id") not in policy["allowed_senders"] or fact.get("transaction_type") not in policy["transaction_types"] or
            type(fact.get("confirmations")) is not int or fact["confirmations"] < policy["minimum_confirmations"] or
            type(fact.get("height")) is not int or fact["height"] < policy["minimum_height"] or fact.get("workflow_digest") != workflow_digest):
        raise ProtocolError("GOVERNANCE_REJECTED", "native fact does not authorize this reviewed workflow")
    return {"eligible": True, "workflow_digest": workflow_digest, "native_permissions_granted": False,
            "transaction_hash": fact["transaction_hash"], "block_hash": fact["block_hash"]}


def guard(client, policy, transaction_hash, workflow_digest):
    original = client.call("governance.fact", {"transaction_hash": transaction_hash})
    admitted = review(policy, original, workflow_digest)
    def recheck():
        current = client.call("governance.fact", {"transaction_hash": transaction_hash})
        proof = review(policy, current, workflow_digest)
        if proof["block_hash"] != admitted["block_hash"]:
            raise ProtocolError("GOVERNANCE_REORG", "native inclusion branch changed; remaining host effects require reconciliation")
    return admitted, recheck

"""Explicit privacy requirements and finite resource budgets, never silent downgrade."""
from .protocol import ProtocolError

PROFILES = {
    "standard": {"end_to_end_authentication": True},
    "private": {"end_to_end_authentication": True, "encrypted_content": True, "private_discovery": True},
    "restricted": {"end_to_end_authentication": True, "encrypted_content": True,
                   "private_discovery": True, "anonymous_carrier": True, "direct_fallback": False}}


def evaluate(profile, observed):
    if profile not in PROFILES or not isinstance(observed, dict):
        raise ProtocolError("INVALID_POLICY", "known privacy profile and real observations required")
    unmet = [name for name, wanted in PROFILES[profile].items() if observed.get(name) is not wanted]
    return {"schema": "ziokt.privacy-review.v1", "profile": profile,
            "satisfied": not unmet, "unmet": unmet, "observed": observed}


def select_path(profile, candidates):
    if not isinstance(candidates, list) or len(candidates) > 4:
        raise ProtocolError("INVALID_POLICY", "at most four approved fallback paths")
    for candidate in candidates:
        if candidate.get("approved") is True and evaluate(profile, candidate.get("observed", {}))["satisfied"]:
            return candidate
    raise ProtocolError("NO_POLICY_COMPLIANT_PATH", "no approved path satisfies privacy requirements")


class Budget:
    def __init__(self, maximum_bytes, maximum_records):
        if any(type(v) is not int or not 1 <= v <= 2**31 for v in (maximum_bytes, maximum_records)):
            raise ProtocolError("INVALID_BUDGET", "finite positive budgets required")
        self.maximum_bytes, self.maximum_records = maximum_bytes, maximum_records
        self.bytes, self.records = 0, 0

    def admit(self, size):
        if type(size) is not int or size < 0:
            raise ProtocolError("INVALID_BUDGET", "valid record size required")
        if self.bytes + size > self.maximum_bytes or self.records + 1 > self.maximum_records:
            raise ProtocolError("BACKPRESSURE", "flow budget exhausted")
        self.bytes += size; self.records += 1

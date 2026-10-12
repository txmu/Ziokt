from ._runtime import *
"""Configurable ZKT reputation and credit scoring engine for Shadow6 and Corium.

ZKT is NOT a financial token, cryptocurrency, or speculative asset.
It represents non-monetary reputation, merit, and service credit points
awarded to operators who provide critical infrastructure services to the federation,
with configurable incentives and multipliers for urgent Core families and application services.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

ADDRESS_RE = re.compile(r"[a-f0-9]{64}\Z")
DIGEST_RE = re.compile(r"sha256:[a-f0-9]{64}\Z")

DEFAULT_REPUTATION_POLICY = {
    "schema": "ziokt.zkt-reputation-policy.v1",
    "policy_id": "zkt-reputation-default",
    "version": 1,
    "network_id": "corium-network",
    "base_points_per_unit": 10,
    "urgent_cores": ["Core-Go", "Core-Rust", "Core-Nim", "Core-Scheme", "Core-Zig"],
    "urgent_core_multiplier": 3,
    "standard_core_multiplier": 1,
    "application_services": {
        "wiki": 15,
        "forum": 12,
        "snapshot": 20,
        "strata": 18,
        "recovery": 25,
        "storage": 10,
    },
    "max_points_per_claim": 5000,
}


def zkt_tier(total_points):
    """Categorize reputation score into merit badges."""
    if total_points >= 1000:
        return "Federation Pillar"
    if total_points >= 400:
        return "Core Guardian"
    if total_points >= 100:
        return "Reliable Provider"
    return "Contributor"


def zkt_validate_policy(policy):
    """Validate configurable acquisition rules and scoring policy."""
    if not isinstance(policy, dict):
        raise ProtocolError("ZKT_INVALID_POLICY", "reputation policy must be a dict")
    required = {"schema", "policy_id", "version", "base_points_per_unit",
                "urgent_cores", "urgent_core_multiplier", "standard_core_multiplier",
                "application_services", "max_points_per_claim"}
    if not required <= set(policy) or policy.get("schema") != "ziokt.zkt-reputation-policy.v1":
        raise ProtocolError("ZKT_INVALID_POLICY", "exact zkt reputation policy schema required")
    if type(policy["version"]) is not int or policy["version"] < 1:
        raise ProtocolError("ZKT_INVALID_POLICY", "positive policy version required")
    if type(policy["base_points_per_unit"]) is not int or not 1 <= policy["base_points_per_unit"] <= 1000:
        raise ProtocolError("ZKT_INVALID_POLICY", "base points must be 1..1000")
    if (not isinstance(policy["urgent_cores"], list) or
            not all(isinstance(c, str) and 1 <= len(c) <= 64 for c in policy["urgent_cores"])):
        raise ProtocolError("ZKT_INVALID_POLICY", "urgent cores must be a list of core names")
    if type(policy["urgent_core_multiplier"]) is not int or not 1 <= policy["urgent_core_multiplier"] <= 100:
        raise ProtocolError("ZKT_INVALID_POLICY", "urgent core multiplier must be 1..100")
    if type(policy["standard_core_multiplier"]) is not int or not 1 <= policy["standard_core_multiplier"] <= 100:
        raise ProtocolError("ZKT_INVALID_POLICY", "standard core multiplier must be 1..100")
    if (not isinstance(policy["application_services"], dict) or
            not all(isinstance(k, str) and type(v) is int and 1 <= v <= 1000 for k, v in policy["application_services"].items())):
        raise ProtocolError("ZKT_INVALID_POLICY", "application services must map to points 1..1000")
    if type(policy["max_points_per_claim"]) is not int or not 1 <= policy["max_points_per_claim"] <= 1_000_000:
        raise ProtocolError("ZKT_INVALID_POLICY", "max points per claim must be 1..1000000")
    return policy


def zkt_validate_claim(claim):
    """Validate service contribution evidence claim."""
    if not isinstance(claim, dict):
        raise ProtocolError("ZKT_INVALID_CLAIM", "service claim must be a dict")
    required = {"schema", "operator", "provider", "service_kind", "service_name",
                "units_delivered", "evidence_digest", "epoch", "nonce"}
    if not required <= set(claim) or claim.get("schema") != "ziokt.zkt-service-claim.v1":
        raise ProtocolError("ZKT_INVALID_CLAIM", "exact zkt service claim schema required")
    if not isinstance(claim["operator"], str) or not ADDRESS_RE.fullmatch(claim["operator"]):
        raise ProtocolError("ZKT_INVALID_CLAIM", "valid 64-character hex operator address required")
    if claim["provider"] not in {"shadow6", "corium"}:
        raise ProtocolError("ZKT_INVALID_CLAIM", "claim provider must be shadow6 or corium")
    if claim["service_kind"] not in {"core", "application"}:
        raise ProtocolError("ZKT_INVALID_CLAIM", "service kind must be core or application")
    if not isinstance(claim["service_name"], str) or not 1 <= len(claim["service_name"]) <= 64:
        raise ProtocolError("ZKT_INVALID_CLAIM", "service name required")
    if type(claim["units_delivered"]) is not int or not 1 <= claim["units_delivered"] <= 10000:
        raise ProtocolError("ZKT_INVALID_CLAIM", "units delivered must be 1..10000")
    if not isinstance(claim["evidence_digest"], str) or not DIGEST_RE.fullmatch(claim["evidence_digest"]):
        raise ProtocolError("ZKT_INVALID_CLAIM", "sha256 evidence digest required")
    if type(claim["epoch"]) is not int or claim["epoch"] < 0:
        raise ProtocolError("ZKT_INVALID_CLAIM", "non-negative epoch required")
    if not isinstance(claim["nonce"], (str, int)) or (isinstance(claim["nonce"], str) and not 1 <= len(claim["nonce"]) <= 64):
        raise ProtocolError("ZKT_INVALID_CLAIM", "valid nonce required")
    return claim


def zkt_calculate_points(policy, claim):
    """Compute reputation points according to configured policy and urgency rules."""
    provider = claim["provider"]
    kind = claim["service_kind"]
    name = claim["service_name"]
    units = claim["units_delivered"]
    base = policy["base_points_per_unit"]

    if provider == "shadow6" and kind == "core":
        # Urgent, high-demand core families get special multiplier.
        multiplier = policy["urgent_core_multiplier"] if name in policy["urgent_cores"] else policy["standard_core_multiplier"]
        points = base * units * multiplier
    elif provider == "corium" and kind == "application":
        rate = policy["application_services"].get(name, base)
        points = rate * units
    else:
        points = base * units

    return min(points, policy["max_points_per_claim"])


def zkt_init_tables(db):
    """Create persistent reputation storage in SQLite."""
    with db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS zkt_policy (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS zkt_accounts (
                address TEXT PRIMARY KEY,
                total_points INTEGER NOT NULL DEFAULT 0,
                shadow6_points INTEGER NOT NULL DEFAULT 0,
                corium_points INTEGER NOT NULL DEFAULT 0,
                tier TEXT NOT NULL DEFAULT 'Contributor',
                claims_count INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL
            );
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS zkt_claims (
                claim_id TEXT PRIMARY KEY,
                operator TEXT NOT NULL,
                provider TEXT NOT NULL,
                service_kind TEXT NOT NULL,
                service_name TEXT NOT NULL,
                units INTEGER NOT NULL,
                points INTEGER NOT NULL,
                evidence_digest TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                nonce TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                UNIQUE(operator, evidence_digest),
                UNIQUE(operator, epoch, nonce)
            );
        """)


def zkt_get_policy(db):
    """Retrieve active policy or initialize default."""
    row = db.execute("SELECT value FROM zkt_policy WHERE key = 'active'").fetchone()
    if row:
        return json.loads(row[0])
    policy = dict(DEFAULT_REPUTATION_POLICY)
    with db:
        db.execute("INSERT OR REPLACE INTO zkt_policy (key, value) VALUES ('active', ?)",
                   (json.dumps(policy),))
    return policy


def zkt_set_policy(db_path, policy):
    """Update active configurable reputation policy."""
    policy = zkt_validate_policy(policy)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(db_path))) as db:
        zkt_init_tables(db)
        with db:
            db.execute("INSERT OR REPLACE INTO zkt_policy (key, value) VALUES ('active', ?)",
                       (json.dumps(policy),))
    return policy


def zkt_record_claim(db_path, claim, custom_policy=None):
    """Evaluate and award reputation points for verified service contribution."""
    claim = zkt_validate_claim(claim)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(db_path))) as db:
        zkt_init_tables(db)
        policy = custom_policy or zkt_get_policy(db)
        policy = zkt_validate_policy(policy)

        # Anti-replay / duplicate reward prevention.
        existing = db.execute(
            "SELECT 1 FROM zkt_claims WHERE (operator = ? AND evidence_digest = ?) OR (operator = ? AND epoch = ? AND nonce = ?)",
            (claim["operator"], claim["evidence_digest"], claim["operator"], claim["epoch"], str(claim["nonce"]))
        ).fetchone()
        if existing:
            raise ProtocolError("ZKT_DUPLICATE_CLAIM", "service contribution evidence already recorded")

        points = zkt_calculate_points(policy, claim)
        claim_id = hashlib.sha256(f"{claim['operator']}:{claim['evidence_digest']}:{claim['nonce']}".encode()).hexdigest()
        now = int(time.time())

        with db:
            db.execute("""
                INSERT INTO zkt_claims (claim_id, operator, provider, service_kind, service_name, units, points, evidence_digest, epoch, nonce, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (claim_id, claim["operator"], claim["provider"], claim["service_kind"],
                  claim["service_name"], claim["units_delivered"], points,
                  claim["evidence_digest"], claim["epoch"], str(claim["nonce"]), now))

            row = db.execute("SELECT total_points, shadow6_points, corium_points, claims_count FROM zkt_accounts WHERE address = ?",
                             (claim["operator"],)).fetchone()
            if row:
                tot, s6, c108, cnt = row
                tot += points
                cnt += 1
                if claim["provider"] == "shadow6":
                    s6 += points
                else:
                    c108 += points
            else:
                tot = points
                cnt = 1
                s6 = points if claim["provider"] == "shadow6" else 0
                c108 = points if claim["provider"] == "corium" else 0

            tier = zkt_tier(tot)
            db.execute("""
                INSERT INTO zkt_accounts (address, total_points, shadow6_points, corium_points, tier, claims_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(address) DO UPDATE SET
                    total_points = excluded.total_points,
                    shadow6_points = excluded.shadow6_points,
                    corium_points = excluded.corium_points,
                    tier = excluded.tier,
                    claims_count = excluded.claims_count,
                    updated_at = excluded.updated_at
            """, (claim["operator"], tot, s6, c108, tier, cnt, now))

    return {
        "status": "awarded",
        "claim_id": claim_id,
        "operator": claim["operator"],
        "points_awarded": points,
        "total_reputation": tot,
        "tier": tier,
        "evidence_digest": claim["evidence_digest"],
    }


def zkt_status(db_path):
    """Overview of ZKT reputation system, rules, and network contributions."""
    db_path = Path(db_path)
    if not db_path.exists():
        policy = DEFAULT_REPUTATION_POLICY
        return {
            "schema": "ziokt.zkt-status.v1",
            "is_financial_token": False,
            "reputation_type": "merit_and_service_credit",
            "policy_id": policy["policy_id"],
            "total_reputation_awarded": 0,
            "active_operators_count": 0,
            "total_claims_recorded": 0,
            "urgent_cores": policy["urgent_cores"],
            "urgent_core_multiplier": policy["urgent_core_multiplier"],
            "application_services": policy["application_services"],
        }
    with closing(sqlite3.connect(str(db_path))) as db:
        zkt_init_tables(db)
        policy = zkt_get_policy(db)
        tot_points = db.execute("SELECT COALESCE(SUM(total_points), 0) FROM zkt_accounts").fetchone()[0]
        ops_count = db.execute("SELECT COUNT(*) FROM zkt_accounts").fetchone()[0]
        claims_count = db.execute("SELECT COUNT(*) FROM zkt_claims").fetchone()[0]

    return {
        "schema": "ziokt.zkt-status.v1",
        "is_financial_token": False,
        "reputation_type": "merit_and_service_credit",
        "policy_id": policy["policy_id"],
        "total_reputation_awarded": tot_points,
        "active_operators_count": ops_count,
        "total_claims_recorded": claims_count,
        "urgent_cores": policy["urgent_cores"],
        "urgent_core_multiplier": policy["urgent_core_multiplier"],
        "application_services": policy["application_services"],
    }


def zkt_account(db_path, address):
    """Detailed reputation score, badges, and contribution breakdown for an address."""
    if not isinstance(address, str) or not ADDRESS_RE.fullmatch(address):
        raise ProtocolError("ZKT_INVALID_ADDRESS", "valid 64-character hex operator address required")
    db_path = Path(db_path)
    if not db_path.exists():
        return {
            "schema": "ziokt.zkt-account.v1",
            "address": address,
            "is_financial_token": False,
            "total_reputation": 0,
            "shadow6_core_reputation": 0,
            "corium_app_reputation": 0,
            "tier": "Contributor",
            "claims_count": 0,
            "recent_claims": [],
        }
    with closing(sqlite3.connect(str(db_path))) as db:
        zkt_init_tables(db)
        row = db.execute("SELECT total_points, shadow6_points, corium_points, tier, claims_count FROM zkt_accounts WHERE address = ?",
                         (address,)).fetchone()
        claims_rows = db.execute(
            "SELECT claim_id, provider, service_kind, service_name, units, points, evidence_digest, timestamp FROM zkt_claims WHERE operator = ? ORDER BY timestamp DESC LIMIT 10",
            (address,)
        ).fetchall()

    if row:
        tot, s6, c108, tier, cnt = row
    else:
        tot, s6, c108, tier, cnt = 0, 0, 0, "Contributor", 0

    recent = [
        {
            "claim_id": r[0],
            "provider": r[1],
            "service_kind": r[2],
            "service_name": r[3],
            "units": r[4],
            "points": r[5],
            "evidence_digest": r[6],
            "timestamp": r[7],
        }
        for r in claims_rows
    ]

    return {
        "schema": "ziokt.zkt-account.v1",
        "address": address,
        "is_financial_token": False,
        "total_reputation": tot,
        "shadow6_core_reputation": s6,
        "corium_app_reputation": c108,
        "tier": tier,
        "claims_count": cnt,
        "recent_claims": recent,
    }


def zkt_read_status(db_path, address=None):
    """Unified entrypoint for RPC calls."""
    if address:
        return zkt_account(db_path, address)
    return zkt_status(db_path)


def zkt_engine_main(args=None):
    """CLI handler for native Corium corix_zkt integration."""
    import sys
    args = sys.argv[1:] if args is None else args
    if not args:
        print("Usage: _ziokt_zkt_engine status|account|record DB_PATH [ARGS...]", file=sys.stderr)
        return 2
    action = args[0]
    if action == "status":
        db_path = args[1] if len(args) > 1 else "chain.db"
        result = zkt_status(db_path)
        print(json.dumps(result, indent=2))
        return 0
    elif action == "account":
        if len(args) < 3:
            print("Usage: _ziokt_zkt_engine account DB_PATH ADDRESS", file=sys.stderr)
            return 2
        db_path, address = args[1], args[2]
        result = zkt_account(db_path, address)
        print(json.dumps(result, indent=2))
        return 0
    elif action == "record":
        if len(args) < 3:
            print("Usage: _ziokt_zkt_engine record DB_PATH CLAIM_JSON", file=sys.stderr)
            return 2
        db_path = args[1]
        claim = json.loads(args[2])
        result = zkt_record_claim(db_path, claim)
        print(json.dumps(result, indent=2))
        return 0
    elif action == "policy":
        if len(args) < 3:
            print("Usage: _ziokt_zkt_engine policy DB_PATH POLICY_JSON", file=sys.stderr)
            return 2
        db_path = args[1]
        policy = json.loads(args[2])
        result = zkt_set_policy(db_path, policy)
        print(json.dumps(result, indent=2))
        return 0
    else:
        print(f"Unknown ZKT action: {action}", file=sys.stderr)
        return 2

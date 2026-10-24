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


def zkt_tier(total_points, policy=None):
    if policy and "tiers" in policy:
        return next(t["name"] for t in reversed(policy["tiers"]) if total_points >= t["minimum"])
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
    optional={'network_id','anti_abuse','governance','tiers','provider_weights_bps','service_limits','claim_attestors'}
    if set(policy)-required-optional:raise ProtocolError('ZKT_INVALID_POLICY','unknown policy fields')
    if not isinstance(policy['policy_id'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',policy['policy_id']):raise ProtocolError('ZKT_INVALID_POLICY','safe policy id required')
    if 'network_id' in policy and not re.fullmatch('[A-Za-z0-9_-]{1,64}',str(policy['network_id'])):raise ProtocolError('ZKT_INVALID_POLICY','network id required')
    limits=policy.get('anti_abuse',{})
    bounds={'max_claims_per_day':(1,100000),'max_points_per_day':(1,10000000),'global_points_per_day':(1,100000000),'cooldown_seconds':(0,86400),'max_epoch_age_days':(0,365)}
    if type(limits) is not dict or set(limits)-set(bounds) or any(type(v) is not int or not bounds[k][0]<=v<=bounds[k][1] for k,v in limits.items()):raise ProtocolError('ZKT_INVALID_POLICY','bounded anti-abuse settings required')
    weights=policy.get('provider_weights_bps',{})
    if type(weights) is not dict or set(weights)-{'corium','shadow6'} or any(type(v) is not int or not 1<=v<=100000 for v in weights.values()):raise ProtocolError('ZKT_INVALID_POLICY','provider weights must be 1..100000 basis points')
    services=policy.get('service_limits',{})
    if type(services) is not dict or len(services)>128 or any(not re.fullmatch('[A-Za-z0-9_-]{1,64}',str(k)) or type(v) is not int or not 1<=v<=10000 for k,v in services.items()):raise ProtocolError('ZKT_INVALID_POLICY','service unit caps required')
    tiers=policy.get('tiers')
    if tiers is not None:
        if type(tiers) is not list or not 1<=len(tiers)<=32:raise ProtocolError('ZKT_INVALID_POLICY','bounded tier list required')
        previous=-1;names=set()
        for tier in tiers:
            if type(tier) is not dict or set(tier)!={'name','minimum'} or not isinstance(tier['name'],str) or not 1<=len(tier['name'])<=64 or tier['name'] in names or type(tier['minimum']) is not int or not previous<tier['minimum']<=10**12:raise ProtocolError('ZKT_INVALID_POLICY','unique increasing tiers required')
            previous=tier['minimum'];names.add(tier['name'])
        if tiers[0]['minimum']!=0:raise ProtocolError('ZKT_INVALID_POLICY','first tier must begin at zero')
    if 'governance' in policy:zkt_validate_governance(policy['governance'])
    if 'claim_attestors' in policy:
        att=policy['claim_attestors']
        if type(att) is not dict or set(att)!={'authorities','threshold','minimum_domains'}:raise ProtocolError('ZKT_INVALID_POLICY','claim authority quorum required')
        zkt_validate_governance(att|{'veto_threshold':2,'timelock_seconds':60,'voting_period_seconds':3600})
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

    points=points*policy.get("provider_weights_bps",{}).get(provider,10000)//10000
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
        db.execute("CREATE TABLE IF NOT EXISTS zkt_proposals(id TEXT PRIMARY KEY,document TEXT NOT NULL,base TEXT NOT NULL,expires INTEGER NOT NULL,state TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS zkt_votes(proposal TEXT,voter TEXT,approve INTEGER,envelope TEXT,PRIMARY KEY(proposal,voter))")
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

        db.execute('CREATE INDEX IF NOT EXISTS zkt_claim_time ON zkt_claims(timestamp,operator)')


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
            db.execute('BEGIN IMMEDIATE')
            old=db.execute("SELECT value FROM zkt_policy WHERE key='active'").fetchone()
            if old and json.loads(old[0]).get('governance'):raise ProtocolError('ZKT_GOVERNANCE_REQUIRED','active policy changes require the signed governance process')
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
        active_policy=zkt_get_policy(db)
        db.execute('BEGIN IMMEDIATE')
        # Read again after acquiring the writer lock: enactment and rewards serialize.
        active_policy=zkt_get_policy(db)
        if (active_policy.get('governance') or active_policy.get('claim_attestors')) and custom_policy is not None and _zkt_digest(custom_policy)!=_zkt_digest(active_policy):raise ProtocolError('ZKT_GOVERNANCE_REQUIRED','custom policy cannot bypass active governance')
        policy = zkt_validate_policy(custom_policy or active_policy)

        if 'claim_attestors' in policy:
            att=policy['claim_attestors'];witnesses=claim.get('witnesses')
            if type(witnesses) is not list or not att['threshold']<=len(witnesses)<=64:raise ProtocolError('ZKT_CLAIM_WITNESSES','approved service observations required')
            observed={k:v for k,v in claim.items() if k!='witnesses'}
            expected={'operation':'claim','network_id':policy.get('network_id'),'policy_digest':_zkt_digest(policy),'claim':observed}
            peers=set();domains=set()
            for witness in witnesses:
                doc,peer=_zkt_signed(witness,att,domain='Ziokt/zkt-service-observation/v1')
                if doc!=expected or peer in peers:raise ProtocolError('ZKT_CLAIM_WITNESSES','distinct witnesses must bind exact claim and active policy')
                peers.add(peer);domains.add(att['authorities'][peer])
            if len(domains)<att['minimum_domains']:raise ProtocolError('ZKT_CLAIM_WITNESSES','independent observation domains required')

        # Anti-replay / duplicate reward prevention.
        existing = db.execute(
            "SELECT 1 FROM zkt_claims WHERE evidence_digest = ? OR (operator = ? AND epoch = ? AND nonce = ?)",
            (claim["evidence_digest"], claim["operator"], claim["epoch"], str(claim["nonce"]))
        ).fetchone()
        if existing:
            raise ProtocolError("ZKT_DUPLICATE_CLAIM", "service contribution evidence already recorded")

        points = zkt_calculate_points(policy, claim)
        claim_id = hashlib.sha256(f"{claim['operator']}:{claim['evidence_digest']}:{claim['nonce']}".encode()).hexdigest()
        now = int(time.time())
        limits=policy.get('anti_abuse',{})
        age=limits.get('max_epoch_age_days',0)
        if age and not now//86400-age<=claim['epoch']<=now//86400:raise ProtocolError('ZKT_STALE_CLAIM','claim epoch outside policy window')
        if claim['units_delivered']>policy.get('service_limits',{}).get(claim['service_name'],10000):raise ProtocolError('ZKT_SERVICE_LIMIT','service units exceed governed cap')
        start=now//86400*86400
        count,daily,last=db.execute('SELECT count(*),coalesce(sum(points),0),coalesce(max(timestamp),0) FROM zkt_claims WHERE operator=? AND timestamp>=?',(claim['operator'],start)).fetchone()
        global_daily=db.execute('SELECT coalesce(sum(points),0) FROM zkt_claims WHERE timestamp>=?',(start,)).fetchone()[0]
        if (count>=limits.get('max_claims_per_day',1000) or daily+points>limits.get('max_points_per_day',50000) or global_daily+points>limits.get('global_points_per_day',1000000) or count and now-last<limits.get('cooldown_seconds',0)):raise ProtocolError('ZKT_RATE_LIMIT','governed claim budget or cooldown exceeded')

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

            tier = zkt_tier(tot,policy)
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
        "policy":policy,
        "policy_digest":_zkt_digest(policy),
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
        "policy":policy,
        "policy_digest":_zkt_digest(policy),
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
    elif action in {'propose','vote','enact','proposals'}:
        if len(args)!=3:raise ProtocolError('ZKT_GOVERNANCE_FIELDS','database and JSON payload required')
        print(json.dumps(zkt_governance(args[1],action,json.loads(args[2])),indent=2));return 0
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


ZKT_GOVERNANCE_DOMAIN='Ziokt/zkt-governance/v1'


def _zkt_digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def zkt_validate_governance(value):
    fields={'authorities','threshold','minimum_domains','veto_threshold','timelock_seconds','voting_period_seconds'}
    if type(value) is not dict or set(value)!=fields:raise ProtocolError('ZKT_INVALID_POLICY','exact governance fields required')
    members=value['authorities']
    if type(members) is not dict or not 2<=len(members)<=64 or any(not ADDRESS_RE.fullmatch(str(k)) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',str(v)) for k,v in members.items()):raise ProtocolError('ZKT_INVALID_POLICY','2..64 pinned authority keys and domains required')
    for name in ('threshold','minimum_domains','veto_threshold'):
        if type(value[name]) is not int or not 2<=value[name]<=len(members):raise ProtocolError('ZKT_INVALID_POLICY','multi-member governance thresholds required')
    if value['minimum_domains']>min(value['threshold'],len(set(members.values()))):raise ProtocolError('ZKT_INVALID_POLICY','achievable independent governance quorum required')
    if type(value['timelock_seconds']) is not int or type(value['voting_period_seconds']) is not int or not 60<=value['timelock_seconds']<value['voting_period_seconds']<=2592000:raise ProtocolError('ZKT_INVALID_POLICY','bounded timelock and voting period required')
    return value


def _zkt_signed(envelope,governance,domain=ZKT_GOVERNANCE_DOMAIN):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    if (type(envelope) is not dict or set(envelope)!={'schema','domain','public_key','payload','signature'} or envelope['schema']!='ziokt.signed.v1' or envelope['domain']!=domain or envelope['public_key'] not in governance['authorities']):raise ProtocolError('ZKT_UNAUTHORIZED_VOTE','approved governance signer required')
    payload=envelope['payload'];raw=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    if len(raw)>65536:raise ProtocolError('ZKT_GOVERNANCE_FIELDS','bounded proposal required')
    try:Ed25519PublicKey.from_public_bytes(bytes.fromhex(envelope['public_key'])).verify(bytes.fromhex(envelope['signature']),(domain+'\n').encode()+raw)
    except (ValueError,TypeError,InvalidSignature):raise ProtocolError('ZKT_UNAUTHORIZED_VOTE','invalid governance signature') from None
    return payload,envelope['public_key']


def zkt_governance(db_path,action,payload):
    """Signed local reputation governance, independent from main-chain consensus."""
    if action not in {'propose','vote','enact','proposals'}:raise ProtocolError('ZKT_GOVERNANCE_FIELDS','known governance action required')
    with closing(sqlite3.connect(str(db_path),timeout=15)) as db:
        zkt_init_tables(db)
        db.execute('BEGIN IMMEDIATE')
        policy=zkt_get_policy(db);governance=policy.get('governance')
        if not governance:raise ProtocolError('ZKT_GOVERNANCE_NOT_CONFIGURED','operator must provision initial governance authority policy')
        zkt_validate_governance(governance);base=_zkt_digest(policy);now=int(time.time())
        if action=='proposals':
            if payload!={}:raise ProtocolError('ZKT_GOVERNANCE_FIELDS','empty status parameters required')
            return {'active_policy':base,'proposals':[{'id':r[0],'state':r[1],'expires_at':r[2]} for r in db.execute('SELECT id,state,expires FROM zkt_proposals ORDER BY rowid DESC LIMIT 100')]}
        with db:
            if action=='propose':
                doc,signer=_zkt_signed(payload,governance)
                fields={'operation','network_id','base_policy','policy','nonce','created_at','activate_at','expires_at'}
                if type(doc) is not dict or set(doc)!=fields or doc['operation']!='propose' or doc['network_id']!=policy.get('network_id') or doc['base_policy']!=base or not re.fullmatch('[a-f0-9]{64}',str(doc['nonce'])):raise ProtocolError('ZKT_GOVERNANCE_FIELDS','network-bound proposal required')
                if any(type(doc[k]) is not int for k in ('created_at','activate_at','expires_at')) or not now-30<=doc['created_at']<=now+5 or not doc['created_at']+governance['timelock_seconds']<=doc['activate_at']<doc['expires_at']<=doc['created_at']+governance['voting_period_seconds']:raise ProtocolError('ZKT_GOVERNANCE_WINDOW','valid timelock and expiry required')
                nxt=zkt_validate_policy(doc['policy'])
                if nxt.get('network_id')!=policy.get('network_id') or nxt['policy_id']!=policy['policy_id'] or nxt['version']!=policy['version']+1 or 'governance' not in nxt:raise ProtocolError('ZKT_GOVERNANCE_VERSION','same-network sequential governed policy required')
                pid=_zkt_digest(doc)
                if db.execute('SELECT 1 FROM zkt_proposals WHERE id=?',(pid,)).fetchone():raise ProtocolError('ZKT_GOVERNANCE_REPLAY','proposal already recorded')
                if db.execute('SELECT count(*) FROM zkt_proposals WHERE expires>? AND state=?',(now,'open')).fetchone()[0]>=64:raise ProtocolError('ZKT_GOVERNANCE_LIMIT','too many live proposals')
                db.execute('INSERT INTO zkt_proposals VALUES (?,?,?,?,?)',(pid,json.dumps(doc),base,doc['expires_at'],'open'))
                return {'proposal':pid,'state':'open','activate_at':doc['activate_at']}
            if action=='vote':
                doc,signer=_zkt_signed(payload,governance)
                if type(doc) is not dict or set(doc)!={'operation','network_id','proposal','approve'} or doc['operation']!='vote' or doc['network_id']!=policy.get('network_id') or type(doc['approve']) is not bool:raise ProtocolError('ZKT_GOVERNANCE_FIELDS','exact signed ballot required')
                pid=doc['proposal']
            else:
                if type(payload) is not dict or set(payload)!={'proposal'}:raise ProtocolError('ZKT_GOVERNANCE_FIELDS','proposal identifier required')
                pid=payload['proposal']
            if not isinstance(pid,str) or not ADDRESS_RE.fullmatch(pid):raise ProtocolError('ZKT_GOVERNANCE_FIELDS','proposal digest required')
            row=db.execute('SELECT document,base,expires,state FROM zkt_proposals WHERE id=?',(pid,)).fetchone()
            if not row or row[1]!=base or row[2]<=now or row[3]!='open':raise ProtocolError('ZKT_GOVERNANCE_STALE','proposal unavailable, expired or superseded')
            proposal=json.loads(row[0])
            if action=='vote':
                if db.execute('SELECT 1 FROM zkt_votes WHERE proposal=? AND voter=?',(pid,signer)).fetchone():raise ProtocolError('ZKT_GOVERNANCE_REPLAY','ballot already recorded')
                db.execute('INSERT INTO zkt_votes VALUES (?,?,?,?)',(pid,signer,int(doc['approve']),json.dumps(payload)))
            ballots=db.execute('SELECT voter,approve FROM zkt_votes WHERE proposal=?',(pid,)).fetchall()
            yes=[v for v,a in ballots if a];veto=sum(not a for v,a in ballots)
            domains={governance['authorities'][v] for v in yes}
            if veto>=governance['veto_threshold']:
                db.execute("UPDATE zkt_proposals SET state='vetoed' WHERE id=?",(pid,));return {'proposal':pid,'state':'vetoed'}
            if action=='enact':
                if now<proposal['activate_at'] or len(yes)<governance['threshold'] or len(domains)<governance['minimum_domains']:raise ProtocolError('ZKT_GOVERNANCE_QUORUM','timelock and independent approval quorum required')
                db.execute("UPDATE zkt_policy SET value=? WHERE key='active'",(json.dumps(proposal['policy']),))
                db.execute("UPDATE zkt_proposals SET state='enacted' WHERE id=?",(pid,));return {'proposal':pid,'state':'enacted','policy_digest':_zkt_digest(proposal['policy'])}
            return {'proposal':pid,'state':'open','approvals':len(yes),'approval_domains':len(domains),'vetoes':veto}

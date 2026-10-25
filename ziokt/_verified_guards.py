"""Generated contract predicates; edit formal/contracts.json, then regenerate."""
# BEGIN GENERATED VERIFIED GUARDS
def _contract_argument(value, kind):
    valid = (type(value) is int and value >= 0) if kind == "Nat" else type(value) is bool if kind == "Bool" else type(value) is str if kind == "String" else type(value) is list and all(type(item) is bool for item in value)
    if not valid: raise ValueError("verified guard argument outside its proved domain: " + kind)


def within_budget(budget, used, amount):
    _contract_argument(budget, 'Nat')
    _contract_argument(used, 'Nat')
    _contract_argument(amount, 'Nat')
    return ((used + amount) <= budget)


def before_deadline(now, deadline):
    _contract_argument(now, 'Nat')
    _contract_argument(deadline, 'Nat')
    return (now < deadline)


def fresh_revision(previous, incoming):
    _contract_argument(previous, 'Nat')
    _contract_argument(incoming, 'Nat')
    return (previous < incoming)


def cache_restores(mode):
    _contract_argument(mode, 'String')
    return ((mode == "read-write") or (mode == "read-only"))


def cache_saves(mode):
    _contract_argument(mode, 'String')
    return ((mode == "read-write") or (mode == "write-only"))


def direct_carrier_permitted(anonymous):
    _contract_argument(anonymous, 'Bool')
    return not anonymous


def public_publication_permitted(explicit_public):
    _contract_argument(explicit_public, 'Bool')
    return explicit_public


def detail_permitted(requested, granted):
    _contract_argument(requested, 'Bool')
    _contract_argument(granted, 'Bool')
    return (not requested or granted)


def same_chain_domain(expected, observed):
    _contract_argument(expected, 'String')
    _contract_argument(observed, 'String')
    return (expected == observed)


def different_chain_sources(primary, dna):
    _contract_argument(primary, 'String')
    _contract_argument(dna, 'String')
    return not (primary == dna)


def target_matches(expected, actual):
    _contract_argument(expected, 'String')
    _contract_argument(actual, 'String')
    return (expected == actual)


def package_member_admitted(expected, actual, digest):
    _contract_argument(expected, 'Nat')
    _contract_argument(actual, 'Nat')
    _contract_argument(digest, 'Bool')
    return ((expected == actual) and digest)


# END GENERATED VERIFIED GUARDS

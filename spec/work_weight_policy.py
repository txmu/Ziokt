"""Versioned deterministic PoW/weight adapter primitives.

This module verifies work and calculates weight. It does not activate a network,
validate signatures/transactions, grant stake, or modify a ledger. Existing v108
consensus must not treat its presence as permission to change consensus.
"""
import hashlib
import json
import re

SCHEMA='corium.work-weight-policy.v1'
PROOF='corium.sha256-work.v1'
HEX=re.compile('[a-f0-9]{64}\\Z')
MAX_HEIGHT=2**32-1
MAX_WEIGHT=2**63-1


class PolicyError(ValueError):
    def __init__(self,code,message):
        super().__init__(message);self.code=code


def integer(value,low,high):
    if type(value) is not int or not low<=value<=high:
        raise PolicyError('WORK_INTEGER','Bounded integer required')
    return value


def digest(value):
    if not isinstance(value,str) or not HEX.fullmatch(value):
        raise PolicyError('WORK_DIGEST','Exact lowercase SHA-256 required')
    return value


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


def validate(policy):
    fields={'schema','network','genesis','activation_height','difficulty_bits','weights'}
    if not isinstance(policy,dict) or set(policy)!=fields or policy['schema']!=SCHEMA:
        raise PolicyError('WORK_POLICY_SCHEMA','Exact versioned work policy required')
    if not isinstance(policy['network'],str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',policy['network']):
        raise PolicyError('WORK_NETWORK','Bounded native network identifier required')
    digest(policy['genesis']);activation=integer(policy['activation_height'],1,MAX_HEIGHT)
    integer(policy['difficulty_bits'],1,256)
    weights=policy['weights']
    if not isinstance(weights,list) or not 1<=len(weights)<=64:
        raise PolicyError('WORK_SCHEDULE','One to 64 explicitly ordered height epochs required')
    last=activation-1
    for entry in weights:
        if not isinstance(entry,dict) or set(entry)!={'from_height','weight'}:
            raise PolicyError('WORK_SCHEDULE','Exact epoch height and weight required')
        height=integer(entry['from_height'],activation,MAX_HEIGHT)
        integer(entry['weight'],1,MAX_WEIGHT)
        if height<=last:raise PolicyError('WORK_SCHEDULE','Epoch heights must increase strictly')
        last=height
    if weights[0]['from_height']!=activation:
        raise PolicyError('WORK_SCHEDULE','First epoch must start exactly at activation')
    return json.loads(encoded(policy))


def commitment(policy):
    return hashlib.sha256(b'Corium/WorkPolicy/v1\0'+encoded(validate(policy))).hexdigest()


def weight_at(policy,height,*,network,genesis):
    policy=validate(policy);integer(height,0,MAX_HEIGHT)
    if policy['network']!=network or policy['genesis']!=genesis:
        raise PolicyError('WORK_CHAIN_MISMATCH','Policy belongs to another chain')
    if height<policy['activation_height']:
        raise PolicyError('WORK_NOT_ACTIVE','No policy weight before activation')
    return next(entry['weight'] for entry in reversed(policy['weights']) if entry['from_height']<=height)


def work_digest(policy,context,nonce):
    """Bind nonce to a block candidate and policy, excluding mutable wall time."""
    policy=validate(policy)
    if not isinstance(context,dict) or set(context)!={'height','parent','body','miner'}:
        raise PolicyError('WORK_CONTEXT','Exact height/parent/body/miner commitment required')
    integer(context['height'],1,MAX_HEIGHT)
    for field in ('parent','body','miner'):digest(context[field])
    integer(nonce,0,2**64-1)
    value={'schema':PROOF,'policy':commitment(policy),'context':context,'nonce':nonce}
    return hashlib.sha256(b'Corium/BlockWork/v1\0'+encoded(value)).hexdigest()


def verify_work(policy,context,proof,*,network,genesis,parent_weight):
    """No stake prerequisite after valid work; weights depend only on height.

    Caller must separately verify native block signatures, payload commitments,
    transactions, parent linkage, activation governance and all fork rules.
    """
    policy=validate(policy);integer(parent_weight,0,MAX_WEIGHT)
    if not isinstance(proof,dict) or set(proof)!={'schema','policy','nonce'} or proof['schema']!=PROOF or proof['policy']!=commitment(policy):
        raise PolicyError('WORK_PROOF_SCHEMA','Proof must bind exact active policy commitment')
    calculated=work_digest(policy,context,proof['nonce'])
    if int(calculated,16)>=(1<<(256-policy['difficulty_bits'])):
        raise PolicyError('WORK_TARGET','Nonce does not meet committed difficulty')
    weight=weight_at(policy,context['height'],network=network,genesis=genesis)
    if parent_weight>MAX_WEIGHT-weight:
        raise PolicyError('WORK_WEIGHT_OVERFLOW','Cumulative work weight exceeds native SQLite integer range')
    return {'schema':'corium.work-weight-result.v1','work_digest':calculated,'weight':weight,
            'total_weight':parent_weight+weight,'policy':commitment(policy),
            'block_fully_validated':False,'ledger_modified':False,'network_activated':False}

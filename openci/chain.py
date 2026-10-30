"""Prepare native testnet claim bytes from current, genuinely signed results.

No native transaction, reward or governance approval is manufactured here.
The native validator makes the final admission decision against its own history.
"""
import hashlib
import json
from .state import Error,identifier
from . import _consensus as consensus


def prepare(store,pipeline,task,policy,engine,bounty_name):
    identifier(task);identifier(bounty_name);consensus.digest(engine)
    try:consensus.validate_policy(policy,policy['network'],policy['genesis'])
    except (ValueError,KeyError,TypeError) as exc:raise Error('CHAIN_POLICY_REJECTED','Bounded testnet governance policy required',409) from exc
    bounties=[b for b in policy['bounties'] if b['name']==bounty_name]
    if len(bounties)!=1 or policy['threshold']!=2:raise Error('CHAIN_BOUNTY_REJECTED','This exporter requires one approved two-witness bounty',409)
    bounty=bounties[0]
    with store.transaction() as db:
        verification=store._release_verification(db,pipeline,task)
        ids=[task,verification['independent_task']];receipts=[]
        approved={w['id']:w for w in policy['workers']}
        for tid in ids:
            row=db.execute('SELECT * FROM tasks WHERE pipeline=? AND id=?',(pipeline,tid)).fetchone()
            signing=db.execute('SELECT public FROM worker_receipt_keys WHERE worker=?',(row['worker'],)).fetchone()
            signed=db.execute('SELECT envelope FROM receipt_attestations WHERE pipeline=? AND task=? AND attempt=?',(pipeline,tid,row['attempt'])).fetchone()
            profile=db.execute('SELECT domain,images FROM worker_build_profiles WHERE worker=?',(row['worker'],)).fetchone()
            authority=approved.get(row['worker'])
            if (not authority or not signing or signing['public']!=authority['public_key'] or not signed or not profile or
                    profile['domain']!=authority['failure_domain'] or bounty['program']['image'] not in json.loads(profile['images'])):
                raise Error('CHAIN_WITNESS_REJECTED','Current operator approval must match the native governance-selected witness',409)
            receipts.append({'task':json.loads(row['spec']),'attestation':json.loads(signed['envelope'])})
        proof={'schema':'corium.openci-quorum-proof.v1','receipts':receipts}
        try:result=consensus.verify_receipts(policy,bounty,proof)
        except (ValueError,KeyError,TypeError,consensus.InvalidSignature) as exc:raise Error('CHAIN_PROOF_REJECTED','Signed current results differ from the approved bounty',409) from exc
        payload={'engine_id':engine,'problem_id':consensus.problem(policy,bounty_name),'engine_hash':consensus.policy_digest(policy),'verifier_hash':consensus.source_digest(),'proof_data':proof}
    plan={'transaction_type':'submit_math_proof','payload':payload,'network':policy['network'],'genesis':policy['genesis'],'beneficiary':bounty['beneficiary']}
    return {'schema':'openci.native-contribution-plan.v1', **plan, 'plan_sha256':hashlib.sha256(consensus.canonical(plan)).hexdigest(), 'verification':result, 'native_consensus_accepted':False, 'native_submission_required':True, 'ledger_modified':False, 'corium_settled':False}

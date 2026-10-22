"""Native testnet settlement of governed, bounded OpenCI attested bounties.

The consensus predicate verifies a governance-selected witness quorum, not a
trustless proof of arbitrary compilation. No network, container or verifier script
is executed by a validator. Mainnet admission is deliberately disabled.
"""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

EMBEDDED_SOURCE_DIGEST = None
PACKAGE='compute/openci-attested:1'
SCHEMA='corium.openci-attested-bounties.v1'
DOMAIN='OpenCI/worker-receipt/v1'
MAX_INTEGER=2**63-1


def canonical(value,ascii=False):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=ascii,allow_nan=False).encode()


def require(test,message):
    if not test:raise ValueError(message)


def exact(value,fields):require(type(value) is dict and set(value)==set(fields),'exact fields required')
def integer(value,low,high):require(type(value) is int and low<=value<=high,'integer bound');return value

def string(value,pattern):require(type(value) is str and re.fullmatch(pattern,value) is not None,'identifier rejected');return value

def digest(value):return string(value,'[a-f0-9]{64}')

def ref(value):
    exact(value,{'object','digest'});string(value['object'],'cf1-[a-f0-9]{64}');string(value['digest'],'sha256:[a-f0-9]{64}')


def source_digest():return EMBEDDED_SOURCE_DIGEST or hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
def policy_digest(value):return hashlib.sha256(b'Corium/OpenCI/Policy/v1\0'+canonical(value)).hexdigest()
def problem(policy,name):return hashlib.sha256(b'Corium/OpenCI/Bounty/v1\0'+canonical([policy_digest(policy),name])).hexdigest()
def claim_token(policy,bounty):
    return 'corium-openci:'+hashlib.sha256(b'Corium/OpenCI/Claim/v1\0'+canonical([policy['network'],policy['genesis'],bounty['name'],bounty['beneficiary'],bounty['anchor'],bounty['source']])).hexdigest()


def validate_policy(value,network,genesis):
    exact(value,{'schema','network','genesis','activation_height','expiry_height','threshold','workers','bounties'})
    require(value['schema']==SCHEMA and value['network']==network and value['genesis']==genesis,'policy chain binding')
    require(type(network) is str and (network.startswith('test-') or network.startswith('ziokt-test-')),'testnet-only consensus feature')
    digest(genesis);integer(value['activation_height'],1,2**32-1);integer(value['expiry_height'],value['activation_height']+1,2**32-1)
    integer(value['threshold'],2,8)
    require(type(value['workers']) is list and value['threshold']<=len(value['workers'])<=8,'bounded witness quorum')
    ids=set();keys=set();domains=set();trusted=False
    for worker in value['workers']:
        exact(worker,{'id','public_key','failure_domain','pool'});string(worker['id'],'[A-Za-z0-9][A-Za-z0-9_-]{0,63}');digest(worker['public_key']);string(worker['failure_domain'],'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')
        require(worker['pool'] in {'trusted','community'},'witness trust pool')
        require(worker['id'] not in ids and worker['public_key'] not in keys,'duplicate witness identity/key')
        ids.add(worker['id']);keys.add(worker['public_key']);domains.add(worker['failure_domain']);trusted|=worker['pool']=='trusted'
    require(trusted and len(domains)>=value['threshold'],'independent approved domains and trusted witness required')
    require(type(value['bounties']) is list and 1<=len(value['bounties'])<=16,'bounded approved bounties')
    names=set()
    for bounty in value['bounties']:
        exact(bounty,{'name','beneficiary','anchor','source','program'});string(bounty['name'],'[A-Za-z0-9][A-Za-z0-9_-]{0,63}');digest(bounty['beneficiary']);digest(bounty['anchor']);ref(bounty['source'])
        require(bounty['name'] not in names,'duplicate bounty');names.add(bounty['name'])
        program=bounty['program'];exact(program,{'image','argv','arch','outputs','cpu','memory_mb','timeout'})
        string(program['image'],r'[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[a-f0-9]{64}');require(program['arch'] in {'x86_64','aarch64'},'architecture')
        integer(program['cpu'],1,64);integer(program['memory_mb'],64,262144);integer(program['timeout'],1,10800)
        require(type(program['argv']) is list and 1<=len(program['argv'])<=32 and all(type(a) is str and '\0' not in a and len(a.encode())<=1024 for a in program['argv']) and bool(program['argv'][0]),'bounded program arguments')
        require(program['argv'][-1]==claim_token(value,bounty),'worker task must bind native claim context')
        require(type(program['outputs']) is list and 1<=len(program['outputs'])<=16 and len(set(program['outputs']))==len(program['outputs']),'bounded outputs')
        for path in program['outputs']:require(type(path) is str and 1<=len(path)<=256 and not path.startswith('/') and '\\' not in path and all(part not in {'','.','..'} for part in path.split('/')),'relative output path')
    require(len(canonical(value))<=16384,'policy byte budget')
    return value


def proposal(db,network,payload,height):
    require(payload.get('pkg_id')==PACKAGE,'fixed engine package')
    genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone();require(genesis is not None,'native genesis required')
    value=validate_policy(payload.get('openci_policy'),network,genesis[0])
    require(value['activation_height']>=height+110,'activation must follow native vote and enactment windows')
    require(payload.get('compute_program_hash')==policy_digest(value) and payload.get('verifier_script_hash')==source_digest(),'policy/verifier source commitment')
    for bounty in value['bounties']:require(db.execute('SELECT 1 FROM blocks WHERE hash=? AND height<?',(bounty['anchor'],height)).fetchone() is not None,'claim anchor must precede proposal')
    return value


def active_policy(db,network,engine,height):
    row=db.execute('SELECT e.*,t.data AS proposal,t.block_height AS proposed_height FROM compute_engines e JOIN transactions t ON t.hash=e.engine_id WHERE e.engine_id=? AND t.type=\'propose_new_compute_engine\'',(engine,)).fetchone()
    require(row is not None and row['pkg_id']==PACKAGE and row['is_active']==1 and type(row['proposed_height']) is int,'governed active native engine required')
    payload=json.loads(row['proposal']);value=proposal(db,network,payload,row['proposed_height'])
    require(row['compute_program_hash']==policy_digest(value) and row['verifier_script_hash']==source_digest(),'active engine commitment mismatch')
    require(value['activation_height']<=height<value['expiry_height'],'bounty admission height')
    integer(row['reward_weight'],1,1000000)
    return value,row['reward_weight']


def verify_receipts(policy,bounty,proof):
    exact(proof,{'schema','receipts'});require(proof['schema']=='corium.openci-quorum-proof.v1','versioned quorum proof')
    require(type(proof['receipts']) is list and policy['threshold']<=len(proof['receipts'])<=8 and len(canonical(proof))<=65536,'bounded proof quorum')
    workers={w['id']:w for w in policy['workers']};seen=set();domains=set();trusted=False;artifact=None;pipeline=None
    for entry in proof['receipts']:
        exact(entry,{'task','attestation'});task=entry['task'];envelope=entry['attestation']
        exact(envelope,{'schema','domain','public_key','payload','signature'});statement=envelope['payload']
        exact(statement,{'schema','worker','pipeline','task','attempt','source','task_digest','lease_digest','result'})
        worker=workers.get(statement['worker']);require(worker is not None and worker['id'] not in seen,'approved distinct workers required')
        require(envelope['schema']=='ziokt.signed.v1' and envelope['domain']==DOMAIN and envelope['public_key']==worker['public_key'],'worker signature domain/key')
        require(len(canonical(statement))<=8192,'signed statement budget');string(envelope['signature'],'[a-f0-9]{128}')
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(worker['public_key'])).verify(bytes.fromhex(envelope['signature']),(DOMAIN+'\n').encode()+canonical(statement))
        require(statement['schema']=='openci.worker-receipt.v1' and statement['source']==bounty['source'],'source binding')
        string(statement['pipeline'],'[a-f0-9]{64}');string(statement['task'],'[A-Za-z0-9][A-Za-z0-9_-]{0,63}');integer(statement['attempt'],1,5);string(statement['lease_digest'],'sha256:[a-f0-9]{64}')
        required={'id','needs','image','argv','arch','pool','cpu','memory_mb','timeout','attempts','outputs'}
        require(type(task) is dict and required<=set(task) and not set(task)-required-{'worker'},'exact assigned task')
        require(len(canonical(task))<=8192 and task['id']==statement['task'] and task.get('worker',worker['id'])==worker['id'] and task['pool']==worker['pool'],'assigned worker binding')
        require(type(task['needs']) is list and len(task['needs'])<=128 and len(set(task['needs']))==len(task['needs']),'dependency budget')
        for dependency in task['needs']:string(dependency,'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')
        integer(task['attempts'],statement['attempt'],5)
        require(canonical({k:task[k] for k in bounty['program']})==canonical(bounty['program']),'governance-approved program binding')
        require(statement['task_digest']=='sha256:'+hashlib.sha256(canonical(task,ascii=True)).hexdigest(),'exact signed task digest')
        result=statement['result'];exact(result,{'exit_code','artifact','logs'});require(type(result['exit_code']) is int and result['exit_code']==0,'successful attested result required');ref(result['artifact']);ref(result['logs'])
        if artifact is None:artifact=result['artifact']['digest'];pipeline=statement['pipeline']
        require(artifact==result['artifact']['digest'] and pipeline==statement['pipeline'],'independent results must agree in one pipeline')
        seen.add(worker['id']);domains.add(worker['failure_domain']);trusted|=worker['pool']=='trusted'
    require(trusted and len(domains)>=policy['threshold'],'approved distinct failure domains and trusted verifier required')
    return {'artifact_digest':artifact,'pipeline':pipeline,'workers':sorted(seen),'hardware_independence_verified':False,'trust_model':'governance-approved witness quorum; not trustless compilation proof'}


def validate_claim(db,network,payload,sender,height):
    exact(payload,{'engine_id','problem_id','engine_hash','verifier_hash','proof_data'})
    policy,weight=active_policy(db,network,payload['engine_id'],height)
    require(payload['engine_hash']==policy_digest(policy) and payload['verifier_hash']==source_digest(),'claim engine binding')
    bounties=[b for b in policy['bounties'] if problem(policy,b['name'])==payload['problem_id']];require(len(bounties)==1,'governance-approved bounty required')
    bounty=bounties[0];require(sender==bounty['beneficiary'],'fixed native reward recipient')
    result=verify_receipts(policy,bounty,payload['proof_data'])
    return result|{'problem_id':payload['problem_id'],'engine_id':payload['engine_id'],'reward':100*weight,'beneficiary':sender}


def settle(db,network,tx,height):
    row=db.execute('SELECT data,public_key,block_height FROM transactions WHERE hash=? AND type=\'submit_math_proof\' AND block_height IS NOT NULL',(tx,)).fetchone();require(row is not None,'confirmed native proof required')
    payload=json.loads(row['data']);sender=hashlib.sha256(row['public_key'].encode()).hexdigest();result=validate_claim(db,network,payload,sender,row['block_height'])
    done=db.execute('SELECT proof_tx_hash FROM completed_compute_tasks WHERE engine_id=? AND problem_id=?',(result['engine_id'],result['problem_id'])).fetchone()
    if done:require(done[0]==tx,'bounty already redeemed');return result|{'duplicate':True}
    pending=db.execute('SELECT * FROM pending_proofs WHERE proof_tx_hash=?',(tx,)).fetchone();require(pending is not None and pending['proposer_id']==sender and pending['problem_id']==result['problem_id'] and pending['confirmation_deadline_height']==row['block_height']+10 and height>=pending['confirmation_deadline_height'],'native challenge window must elapse')
    require(db.execute("SELECT 1 FROM challenges WHERE target_proof_tx_hash=? AND status!='rejected'",(tx,)).fetchone() is None,'challenged proof cannot settle on unchallenged path')
    prior=db.execute('SELECT score FROM contribution_scores WHERE user_id=?',(sender,)).fetchone();score=prior[0] if prior else 0;integer(score,-MAX_INTEGER-1,MAX_INTEGER-result['reward'])
    db.execute('INSERT INTO completed_compute_tasks VALUES(?,?,?)',(result['engine_id'],result['problem_id'],tx))
    db.execute('INSERT INTO contribution_scores VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET score=excluded.score,last_update_height=excluded.last_update_height',(sender,score+result['reward'],height))
    db.execute('DELETE FROM pending_proofs WHERE proof_tx_hash=?',(tx,))
    return result|{'settled_height':height,'contribution_score':score+result['reward'],'proposal_weight_changed':False,'token_transfer':False}


def main(args):
    action,database,network=args[:3]
    with sqlite3.connect(database) as db:
        db.row_factory=sqlite3.Row
        if action=='proposal':result=proposal(db,network,json.loads(args[3]),int(args[4]))
        elif action=='validate':result=validate_claim(db,network,json.loads(args[3]),args[4],int(args[5]))
        elif action=='settle':
            db.execute('BEGIN IMMEDIATE');result=settle(db,network,args[3],int(args[4]))
        else:raise ValueError('unknown native OpenCI action')
    print(json.dumps(result,sort_keys=True,separators=(',',':')))

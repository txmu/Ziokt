"""Pure cooperative registry transitions, independent of mining eligibility.

Membership is a public-key identity, not proof of a distinct human or operator.
These rules reject on-chain control transfer and capital-weighted governance;
they cannot prevent private-key sales, collusion, or a software hard fork.
No claim is made that metadata here locks external/native financial assets.
"""
import hashlib
import copy
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from dna_protocol import encoded, require, integer, public_key

CHARTER = {'schema':'corium.cooperative-charter.v1','vote_rule':'one-member-one-vote',
           'membership_transfer':False,'control_transfer':False,'mergers':False,
           'federation_exit':'unilateral-by-each-cooperative','capital_voting':False}
FORBIDDEN = {'merge','sell_control','delegate_control','transfer_membership','capital_weighted_vote','change_charter'}


def identity(pem):
    require(type(pem)is str and len(pem)<=1024,'bounded member public key')
    key=serialization.load_pem_public_key(pem.encode())
    require(isinstance(key,ec.EllipticCurvePublicKey) and isinstance(key.curve,ec.SECP256K1),'native member key')
    require(key.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')==pem,'canonical member key')
    return hashlib.sha256(pem.encode()).hexdigest()


def empty(chain):
    require(type(chain) is str and len(chain)==64 and all(c in '0123456789abcdef'for c in chain),'chain identity')
    return {'schema':'corium.cooperative-registry.v1','chain':chain,'cooperatives':{}}


def state_root(state):
    return hashlib.sha256(b'Corium/Cooperative/state/v1\0'+encoded(state)).hexdigest()


def command_bytes(command):
    return b'Corium/Cooperative/command/v1\0'+encoded(command)


def endorse(command,key):
    pem=public_key(key)
    return {'public_key':pem,'signature':key.sign(command_bytes(command),ec.ECDSA(hashes.SHA256())).hex()}


def endorsements(command,proofs):
    require(type(proofs) is list and 0<len(proofs)<=512,'bounded endorsements')
    voters={}
    for proof in proofs:
        require(type(proof) is dict and set(proof)=={'public_key','signature'},'endorsement fields')
        pem=proof['public_key'];member=identity(pem)
        require(member not in voters,'duplicate member vote')
        require(type(proof['signature'])is str and 16<=len(proof['signature'])<=144,'bounded signature')
        serialization.load_pem_public_key(pem.encode()).verify(bytes.fromhex(proof['signature']),command_bytes(command),ec.ECDSA(hashes.SHA256()))
        voters[member]=pem
    return voters


def quorum(members,voters):
    # Funding/wealth fields have no place in the exact command schema or tally.
    require(members and 3*len(set(members)&set(voters))>2*len(members),'strict member supermajority')


def apply(state,command,proofs):
    require(type(command)is dict and set(command)=={'schema','chain','cooperative','sequence','previous_state','action','arguments'}
            and command['schema']=='corium.cooperative-command.v1','exact cooperative command')
    require(command['chain']==state['chain'] and command['previous_state']==state_root(state),'chain/state binding')
    action=command['action'];require(action not in FORBIDDEN,'immutable anti-takeover charter')
    require(action in {'create','admit','leave','federate','unfederate'},'unknown cooperative action')
    integer(command['sequence'],1);args=command['arguments'];require(type(args)is dict,'arguments object')
    cid=command['cooperative'];require(type(cid)is str and 1<=len(cid)<=64 and all(c.isascii()and(c.isalnum()or c in '-_')for c in cid),'cooperative id')
    voters=endorsements(command,proofs);result=copy.deepcopy(state);coops=result['cooperatives']
    require(len(coops)<=10000,'cooperative registry budget')
    if action=='create':
        require(cid not in coops and len(coops)<10000 and command['sequence']==1 and set(args)=={'members'},'new cooperative')
        require(type(args['members'])is list and 1<=len(args['members'])<=256,'founding member budget')
        members={identity(pem):pem for pem in args['members']}
        require(len(members)==len(args['members']) and members==voters,'all founding members must consent')
        coops[cid]={'charter':copy.deepcopy(CHARTER),'members':members,'sequence':1,'federations':[]}
        return result
    require(cid in coops,'known cooperative');coop=coops[cid]
    require(coop['charter']==CHARTER and command['sequence']==coop['sequence']+1,'charter or sequence mismatch')
    if action=='leave':
        require(set(args)=={'member'} and args['member'] in coop['members']
                and set(voters)=={args['member']},'only member can exercise own exit')
        del coop['members'][args['member']]
    else:
        quorum(coop['members'],voters)
        if action=='admit':
            require(set(args)=={'public_key'},'admission fields');new=identity(args['public_key'])
            require(new not in coop['members'] and new in voters and len(coop['members'])<256,'new member consent/budget')
            coop['members'][new]=args['public_key']
        else:
            require(set(args)=={'partner'} and type(args['partner'])is str and args['partner'] in coops
                    and args['partner']!=cid,'independent federation partner')
            partner=coops[args['partner']]
            if action=='federate':
                require(args['partner'] not in coop['federations'],'already federated')
                quorum(partner['members'],voters)
                coop['federations'].append(args['partner']);partner['federations'].append(cid)
            else:
                require(args['partner'] in coop['federations'],'existing federation')
                coop['federations'].remove(args['partner']);partner['federations'].remove(cid)
            partner['sequence']+=1
            partner['federations'].sort()
            # Federation never combines member lists, identities or authority.
        coop['federations'].sort()
    coop['sequence']=command['sequence']
    return result

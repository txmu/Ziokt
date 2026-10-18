"""Optional shared namespaces carried by native Corium IBC checkpoint proofs.

An explicitly configured home chain owns the namespace. Other chains mirror
short-lived bindings; they cannot silently become another naming authority.
Trusted checkpoints remain independently governed and are never advanced here.
"""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import time
from .protocol import ProtocolError,encoded,strict_json

FORMAT='CORIUM_IBC_CHECKPOINT_V2'
MESSAGE='ZIOKT_NAME_BINDING_V1'


def reject(message):raise ProtocolError('IBC_NAME_REJECTED',message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def compact(value):
    import json
    return json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()


def header_hash(header):
    fields={'height','hash','previous_hash','timestamp','transactions','transactions_root','validator','signature'}
    if not isinstance(header,dict) or set(header)!=fields:reject('exact checkpoint header required')
    nodes=header['transactions']
    from .naming import KEY
    if not isinstance(nodes,list) or len(nodes)>4096 or any(not isinstance(x,str) or not KEY.fullmatch(x) for x in nodes) or len(set(nodes))!=len(nodes):reject('invalid transaction list')
    if any(type(header[k]) is not int or not 0<=header[k]<2**63 for k in ('height','timestamp')):reject('invalid header position')
    body={k:header[k] for k in ('height','previous_hash','timestamp','transactions')}
    if sha(compact(body))!=header['hash']:reject('unbound block hash')
    level=nodes[:]
    while len(level)>1:level=[sha((level[i]+level[min(i+1,len(level)-1)]).encode()) for i in range(0,len(level),2)]
    if header['transactions_root']!=(level[0] if level else sha(b'')):reject('unbound transaction root')
    return header['hash']


def verify_binding(proof,target,body,*,anchor,destination,source,namespace,activation_height,now=None):
    now=int(time.time()) if now is None else now
    if (not isinstance(proof,dict) or set(proof)!={'format','final_header','header_chain','merkle_proof','source_transaction'} or
            proof['format']!=FORMAT or len(encoded(proof))>262144):reject('bounded native checkpoint proof required')
    final=proof['final_header'];final_hash=header_hash(final)
    headers=proof['header_chain']
    if not isinstance(headers,list) or len(headers)>256 or final['height']<activation_height:reject('unsupported or pre-activation history')
    if final_hash!=anchor:
        current=anchor;expected_height=None;child_time=None;found=False
        for header in headers:
            value=header_hash(header)
            if value!=current:
                if expected_height is None:continue
                reject('broken checkpoint history')
            if expected_height is not None and (header['height']!=expected_height or header['timestamp']>child_time):reject('invalid ancestor position')
            current=header['previous_hash'];expected_height=header['height']-1;child_time=header['timestamp']
            if current==final_hash:
                if final['height']!=expected_height or final['timestamp']>child_time:reject('invalid final position')
                found=True;break
        if not found:reject('binding is not historical to trusted checkpoint')
    if target not in final['transactions']:reject('binding transaction absent')
    merkle=proof['merkle_proof']
    if not isinstance(merkle,dict) or merkle.get('target_tx_hash')!=target:reject('proof transaction differs')
    siblings=merkle.get('siblings')
    if set(merkle)!={'target_tx_hash','siblings'} or not isinstance(siblings,list) or len(siblings)>16:reject('bounded Merkle path required')
    value=target
    from .naming import KEY
    for sibling in siblings:
        if (not isinstance(sibling,dict) or set(sibling)!={'hash','position'} or
                not isinstance(sibling['hash'],str) or not KEY.fullmatch(sibling['hash']) or sibling['position'] not in ('left','right')):reject('invalid Merkle sibling')
        value=sha(((sibling['hash']+value) if sibling['position']=='left' else (value+sibling['hash'])).encode())
    if value!=final['transactions_root']:reject('Merkle root differs')
    raw=proof['source_transaction']
    if not isinstance(raw,str) or sha(raw.encode())!=target:reject('transaction content differs')
    tx=strict_json(raw.encode(),65536)
    if not isinstance(tx,dict) or set(tx)!={'type','data','timestamp'} or tx['type']!='ibc_dispatch':reject('native IBC dispatch required')
    data=tx['data']
    if not isinstance(data,dict) or set(data)!={'target_chain_id','message_type','message_payload'} or data['target_chain_id']!=destination or data['message_type']!=MESSAGE or data['message_payload']!=body:reject('IBC destination or payload differs')
    fields={'namespace','root','source_chain_id','epoch','expires_at','record'}
    if not isinstance(body,dict) or set(body)!=fields or body['namespace']!=namespace or body['source_chain_id']!=source:reject('shared namespace authority differs')
    if type(body['epoch']) is not int or not 1<=body['epoch']<=2**53-1:reject('bounded lease sequence required')
    if type(tx['timestamp']) is not int or type(body['expires_at']) is not int or not now<body['expires_at']<=tx['timestamp']+600:reject('binding lease expired or exceeds budget')
    record=body['record']
    fields={'network_id','owner','revision','expires_at','delegations','published_suffixes'}
    if not isinstance(record,dict) or set(record)!=fields or record['network_id']!=namespace or record['expires_at']>body['expires_at']:reject('record not bounded by its shared namespace lease')
    return {**record,'proof':{'kind':'corium-ibc-shared-namespace','home_chain':source,'destination_chain':destination,
                            'namespace':namespace,'source_transaction':target,'block_hash':final_hash,
                            'checkpoint':anchor,'epoch':body['epoch'],'proof':proof}}


class IBCNames:
    component='corium'
    def __init__(self,*,chain_db,source_chain,destination_chain,namespace,activation_height,checkpoint_expires_at):
        if type(activation_height) is not int or activation_height<1:raise ValueError('explicit source protocol activation height required')
        self.path,self.source,self.destination,self.namespace=chain_db,source_chain,destination_chain,namespace
        self.activation,self.checkpoint_expiry=activation_height,checkpoint_expires_at
    def __call__(self,root):
        if type(self.checkpoint_expiry) is not int or self.checkpoint_expiry<=time.time():reject('governance checkpoint configuration expired')
        with closing(sqlite3.connect(Path(self.path).absolute().as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            db.execute('BEGIN')
            row=db.execute("SELECT last_known_header_hash FROM ibc_verifiers WHERE target_chain_id=? AND is_active=1 AND verifier_id='BUILT_IN:hash-chain-v1'",(self.source,)).fetchone()
            if not row:reject('active native IBC verifier missing')
            records=db.execute("SELECT source_tx_hash,message_payload,proof_data FROM ibc_incoming_queue WHERE source_chain_id=? AND message_type=? AND json_extract(message_payload,'$.root')=? AND json_extract(message_payload,'$.namespace')=? LIMIT 1025",(self.source,MESSAGE,root,self.namespace)).fetchall()
        if len(records)>1024:reject('namespace history needs archival before further resolution')
        candidates=[]
        for target,raw,raw_proof in records:
            body=strict_json(raw.encode(),65536);proof=strict_json(raw_proof.encode(),262144)
            # Highest committed lease wins even if expired: never resurrect an
            # older positive answer after an unpublication/revocation lease.
            candidates.append((proof['final_header']['height'],body['epoch'],target,body,proof))
        if not candidates:raise ProtocolError('NAME_NOT_FOUND','no native IBC naming lease received')
        candidates.sort(key=lambda item:item[:2],reverse=True)
        if len(candidates)>1 and candidates[0][:2]==candidates[1][:2] and candidates[0][2]!=candidates[1][2]:reject('conflicting source leases')
        _,_,target,body,proof=candidates[0]
        return verify_binding(proof,target,body,anchor=row[0],destination=self.destination,source=self.source,
                              namespace=self.namespace,activation_height=self.activation)

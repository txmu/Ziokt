"""Two real independent Corium chains; native dispatch, proof, receive and DNS."""
import base64
import copy
import json
from pathlib import Path
import shlex
import sqlite3
import sys
import time
import unittest
from ziokt.ibc_naming import IBCNames,verify_binding
from ziokt.naming import Names
from ziokt.security import sign
from ziokt.protocol import ProtocolError

class IBCNamingTests(unittest.TestCase):
    def test_two_native_chains_share_only_explicit_namespace(self):
        source_path=Path(__file__).resolve().parents[2]/'Corium'
        sys.path.insert(0,str(source_path))
        try:import test_core as core
        finally:sys.path.pop(0)
        source=core.Fixture();source.network_id='source-a';source.setUp();self.addCleanup(source.doCleanups)
        destination=core.Fixture();destination.network_id='source-b';destination.setUp();self.addCleanup(destination.doCleanups)
        key=bytes(range(32));public=sign({},key,'test')['public_key'];expiry=int(time.time())+300
        delegation={'network_id':'shared-one','component':'corium','path':'corium','parent_revision':1,'revision':1,
                    'expires_at':expiry,'delegate':None,'descriptor':{'public_dns':[{'type':'A','value':'8.8.8.8','ttl':30}],'services':{},'private':None}}
        record={'network_id':'shared-one','owner':public,'revision':1,'expires_at':expiry,'published_suffixes':['corix'],
                'delegations':{'corium':sign(delegation,key,'Ziokt/name-delegation/v1')}}
        binding={'namespace':'shared-one','root':'corium','source_chain_id':'source-a','epoch':1,'expires_at':expiry,'record':record}
        payload={'target_chain_id':'source-b','message_type':'ZIOKT_NAME_BINDING_V1','message_payload':binding}
        source.run_core('blockchain_create_transaction ibc_dispatch '+shlex.quote(json.dumps(payload))+' >/dev/null; blockchain_mine_block')
        with sqlite3.connect(source.chain) as db:
            tx=db.execute("SELECT hash FROM transactions WHERE type='ibc_dispatch'").fetchone()[0]
            anchor=db.execute('SELECT hash FROM blocks ORDER BY height DESC LIMIT 1').fetchone()[0]
        proof=json.loads(source.run_core('_internal_ibc_generate_proof '+tx).stdout)
        envelope={'source_tx_hash':tx,'message_type':'ZIOKT_NAME_BINDING_V1','message_payload':binding,'proof_data':proof}
        with sqlite3.connect(destination.chain) as db:db.execute('INSERT INTO ibc_verifiers VALUES (?,?,?,?,?)',('source-a','BUILT_IN:hash-chain-v1',1,anchor,1))
        receive={'source_chain_id':'source-a','payload_and_proof':base64.b64encode(json.dumps(envelope,separators=(',',':')).encode()).decode()}
        destination.run_core('blockchain_create_transaction ibc_receive '+shlex.quote(json.dumps(receive))+' >/dev/null; blockchain_mine_block')
        adapter=IBCNames(chain_db=destination.chain,source_chain='source-a',destination_chain='source-b',namespace='shared-one',activation_height=1,checkpoint_expires_at=int(time.time())+600)
        names=Names({'corium':adapter},network_id='shared-one')
        self.assertEqual(names.resolve('corium.corix')['records'][0]['value'],'8.8.8.8')
        args={'anchor':anchor,'destination':'source-b','source':'source-a','namespace':'shared-one','activation_height':1}
        for changes in ({'destination':'wrong'},{'source':'wrong'},{'namespace':'another'},{'anchor':'f'*64},{'activation_height':999},{'now':expiry+1}):
            with self.assertRaises(ProtocolError):verify_binding(proof,tx,binding,**{**args,**changes})
        forged=copy.deepcopy(binding);forged['record']['owner']='f'*64
        with self.assertRaises(ProtocolError):verify_binding(proof,tx,forged,**args)
        # Even an authenticated historical block must not turn a future-dated
        # transaction into an arbitrarily long-lived naming lease.
        import hashlib
        future=copy.deepcopy(binding);future['expires_at']=expiry+7200;future['record']['expires_at']=expiry+7200
        future_proof=copy.deepcopy(proof)
        raw=json.dumps({'type':'ibc_dispatch','data':{'target_chain_id':'source-b','message_type':'ZIOKT_NAME_BINDING_V1','message_payload':future},'timestamp':expiry+7000},ensure_ascii=False,separators=(',',':'))
        future_tx=hashlib.sha256(raw.encode()).hexdigest();future_proof['source_transaction']=raw
        header=future_proof['final_header'];header['transactions']=[future_tx];header['transactions_root']=future_tx
        header['hash']=hashlib.sha256(json.dumps({key:header[key] for key in ('height','previous_hash','timestamp','transactions')},ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        future_proof['merkle_proof']={'target_tx_hash':future_tx,'siblings':[]};future_proof['header_chain']=[]
        with self.assertRaisesRegex(ProtocolError,'lease'):verify_binding(future_proof,future_tx,future,**{**args,'anchor':header['hash']})
        with self.assertRaises(ProtocolError):names.resolve('corium.cor')
        with sqlite3.connect(destination.chain) as db:db.execute('UPDATE ibc_verifiers SET is_active=0')
        with self.assertRaises(ProtocolError):names.resolve('corium.corix')

if __name__=='__main__':unittest.main()

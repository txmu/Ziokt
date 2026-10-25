"""Observed relay work -> approved peer witnesses -> native ZKT reputation.

ZKT is non-monetary local reputation. Peer attestations are an explicit operator
trust model, not a trustless bandwidth proof, token mint or main-chain reward.
"""
from contextlib import contextmanager,closing
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from .protocol import ProtocolError,secure_read,strict_json,encoded
from .security import sign,verify
from ._zkt_runtime import zkt_validate_policy,zkt_record_claim

DOMAIN='Ziokt/peer-relay-receipt/v1'


def require(value,message):
    if not value:raise ProtocolError('RELAY_REWARD_REJECTED',message)


class RelayRewards:
    def __init__(self,config,network):
        fields={'root','ledger','network','beneficiary','policy_file','peers','threshold','bytes_per_unit','max_units_per_receipt','max_units_per_day'}
        require(type(config) is dict and set(config)==fields and config['network']==network,'exact network-bound reward configuration required')
        require(type(config['beneficiary']) is str and re.fullmatch('[a-f0-9]{64}',config['beneficiary']),'fixed beneficiary required')
        require(type(config['threshold']) is int and 2<=config['threshold']<=8,'independent peer quorum required')
        for name,low,high in [('bytes_per_unit',4096,1048576),('max_units_per_receipt',1,10000),('max_units_per_day',1,100000)]:
            require(type(config[name]) is int and low<=config[name]<=high,'bounded reward units required')
        peers=config['peers'];require(type(peers) is dict and config['threshold']<=len(peers)<=8,'bounded approved peers required')
        keys=set();identities=set()
        for name,peer in peers.items():
            require(type(name) is str and re.fullmatch('[A-Za-z0-9_-]{1,64}',name),'peer id required')
            require(type(peer) is dict and set(peer)=={'public_key','failure_domain','native_peer_id','pool'},'exact approved peer identity required')
            require(re.fullmatch('[a-f0-9]{64}',str(peer['public_key'])) and peer['public_key'] not in keys,'distinct peer signing keys required')
            require(re.fullmatch('[a-f0-9]{64}',str(peer['native_peer_id'])) and peer['native_peer_id']!=config['beneficiary'] and peer['native_peer_id'] not in identities,'distinct external peer identities required')
            require(re.fullmatch('[A-Za-z0-9_-]{1,64}',str(peer['failure_domain'])) and peer['pool'] in {'trusted','community'},'approved peer domain and pool required')
            keys.add(peer['public_key']);identities.add(peer['native_peer_id'])
        self.config=config;self.network=network
        self.policy=zkt_validate_policy(strict_json(secure_read(config['policy_file'],65536),65536))
        require(self.policy['network_id']==network and 'network_relay' in self.policy['application_services'],'network-scoped ZKT relay rate required')
        self.policy_digest='sha256:'+hashlib.sha256(encoded(self.policy)).hexdigest()
        self.root=Path(config['root'])
        require(self.root.is_absolute() and not self.root.is_symlink(),'private fixed accounting root required')
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True);self.root.chmod(0o700)
        self.path=self.root/'relay-rewards.sqlite';require(not self.path.is_symlink(),'regular accounting database required')
        try:fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        except FileExistsError:pass
        else:os.close(fd)
        info=self.path.lstat();require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1 and not info.st_mode&0o077,'private owner-controlled accounting database required')
        self.ledger=Path(config['ledger']);require(self.ledger.is_absolute() and self.ledger.is_file() and not self.ledger.is_symlink() and self.ledger.stat().st_uid==os.getuid() and self.ledger.stat().st_nlink==1 and not self.ledger.stat().st_mode&0o022,'existing owner-configured native ZKT ledger required')
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS relay_receipts(id TEXT PRIMARY KEY,document TEXT,units INTEGER,day INTEGER,state TEXT,witnesses TEXT,result TEXT)')
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS relay_session ON relay_receipts(json_extract(document,'$.session'))")
            db.execute('CREATE INDEX IF NOT EXISTS relay_daily_budget ON relay_receipts(day,state)')

    @contextmanager
    def transaction(self):
        db=sqlite3.connect(self.path,timeout=15,isolation_level=None)
        try:
            db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE');yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    def observe(self,session,a,b):
        require(a['state']==b['state']=='complete','both native directions must finish')
        require(a['browser_acknowledged_bytes']==b['native_written_bytes'] and b['browser_acknowledged_bytes']==a['native_written_bytes']
                and a['acknowledged_sha256']==b['written_sha256'] and b['acknowledged_sha256']==a['written_sha256'],'native forwarding byte/digest correspondence required')
        total=a['native_written_bytes']+b['native_written_bytes']
        units=min(total//self.config['bytes_per_unit'],self.config['max_units_per_receipt'])
        if units<1:return {'state':'below_minimum','points_awarded':0,'main_chain_settled':False}
        nonce=hashlib.sha256(session.encode()).hexdigest()
        stamp=int(time.time())
        document={'schema':'ziokt.peer-relay-receipt.v1','network':self.network,'session':nonce,
                  'beneficiary':self.config['beneficiary'],'bytes':total,'units':units,
                  'forward_sha256':a['acknowledged_sha256'],'return_sha256':b['acknowledged_sha256'],
                  'observed_at':stamp,'epoch':stamp//86400,'policy_digest':self.policy_digest}
        receipt=hashlib.sha256(encoded(document)).hexdigest()
        with self.transaction() as db:
            existing=db.execute('SELECT id,document FROM relay_receipts WHERE json_extract(document,\'$.session\')=?',(nonce,)).fetchone()
            if existing:return {'state':'awaiting_peer_witnesses','receipt_id':existing[0],'receipt':json.loads(existing[1]),'main_chain_settled':False}
            require(db.execute('SELECT count(*) FROM relay_receipts').fetchone()[0]<100000,'accounting archive required')
            db.execute('INSERT INTO relay_receipts VALUES (?,?,?,?,?,NULL,NULL)',(receipt,json.dumps(document),units,document['epoch'],'awaiting_peer_witnesses'))
        return {'state':'awaiting_peer_witnesses','receipt_id':receipt,'receipt':document,'main_chain_settled':False,'resource_claims_hardware_attested':False}

    def settle(self,receipt,witnesses):
        require(type(receipt) is str and re.fullmatch('[a-f0-9]{64}',receipt),'receipt address required')
        require(type(witnesses) is list and self.config['threshold']<=len(witnesses)<=8,'bounded peer quorum required')
        with self.transaction() as db:
            row=db.execute('SELECT document,units,day,state,result FROM relay_receipts WHERE id=?',(receipt,)).fetchone()
            require(row is not None,'only locally observed native forwarding can earn reputation')
            document=json.loads(row[0]);domains=set();peers=set();trusted=False
            require(document['policy_digest']==self.policy_digest and document['network']==self.network,'same approved reward policy required')
            for entry in witnesses:
                require(type(entry) is dict and set(entry)=={'peer','attestation'} and entry['peer'] in self.config['peers'] and entry['peer'] not in peers,'distinct approved peer witness required')
                peer=self.config['peers'][entry['peer']]
                actual=verify(entry['attestation'],peer['public_key'],DOMAIN,maximum=4096)
                require(actual==document,'peer witness must bind the exact observed relay receipt')
                peers.add(entry['peer']);domains.add(peer['failure_domain']);trusted|=peer['pool']=='trusted'
            require(len(domains)>=self.config['threshold'] and trusted,'independent domains and a trusted verifier required')
            if row[3]=='awarded':return json.loads(row[4])|{'duplicate':True}
            if row[3]!='settling':
                reserved=db.execute("SELECT COALESCE(sum(units),0) FROM relay_receipts WHERE day=? AND state IN ('settling','awarded')",(row[2],)).fetchone()[0]
                require(reserved+row[1]<=self.config['max_units_per_day'],'daily reputation budget exhausted')
                db.execute("UPDATE relay_receipts SET state='settling',witnesses=? WHERE id=?",(json.dumps(witnesses),receipt))
        claim={'schema':'ziokt.zkt-service-claim.v1','operator':document['beneficiary'],'provider':'corium',
               'service_kind':'application','service_name':'network_relay','units_delivered':document['units'],
               'evidence_digest':'sha256:'+receipt,'epoch':document['epoch'],'nonce':document['session']}
        try:result=zkt_record_claim(self.ledger,claim,self.policy)
        except (ProtocolError,sqlite3.IntegrityError) as error:
            if isinstance(error,ProtocolError) and error.code!='ZKT_DUPLICATE_CLAIM':raise
            with closing(sqlite3.connect(self.ledger)) as db:
                old=db.execute('SELECT claim_id,points FROM zkt_claims WHERE operator=? AND evidence_digest=? AND nonce=?',(claim['operator'],claim['evidence_digest'],claim['nonce'])).fetchone()
            require(old is not None,'native reward intent requires reconciliation')
            result={'status':'awarded','claim_id':old[0],'points_awarded':old[1]}
        result.update(receipt_id=receipt,reward_kind='native-zkt-local-reputation',main_chain_settled=False,
                      token_transfer=False,peer_quorum_verified=True,anonymity_verified=False)
        with self.transaction() as db:db.execute("UPDATE relay_receipts SET state='awarded',result=? WHERE id=?",(json.dumps(result),receipt))
        return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--receipt',type=Path,required=True);parser.add_argument('--key',type=Path,required=True);parser.add_argument('--peer',required=True)
    args=parser.parse_args();value=strict_json(secure_read(args.receipt,4096),4096)
    require(value.get('schema')=='ziokt.peer-relay-receipt.v1','observed peer relay receipt required')
    # Operator supplies only a receipt independently checked against its own
    # forwarding observation; a signing key is never accepted by the public API.
    print(json.dumps({'peer':args.peer,'attestation':sign(value,secure_read(args.key,32),DOMAIN)}))


if __name__=='__main__':main()

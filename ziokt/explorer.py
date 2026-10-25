"""Bounded read-only views of the configured local Corium canonical chain."""
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import stat
from urllib.parse import urlsplit,parse_qs
from .protocol import ProtocolError
from ._verified_guards import same_chain_domain

HEX=re.compile(r'[0-9a-f]{64}\Z')

class ChainExplorer:
    def __init__(self,state_root,network,expected_genesis=None):
        if not isinstance(network,str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',network):
            raise ProtocolError('INVALID_CONFIG','bounded native network identifier required')
        if expected_genesis is not None and (not isinstance(expected_genesis,str) or not HEX.fullmatch(expected_genesis)):
            raise ProtocolError('INVALID_CONFIG','exact genesis digest required')
        self.path=Path(state_root)/'var/lib/corix/networks'/network/'blockchain/chain.db'
        self.network=network
        self.expected_genesis=expected_genesis
        if not self.path.is_absolute() or self.path.resolve()!=self.path or not stat.S_ISREG(self.path.stat().st_mode):
            raise ProtocolError('INVALID_CONFIG','existing regular chain database required')

    def query(self,url):
        if not isinstance(url,str) or len(url)>2048:raise ProtocolError('INVALID_REQUEST','bounded explorer path required')
        route=urlsplit(url);args=parse_qs(route.query,keep_blank_values=True)
        if route.fragment or any(len(v)!=1 for v in args.values()):raise ProtocolError('INVALID_REQUEST','exact explorer query required')
        try:
            with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
                db.execute('PRAGMA query_only=ON');db.execute('PRAGMA trusted_schema=OFF')
                ticks=[0]
                def budget():
                    ticks[0]+=1
                    return ticks[0]>1000
                db.set_progress_handler(budget,1000)
                db.execute('BEGIN')
                tip=db.execute('SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
                if tip is None:raise ProtocolError('CHAIN_UNAVAILABLE','chain has no genesis')
                genesis=db.execute('SELECT hash,timestamp FROM blocks WHERE height=0').fetchone()
                if genesis is None:raise ProtocolError('CHAIN_UNAVAILABLE','chain has no genesis')
                if self.expected_genesis is not None and not same_chain_domain(self.expected_genesis,genesis[0]):
                    raise ProtocolError('NETWORK_MISMATCH','configured genesis differs from chain database')
                base={'network_id':self.network,'genesis_hash':genesis[0],'tip_height':tip[0],'tip_hash':tip[1],'view':'local-canonical','irreversible_finality':False}
                if route.path=='/api/explorer/summary' and not args:
                    pending=db.execute('SELECT count(*) FROM transactions WHERE block_height IS NULL').fetchone()[0]
                    validators=db.execute("SELECT count(*) FROM validators WHERE status='active'").fetchone()[0]
                    genesis=db.execute('SELECT hash,timestamp FROM blocks WHERE height=0').fetchone()
                    return {**base,'pending_transactions':pending,'active_validators':validators,'genesis_hash':genesis[0],'genesis_timestamp':genesis[1]}
                if route.path=='/api/explorer/upgrades' and not args:
                    rows=db.execute("SELECT e.engine_id,e.pkg_id,e.is_active,e.reward_weight,e.compute_program_hash,e.verifier_script_hash,t.block_height,json_extract(t.data,'$.work_consensus.work_policy.activation_height'),json_extract(t.data,'$.openci_policy.activation_height') FROM compute_engines e JOIN transactions t ON t.hash=e.engine_id WHERE t.type='propose_new_compute_engine' AND t.block_height IS NOT NULL AND e.pkg_id IN ('consensus/work-weight:2','compute/openci-attested:1') ORDER BY t.block_height DESC,t.hash LIMIT 33").fetchall()
                    records=[]
                    for row in rows[:32]:
                        completed=db.execute('SELECT count(*) FROM completed_compute_tasks WHERE engine_id=?',(row[0],)).fetchone()[0]
                        records.append({'engine_id':row[0],'package':row[1],'active_in_local_state':bool(row[2]),'reward_weight':row[3],'policy_sha256':row[4],'verifier_sha256':row[5],'proposal_height':row[6],'declared_activation_height':row[7] if row[1]=='consensus/work-weight:2' else row[8],'completed_bounties':completed})
                    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('block_work','zkn_shield_notes')")}
                    proofs=db.execute('SELECT count(*) FROM block_work w JOIN blocks b ON b.hash=w.hash').fetchone()[0] if 'block_work' in tables else 0
                    return {**base,'governance_records':records,'records_truncated':len(rows)>32,'canonical_work_proof_rows':proofs,'business_validation':'not_assessed','remote_verified':'not_assessed','settlement_asset':'contribution_score_not_tokens','effort_work':'engine_zero_distinct_from_native_work_v2','anonymity_guarantee':'not_assessed'}
                if route.path=='/api/explorer/blocks' and set(args)<={'before'}:
                    before=args.get('before',[str(min(tip[0]+1,2**53-1))])[0]
                    if not before.isascii() or not before.isdecimal() or len(before)>16 or not 0<=int(before)<2**53:raise ProtocolError('INVALID_REQUEST','bounded height required')
                    rows=db.execute('SELECT height,hash,previous_hash,timestamp,validator,total_weight,length(transactions) FROM blocks WHERE height<? ORDER BY height DESC LIMIT 20',(int(before),)).fetchall()
                    return {**base,'blocks':[self.block(row,tip[0]) for row in rows],'next_before':rows[-1][0] if rows else None}
                if route.path=='/api/explorer/transactions' and set(args)<={'after','pending'}:
                    after=args.get('after',[''])[0]
                    pending=args.get('pending',['0'])[0]
                    if (after and not HEX.fullmatch(after)) or pending not in {'0','1'}:
                        raise ProtocolError('INVALID_REQUEST','exact transaction cursor and pending flag required')
                    condition='hash>?'+(' AND block_height IS NULL' if pending=='1' else '')
                    rows=db.execute('SELECT hash,type,timestamp,block_height,length(data) FROM transactions WHERE '+condition+' ORDER BY hash LIMIT 21',(after,)).fetchall()
                    return {**base,'transactions':[self.tx(r,tip[0]) for r in rows[:20]],'next_after':rows[19][0] if len(rows)>20 else None,'pending_only':pending=='1'}
                if route.path=='/api/explorer/activity' and not args:
                    rows=db.execute('SELECT b.height,b.timestamp,COUNT(t.hash) FROM blocks b LEFT JOIN transactions t ON t.block_height=b.height WHERE b.height>=? GROUP BY b.height ORDER BY b.height DESC LIMIT 20',(max(0,tip[0]-19),)).fetchall()
                    return {**base,'blocks':[{'height':r[0],'timestamp':r[1],'transaction_count':r[2]} for r in rows]}
                if route.path.startswith('/api/explorer/block/') and set(args)<={'after'}:
                    value=route.path.rsplit('/',1)[1]
                    if HEX.fullmatch(value):where=('hash=?',value)
                    elif value.isascii() and value.isdecimal() and len(value)<=16 and int(value)<2**53:where=('height=?',int(value))
                    else:raise ProtocolError('INVALID_REQUEST','block height or digest required')
                    row=db.execute('SELECT height,hash,previous_hash,timestamp,validator,total_weight,length(transactions) FROM blocks WHERE '+where[0],(where[1],)).fetchone()
                    if not row:raise ProtocolError('NOT_FOUND','block not on local canonical chain')
                    after=args.get('after',[''])[0]
                    if after and not HEX.fullmatch(after):raise ProtocolError('INVALID_REQUEST','transaction digest cursor required')
                    txs=db.execute('SELECT hash,type,timestamp,block_height,length(data) FROM transactions WHERE block_height=? AND hash>? ORDER BY hash LIMIT 101',(row[0],after)).fetchall()
                    return {**base,'block':self.block(row,tip[0]),'transactions':[self.tx(r,tip[0]) for r in txs[:100]],'transactions_truncated':len(txs)>100,'next_after':txs[99][0] if len(txs)>100 else None}
                if route.path.startswith('/api/explorer/transaction/') and not args:
                    value=route.path.rsplit('/',1)[1]
                    if not HEX.fullmatch(value):raise ProtocolError('INVALID_REQUEST','transaction digest required')
                    row=db.execute('SELECT hash,type,timestamp,block_height,length(data) FROM transactions WHERE hash=?',(value,)).fetchone()
                    if not row:raise ProtocolError('NOT_FOUND','transaction not found locally')
                    return {**base,'transaction':self.tx(row,tip[0])}
                raise ProtocolError('NOT_FOUND','unknown explorer endpoint')
        except sqlite3.Error as exc:
            raise ProtocolError('CHAIN_UNAVAILABLE','chain query failed or exceeded resource budget') from exc

    @staticmethod
    def block(row,tip):
        return dict(zip(('height','hash','previous_hash','timestamp','validator','total_weight','transaction_list_bytes'),row))|{'confirmations':max(0,tip-row[0]+1)}

    @staticmethod
    def tx(row,tip):
        return dict(zip(('hash','type','timestamp','block_height','payload_bytes'),row))|{'confirmations':0 if row[3] is None else max(0,tip-row[3]+1),'phase':'pending-native-consensus' if row[3] is None else 'included'}

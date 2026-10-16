"""Bounded read-only views of the configured local Corium canonical chain."""
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import stat
from urllib.parse import urlsplit,parse_qs
from .protocol import ProtocolError

HEX=re.compile(r'[0-9a-f]{64}\Z')

class ChainExplorer:
    def __init__(self,state_root,network):
        self.path=Path(state_root)/'var/lib/corix/networks'/network/'blockchain/chain.db'
        self.network=network
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
                base={'network_id':self.network,'tip_height':tip[0],'tip_hash':tip[1],'view':'local-canonical','irreversible_finality':False}
                if route.path=='/api/explorer/summary' and not args:
                    pending=db.execute('SELECT count(*) FROM transactions WHERE block_height IS NULL').fetchone()[0]
                    validators=db.execute("SELECT count(*) FROM validators WHERE status='active'").fetchone()[0]
                    genesis=db.execute('SELECT hash,timestamp FROM blocks WHERE height=0').fetchone()
                    return {**base,'pending_transactions':pending,'active_validators':validators,'genesis_hash':genesis[0],'genesis_timestamp':genesis[1]}
                if route.path=='/api/explorer/blocks' and set(args)<={'before'}:
                    before=args.get('before',[str(min(tip[0]+1,2**53-1))])[0]
                    if not before.isascii() or not before.isdecimal() or len(before)>16 or not 0<=int(before)<2**53:raise ProtocolError('INVALID_REQUEST','bounded height required')
                    rows=db.execute('SELECT height,hash,previous_hash,timestamp,validator,total_weight,length(transactions) FROM blocks WHERE height<? ORDER BY height DESC LIMIT 20',(int(before),)).fetchall()
                    return {**base,'blocks':[self.block(row,tip[0]) for row in rows],'next_before':rows[-1][0] if rows else None}
                if route.path.startswith('/api/explorer/block/') and not args:
                    value=route.path.rsplit('/',1)[1]
                    if HEX.fullmatch(value):where=('hash=?',value)
                    elif value.isascii() and value.isdecimal() and len(value)<=16 and int(value)<2**53:where=('height=?',int(value))
                    else:raise ProtocolError('INVALID_REQUEST','block height or digest required')
                    row=db.execute('SELECT height,hash,previous_hash,timestamp,validator,total_weight,length(transactions) FROM blocks WHERE '+where[0],(where[1],)).fetchone()
                    if not row:raise ProtocolError('NOT_FOUND','block not on local canonical chain')
                    txs=db.execute('SELECT hash,type,timestamp,block_height,length(data) FROM transactions WHERE block_height=? ORDER BY hash LIMIT 101',(row[0],)).fetchall()
                    return {**base,'block':self.block(row,tip[0]),'transactions':[self.tx(r,tip[0]) for r in txs[:100]],'transactions_truncated':len(txs)>100}
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

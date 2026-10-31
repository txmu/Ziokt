#!/usr/bin/env python3
"""Sync an independent node from a public ledger snapshot with full native replay.

The received derived state is discarded. Identity keys and peer routing stay local.
"""
import argparse,hashlib,json,os,shutil,sqlite3,subprocess,tempfile
from pathlib import Path

SCRIPT=r'''
set -e
export CORIUM_ROOT="$2" CORIUM_NETWORK_ID_OVERRIDE="$3"
source "$1"
load_config
acquire_lock network
acquire_lock system
original_chain="$BLOCKCHAIN_DB";original_forum="$FORUM_DB"
_internal_consensus_safety_check
BLOCKCHAIN_DB="$4/blockchain/chain.db"
_internal_replay_chain_state "$5" "$4/verified"
BLOCKCHAIN_DB="$original_chain"
( BLOCKCHAIN_DB="$4/verified/chain.db";FORUM_DB="$4/verified/forum.db";_internal_semantic_state ) > "$4/verified/state.json"
ancestor=$(python3 - "$original_chain" "$4/verified/chain.db" <<'ANCESTOR'
import sqlite3,sys
with sqlite3.connect(sys.argv[1]) as old,sqlite3.connect(sys.argv[2]) as new:
    incoming=dict(new.execute('SELECT height,hash FROM blocks'))
    ancestor=None
    for height,digest in old.execute('SELECT height,hash FROM blocks ORDER BY height'):
        if incoming.get(height)!=digest:break
        ancestor=digest
    if ancestor is None:raise ValueError('unrelated ledger')
    previous=old.execute('SELECT hash,total_weight FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
    candidate=new.execute('SELECT hash,total_weight FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
    if candidate[0]!=previous[0] and candidate[1]<=previous[1]:raise ValueError('candidate must be strictly heavier')
    print(ancestor)
ANCESTOR
)
_corium_work_consensus fork-guard "$BLOCKCHAIN_DB" "$CORIUM_NETWORK_ID" "$ancestor" >/dev/null
if [ "$6" != apply ]; then printf '{"native_replay":"passed","applied":false}\n';exit 0;fi
db_begin_transaction "$BLOCKCHAIN_DB" "$FORUM_DB"
committed=false
trap 'if ! $committed;then db_rollback_transaction "$original_chain" "$original_forum";fi;release_lock system;release_lock network' EXIT
python3 - "$4/verified/state.json" "$original_chain" "$original_forum" "$4/verified/chain.db" "$4/verified/forum.db" <<'ADOPT'
import sqlite3,json,sys,re
from contextlib import closing
state=json.load(open(sys.argv[1]))
def decode(value):return bytes.fromhex(value['$corium_blob']) if isinstance(value,dict) and set(value)=={'$corium_blob'} else value
with closing(sqlite3.connect(sys.argv[2])) as db:
    db.execute('ATTACH DATABASE ? AS app',(sys.argv[3],));db.execute('BEGIN IMMEDIATE')
    incoming={r['hash'] for r in state['chain']['transactions']}
    pending=[r for r in db.execute('SELECT hash,type,data,signature,public_key,timestamp FROM transactions') if r[0] not in incoming]
    if len(pending)>4096:raise ValueError('local pending transaction budget')
    for label,tables,source_path in [('main',state['chain'],sys.argv[4]),('app',state['application'],sys.argv[5])]:
        with closing(sqlite3.connect(source_path)) as source:
            for table,rows in tables.items():
                if not re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',table):raise ValueError('native table name')
                if not db.execute('SELECT 1 FROM '+label+'.sqlite_master WHERE type="table" AND name=?',(table,)).fetchone():
                    sql=source.execute('SELECT sql FROM sqlite_master WHERE type="table" AND name=?',(table,)).fetchone()[0]
                    db.execute(sql if label=='main' else sql.replace('CREATE TABLE ', 'CREATE TABLE app.',1))
                db.execute('DELETE FROM '+label+'."'+table+'"')
                for row in rows:
                    fields=list(row)
                    db.execute('INSERT INTO '+label+'."'+table+'" ('+','.join('"'+f+'"' for f in fields)+') VALUES ('+','.join('?' for f in fields)+')',[decode(row[f]) for f in fields])
    db.executemany('INSERT INTO transactions(hash,type,data,signature,public_key,timestamp,block_height) VALUES(?,?,?,?,?,?,NULL)',pending)
    tip=db.execute('SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
    db.execute("INSERT OR REPLACE INTO chain_state VALUES('last_processed_height',?)",(str(tip[0]),))
    db.execute("INSERT OR REPLACE INTO chain_state VALUES('chain_info',?)",(tip[1]+'|'+str(tip[0]),))
    db.commit()
ADOPT
_internal_consensus_safety_check
db_commit_transaction "$BLOCKCHAIN_DB" "$FORUM_DB"
committed=true
printf '{"native_replay":"passed","applied":true}\n'
'''

def digest_file(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):value.update(part)
    return value.hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--network',required=True);p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--sha256',required=True);p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    if a.snapshot.is_symlink() or not a.snapshot.is_file() or a.snapshot.stat().st_size>512*1024**2:raise ValueError('bounded regular ledger snapshot required')
    digest=digest_file(a.snapshot)
    if digest!=a.sha256:raise ValueError('snapshot SHA-256 differs')
    a.root=a.root.resolve();area=a.root/'var/lib/corix/sync';area.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.TemporaryDirectory(prefix='verified-',dir=area) as work:
        work=Path(work);(work/'blockchain').mkdir();(work/'forum').mkdir();(work/'verified').mkdir()
        received=work/'blockchain/chain.db';shutil.copyfile(a.snapshot,received);received.chmod(0o600)
        if digest_file(received)!=digest:raise ValueError('snapshot changed during staging')
        with sqlite3.connect(received) as db:
            if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('corrupt snapshot')
            height,tip=db.execute('SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
        # Only local application schemas are supplied, never another host's private data.
        application=a.root/'var/lib/corix/networks'/a.network/'forum/forum.db'
        with sqlite3.connect(application.as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(work/'forum/forum.db') as target:
            for (sql,) in source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):target.execute(sql)
        result=subprocess.run(['bash','-c',SCRIPT,'ziokt-verified-sync',str(a.source.resolve()),str(a.root),a.network,str(work),str(height),'apply' if a.apply else 'verify'],check=True)
        print(json.dumps({'schema':'ziokt.native-verified-sync.v1','network':a.network,'height':height,'hash':tip,'snapshot_sha256':digest,'applied':a.apply,'identity_keys_copied':False}))

if __name__=='__main__':main()

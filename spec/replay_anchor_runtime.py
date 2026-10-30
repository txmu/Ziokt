"""Restore only the exact state committed by an existing signed DNA declaration."""
def replay_anchor(database,network,requested,state_path,chain_path,application_path):
    import stat,os,re
    declaration=Recovery.declaration(network)
    require(declaration is not None and declaration['protocol']==Recovery.SIDE,'DNA recovery declaration required')
    checkpoint=declaration['checkpoint'];height=checkpoint['height']
    require(type(requested)is int and requested>=height,'checkpoint must precede replay height')
    path=Path(state_path);info=path.lstat()
    require(stat.S_ISREG(info.st_mode) and not info.st_mode&0o077 and info.st_uid in (0,os.geteuid()) and info.st_size<=64*1024*1024,'private bounded recovery baseline required')
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,'duplicate baseline key');result[key]=value
        return result
    state=json.loads(path.read_text(),object_pairs_hook=unique)
    require(hashlib.sha256(DNA.encoded(state)).hexdigest()==declaration['initial_state_root'],'signed initial state root differs')
    require(set(state)-{'_custom_schemas'}=={'chain','application'},'exact baseline state fields')
    initial_blocks=state['chain']['blocks']
    require(len(initial_blocks)==height+1 and sorted(row['height'] for row in initial_blocks)==list(range(height+1)),'complete signed archive prefix required')
    anchor=next(row for row in initial_blocks if row['height']==height)
    require(anchor['hash']==checkpoint['hash'],'signed checkpoint anchor differs')
    with sqlite3.connect(database) as source:
        require(source.execute('SELECT hash FROM blocks WHERE height=?',(height,)).fetchone()==(checkpoint['hash'],),'accepted archive checkpoint required')
    with sqlite3.connect(chain_path) as db:
        later_blocks=db.execute('SELECT * FROM blocks WHERE height>? ORDER BY height',(height,)).fetchall()
        later_transactions=db.execute('SELECT * FROM transactions WHERE block_height>?',(height,)).fetchall()
        has_work=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='block_work'").fetchone()
        later_work=db.execute('SELECT w.* FROM block_work w JOIN blocks b ON b.hash=w.hash WHERE b.height>?',(height,)).fetchall() if has_work else []
        work_sql=db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='block_work'").fetchone() if has_work else None
    def cell(value):
        if type(value)is dict:
            require(set(value)=={'$corium_blob'} and type(value['$corium_blob'])is str,'typed baseline blob required')
            return bytes.fromhex(value['$corium_blob'])
        require(value is None or type(value)in (str,int),'baseline scalar required')
        return value
    source_application=Path(database).parent.parent/'forum/forum.db'
    for label,target,original in [('chain',chain_path,database),('application',application_path,source_application)]:
        with sqlite3.connect(Path(original).absolute().as_uri()+'?mode=ro',uri=True) as source:
            native_schemas=dict(source.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        schemas={table:native_schemas[table] for table in state[label] if table in native_schemas}
        schemas.update(state.get('_custom_schemas',{}).get(label,{}))
        with sqlite3.connect(target) as db:
            for table,sql in schemas.items():
                require(re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',table) and type(sql)is str and len(sql)<=65536,'bounded baseline table schema required')
                require(re.match(r'\ACREATE TABLE\s+(?:IF NOT EXISTS\s+)?["`\[]?'+re.escape(table)+r'["`\]]?\s*\(',sql,re.I) and ';' not in sql.rstrip().rstrip(';'),'one literal baseline table schema required')
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():db.execute(sql)
            for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
                require(re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',table),'native table name required');db.execute('DELETE FROM "'+table+'"')
            for table,rows in state[label].items():
                require(re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',table) and type(rows)is list,'baseline table rows required')
                columns=[row[1] for row in db.execute('PRAGMA table_info("'+table+'")')]
                require(columns,'native baseline table unavailable: '+label+'/'+table)
                for row in rows:
                    require(type(row)is dict and set(row)==set(columns),'exact native baseline columns required')
                    db.execute('INSERT INTO "'+table+'" VALUES('+','.join('?' for _ in columns)+')',[cell(row[column]) for column in columns])
            if label=='chain':
                db.executemany('INSERT INTO blocks VALUES(?,?,?,?,?,?,?,?)',later_blocks)
                db.executemany('INSERT INTO transactions VALUES(?,?,?,?,?,?,?)',later_transactions)
                if later_work:
                    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='block_work'").fetchone():db.execute(work_sql[0])
                    db.executemany('INSERT OR REPLACE INTO block_work VALUES('+','.join('?' for _ in later_work[0])+')',later_work)
                db.execute("INSERT OR REPLACE INTO chain_state VALUES('chain_info',?)",(checkpoint['hash']+'|'+str(height),))
                db.execute("INSERT OR REPLACE INTO chain_state VALUES('last_processed_height',?)",(str(height),))
    return {'height':height,'hash':checkpoint['hash'],'initial_state_root':declaration['initial_state_root']}

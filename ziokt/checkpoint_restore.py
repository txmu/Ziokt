"""Materialize verified local checkpoints in a new staging directory, without replay.

This does not authorize remote snapshots or switch a running node's databases.
"""
import json,os,re,sqlite3,tempfile
from pathlib import Path
from .checkpoint_format import assemble,canonical,require
from .checkpoint_store import write_new,sync_directory

def materialize_local(store,target,*,allow_bootstrap=False):
 checkpoint=store.current(allow_bootstrap=allow_bootstrap);require(checkpoint.verification_level in {'local-authenticated-checkpoint','explicitly-trusted-bootstrap'} if allow_bootstrap else checkpoint.verification_level=='local-authenticated-checkpoint','owner-local restore requires an owner-local checkpoint')
 target=Path(target).absolute();require(not target.exists()and not target.is_symlink(),'new checkpoint staging destination required');target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 generation=store.generations/checkpoint.manifest['snapshot_hash']
 def read(identity):
  from .checkpoint_store import read_private
  from .checkpoint_format import CHUNK
  return read_private(generation/'objects'/(identity+'.chunk'),CHUNK)
 with tempfile.TemporaryDirectory(prefix='.restore-',dir=target.parent)as temporary:
  stage=Path(temporary)
  for role,chain in checkpoint.manifest['chains'].items():
   role_path=stage/role;role_path.mkdir(mode=0o700);state=json.loads(checkpoint.states[role]);schemas=json.loads(assemble(chain['database_schema'],read))
   for label,filename in [('chain','chain.db'),('application','forum.db')]:
    path=role_path/filename
    with sqlite3.connect(path)as db:
     # Recreate native schemas, including late migrations, before restoring rows.
     for name,sql in schemas[label]['tables'].items():
      require(re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',name)and type(sql)is str,'native table schema required')
      require(re.match(r'^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["`\[]?'+re.escape(name)+r'["`\]]?\s*\(',sql,re.I),'native CREATE TABLE required');db.execute(sql)
     for name,rows in state[label].items():
      fields={r[1]for r in db.execute('PRAGMA table_info("'+name+'")')}
      for row in rows:
       require(set(row)<=fields,'native row differs from committed schema')
       if row:
        columns=list(row);values=[bytes.fromhex(row[k]['$corium_blob'])if type(row[k])is dict and set(row[k])=={'$corium_blob'}else row[k]for k in columns]
        db.execute('INSERT INTO "'+name+'"('+','.join('"'+k+'"'for k in columns)+') VALUES('+','.join('?'for _ in columns)+')',values)
     for name,sql in schemas[label]['indexes'].items():
      require(re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',name)and type(sql)is str and re.match(r'^CREATE\s+(?:UNIQUE\s+)?INDEX\s+',sql,re.I),'native CREATE INDEX required');db.execute(sql)
     if label=='chain'and 'chain_state'in schemas[label]['tables']:
      db.executemany('INSERT OR REPLACE INTO chain_state VALUES(?,?)',[('chain_info',chain['block_hash']+'|'+str(chain['height'])),('last_processed_height',str(chain['height']))])
     require(db.execute('PRAGMA integrity_check').fetchall()==[('ok',)],'restored native database integrity failed')
    path.chmod(0o600)
    # Compare all committed rows after SQLite has applied its native types.
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)as db:
     for name,expected in state[label].items():
      columns=[r[1]for r in db.execute('PRAGMA table_info("'+name+'")')]
      query='SELECT * FROM "'+name+'"'+(" WHERE key='core_gpg_authority'"if name=='chain_state'else '')
      rows=[dict(zip(columns,({'$corium_blob':v.hex()}if type(v)is bytes else v for v in row)))for row in db.execute(query)]
      if name in {'mails','messages'}:
       for row in rows:
        for key in ['is_read','priority','local_path']:row.pop(key,None)
      require(sorted(rows,key=canonical)==sorted(expected,key=canonical),'restored native state differs in '+label+'.'+name)
   # Journals stay as signed payloads until a quiesced consumer adoption can
   # reconcile existing native operation receipts; they are never dispatched here.
   for consumer in chain['consumer_state']:write_new(role_path/(consumer['id']+'.journal.json'),assemble(consumer['state'],read))
   sync_directory(role_path)
  write_new(stage/'manifest.json',canonical(checkpoint.manifest));sync_directory(stage);os.rename(stage,target);sync_directory(target.parent)
 return {'snapshot_hash':checkpoint.manifest['snapshot_hash'],'directory':str(target),'verification_level':checkpoint.verification_level,'full_history_replays':0,'production_databases_switched':False}

"""Owner-local RNA journals. These must never be shared as a new node's receipts."""
import json,sqlite3
from contextlib import closing
from pathlib import Path
from .checkpoint_format import canonical,digest,require,hexid,integer,chunk_bytes,MAX_BYTES

SCHEMA='ziokt.consumer-checkpoint.v1'
COLUMNS={
 'sequences':['sender','sequence'],
 'jobs':['id','sender','sequence','frame','command','state','result','error','attempts','next_at'],
 'chain_cursor':['slot','height','hash'],
 'chain_frames':['id','height','hash','timestamp'],
}
STATES={'queued','dispatching','retry','unknown','completed_read','native_committed','rejected'}
TERMINAL={'completed_read','native_committed','rejected'}

def encoded_cell(value):
 require(value is None or type(value)in {str,int,bytes},'unsupported consumer SQLite value')
 return {'$blob':value.hex()}if type(value)is bytes else value

def receipt_root(tables):
 # Include watermarks and uncertain dispatches, as well as completed receipts.
 return digest(b'Ziokt/consumer-receipts/v1\0'+canonical(tables))

def validate_payload(raw,descriptor,chain_id):
 require(type(raw)is bytes and len(raw)<=MAX_BYTES,'consumer byte budget')
 value=json.loads(raw)
 require(canonical(value)==raw,'canonical consumer journal required')
 require(type(value)is dict and set(value)=={'schema','consumer_id','owner_identity','chain_id','tables'},'exact consumer checkpoint required')
 require(value['schema']==SCHEMA and value['consumer_id']==descriptor['id']and value['owner_identity']==descriptor['owner_identity']and value['chain_id']==chain_id,'consumer identity/domain differs')
 tables=value['tables'];require(type(tables)is dict and set(tables)==set(COLUMNS),'complete consumer journal required')
 require(receipt_root(tables)==descriptor['receipts_root'],'consumer receipt commitment differs')
 for table,columns in COLUMNS.items():
  rows=tables[table];require(type(rows)is list and len(rows)<=4096,'consumer row budget')
  require(rows==sorted(rows,key=canonical),'canonical consumer row ordering required')
  for row in rows:
   require(type(row)is dict and set(row)==set(columns),'consumer row fields differ')
   for cell in row.values():
    require(cell is None or type(cell)in {int,str}or (type(cell)is dict and set(cell)=={'$blob'}and type(cell['$blob'])is str),'consumer cell encoding differs')
    if type(cell)is dict:
     require(len(cell['$blob'])<=2*65536 and len(cell['$blob'])%2==0,'consumer blob budget')
     require(bytes.fromhex(cell['$blob']).hex()==cell['$blob'],'canonical consumer blob required')
 cursor=tables['chain_cursor'];require(cursor==[{'slot':1,'height':descriptor['cursor'],'hash':descriptor['canonical_hash']}],'consumer cursor fields differ')
 sequences={}
 for row in tables['sequences']:
  sender=hexid(row['sender']);require(sender not in sequences,'duplicate sender watermark');sequences[sender]=integer(row['sequence'],1)
 jobs={};sender_sequences=set()
 for row in tables['jobs']:
  identity=hexid(row['id']);sender=hexid(row['sender']);sequence=integer(row['sequence'],1)
  require(identity not in jobs and (sender,sequence)not in sender_sequences,'duplicate consumer operation or sequence')
  require(sequences.get(sender,0)>=sequence,'consumer replay watermark is behind journal')
  require(row['state']in STATES,'unknown consumer dispatch state');integer(row['attempts']);integer(row['next_at'])
  require(type(row['frame'])is dict and type(row['command'])is dict,'consumer frame and command bytes required')
  frame=bytes.fromhex(row['frame']['$blob']);command=bytes.fromhex(row['command']['$blob'])
  require(digest(b'Ziokt/DNAConsumer/frame/v1\n'+frame)==identity,'consumer frame identity differs')
  require(len(frame)<=16384 and len(command)<=8192,'consumer frame/command budget')
  require(row['state']not in {'completed_read','native_committed'}or type(row['result'])is dict,'completed consumer operation lacks its receipt')
  jobs[identity]=row;sender_sequences.add((sender,sequence))
 frames=set()
 for row in tables['chain_frames']:
  identity=hexid(row['id']);require(identity in jobs and identity not in frames,'consumer frame origin lacks a unique job')
  integer(row['height']);hexid(row['hash']);integer(row['timestamp']);frames.add(identity)
 return value

def capture(path,consumer_id,owner_identity,chain_id):
 path=Path(path);require(path.is_file()and not path.is_symlink(),'local regular consumer database required')
 with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5))as db:
  db.execute('BEGIN');require(db.execute('PRAGMA integrity_check').fetchall()==[('ok',)],'corrupted consumer database')
  tables={}
  for table,columns in COLUMNS.items():
   require([r[1]for r in db.execute('PRAGMA table_info('+table+')')]==columns,'consumer schema version differs')
   tables[table]=sorted([dict(zip(columns,map(encoded_cell,row)))for row in db.execute('SELECT * FROM '+table)],key=canonical)
 cursor=tables['chain_cursor'];require(len(cursor)==1,'consumer has no canonical cursor')
 descriptor={'id':consumer_id,'owner_identity':hexid(owner_identity),'cursor':cursor[0]['height'],'canonical_hash':cursor[0]['hash'],'receipts_root':receipt_root(tables)}
 raw=canonical({'schema':SCHEMA,'consumer_id':consumer_id,'owner_identity':owner_identity,'chain_id':hexid(chain_id),'tables':tables})
 descriptor['state'],objects=chunk_bytes(raw);validate_payload(raw,descriptor,chain_id)
 return descriptor,objects

def guard_existing(existing,restored):
 """A restore must retain every durable operation and sequence watermark.

 Checking a saved local journal is only one restoration gate. Native operation
 reconciliation and quiesced, atomic database adoption are still required.
 """
 require(all(existing[k]==restored[k]for k in ['schema','consumer_id','owner_identity','chain_id']),'local consumer ownership changed')
 previous=existing['tables'];next_=restored['tables']
 watermarks={r['sender']:r['sequence']for r in next_['sequences']}
 require(all(watermarks.get(r['sender'],0)>=r['sequence']for r in previous['sequences']),'consumer restore would lower replay watermarks')
 jobs={r['id']:r for r in next_['jobs']}
 for old in previous['jobs']:
  require(old['id']in jobs,'consumer restore would forget an admitted operation')
  new=jobs[old['id']]
  require(all(old[k]==new[k]for k in ['sender','sequence','frame','command']),'consumer admitted operation changed')
  if old['state']in TERMINAL or old['state']in {'dispatching','unknown'}:
   require(new==old,'consumer restore would rewind a receipt or uncertain side effect')

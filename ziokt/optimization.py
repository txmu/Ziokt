"""Opt-in, reversible optimization profiles grounded in Expression Model 2.1.

A replica is not an independent observation. Bytes/hashes do not estimate mutual
information, human intent or task risk. Statistical metrics require an explicit
finite target/background model; operational measurements retain their units.
"""
import json
import math
import time

# Every option has an actual consumer. Security invariants are not configurable.
OPTIONS={
 'enabled':(bool,False,None,None),
 'sqlite_cache_kib':(int,2000,256,16384),
 'search_prefix':(bool,True,None,None),
 'search_fuzzy':(bool,False,None,None),
 'search_group_works':(bool,False,None,None),
 'search_page_limit':(int,100,10,100),
 'transfer_parallelism':(int,1,1,4),
 'transfer_prefer_verified_sources':(bool,False,None,None),
 'transfer_quarantine_seconds':(int,0,0,3600),
 'transfer_retries':(int,0,0,2),
 'collect_expired_uploads':(bool,False,None,None),
 'nntp_max_range':(int,1000,10,1000),
}
DEFAULTS={name:definition[1] for name,definition in OPTIONS.items()}
APPLICATIONS={'content','library','netnews','community','applications'}


class Profiles:
 def __init__(self,db,lock):
  self.db,self.lock=db,lock
  db.executescript('''CREATE TABLE IF NOT EXISTS optimization_profiles(scope TEXT PRIMARY KEY,revision INTEGER NOT NULL,settings BLOB NOT NULL,updated INTEGER NOT NULL);
  CREATE TABLE IF NOT EXISTS optimization_audit(id INTEGER PRIMARY KEY,scope TEXT,revision INTEGER,settings BLOB,at INTEGER);''')
 def get(self,owner,application='content'):
  if application not in APPLICATIONS:raise ValueError('optimization application')
  result=dict(DEFAULTS);revisions={}
  with self.lock:
   for scope in ('node','application:'+application,'account:'+owner):
    row=self.db.execute('SELECT revision,settings FROM optimization_profiles WHERE scope=?',(scope,)).fetchone()
    if row:result.update(json.loads(row[1]));revisions[scope]=row[0]
  # Disabled profiles cannot silently change existing execution behavior.
  effective=result if result['enabled'] else dict(DEFAULTS)
  return {'schema':'ziokt.optimization-profile.v1','settings':result,'effective':effective,'revisions':revisions,'security_overrides_allowed':False}
 def set(self,owner,settings,revision,*,application=None,node=False):
  if not isinstance(settings,dict) or set(settings)-set(OPTIONS):raise ValueError('unknown optimization')
  if type(revision) is not int or revision<0:raise ValueError('profile revision')
  for name,value in settings.items():
   kind,_,low,high=OPTIONS[name]
   if type(value) is not kind or (kind is int and not low<=value<=high):raise ValueError('optimization bounds')
  if application is not None and application not in APPLICATIONS:raise ValueError('optimization application')
  scope='node' if node else 'application:'+application if application is not None else 'account:'+owner
  with self.lock,self.db:
   self.db.execute('BEGIN IMMEDIATE')
   row=self.db.execute('SELECT revision,settings FROM optimization_profiles WHERE scope=?',(scope,)).fetchone()
   if (row[0] if row else 0)!=revision:raise ValueError('optimization revision conflict')
   merged=json.loads(row[1]) if row else {};merged.update(settings);raw=json.dumps(merged,sort_keys=True)
   self.db.execute('INSERT OR REPLACE INTO optimization_profiles VALUES(?,?,?,?)',(scope,revision+1,raw,int(time.time())))
   self.db.execute('INSERT INTO optimization_audit(scope,revision,settings,at) VALUES(?,?,?,?)',(scope,revision+1,raw,int(time.time())))
  return {'scope':scope,'revision':revision+1,'settings':merged,'reversible':True}


def finite_metrics(joint,decoder=None):
 """Exact finite-model calculations; no empirical or causal claims."""
 if not isinstance(joint,list) or not 1<=len(joint)<=4096:raise ValueError('finite joint budget')
 distribution={}
 for row in joint:
  if not isinstance(row,dict) or set(row)!={'x','y','z','p'}:raise ValueError('joint fields')
  if any(not isinstance(row[k],str) or len(row[k])>64 for k in ('x','y','z')):raise ValueError('finite state labels')
  p=row['p']
  if type(p) not in {int,float} or not math.isfinite(p) or not 0<=p<=1:raise ValueError('probability')
  key=(row['x'],row['y'],row['z']);distribution[key]=distribution.get(key,0)+p
 if not math.isclose(sum(distribution.values()),1,abs_tol=1e-10):raise ValueError('joint must sum to one')
 pxz={};pyz={};pz={};posterior={}
 for (x,y,z),p in distribution.items():
  pxz[x,z]=pxz.get((x,z),0)+p;pyz[y,z]=pyz.get((y,z),0)+p;pz[z]=pz.get(z,0)+p;posterior.setdefault((y,z),{})[x]=p
 information=sum(p*math.log2(p*pz[z]/(pxz[x,z]*pyz[y,z])) for (x,y,z),p in distribution.items() if p)
 entropy=-sum(p*math.log2(p/pz[z]) for (x,z),p in pxz.items() if p)
 optimal=1-sum(max(values.values()) for values in posterior.values())
 actual=None
 if decoder is not None:
  if not isinstance(decoder,list) or len(decoder)>4096:raise ValueError('decoder budget')
  choices={}
  for row in decoder:
   if not isinstance(row,dict) or set(row)!={'y','z','decision'} or any(not isinstance(v,str) or len(v)>64 for v in row.values()):raise ValueError('decoder fields')
   key=(row['y'],row['z'])
   if key in choices:raise ValueError('duplicate decoder state')
   choices[key]=row['decision']
  if set(choices)!=set(posterior):raise ValueError('decoder must cover every observed signal/background')
  actual=sum(p for (x,y,z),p in distribution.items() if choices[y,z]!=x)
 return {'model':'explicit-finite-joint','information_retained_bits':max(0,information),'optimal_zero_one_risk':max(0,optimal),'actual_zero_one_risk':actual,'interpretation_extra_zero_one_risk':max(0,actual-optimal) if actual is not None else None,'remaining_uncertainty_bits':max(0,entropy-information),'units_kept_separate':True,'independence_inferred':False,'human_intent_inferred':False,'markov_assumption_inferred':False}

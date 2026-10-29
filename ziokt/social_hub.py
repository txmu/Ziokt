"""Account-isolated projections over original authorized read-only MCP tools.

No transport or decryption protocol is introduced. Every query rechecks source
permissions and rereads native data before exposing the local search projection.
"""
import hashlib,json,sqlite3,time
from pathlib import Path
from .protocol import encoded


def field(value,path,default=None):
    if path=='':return value
    for part in path.split('.'):
        if not isinstance(value,dict) or part not in value:return default
        value=value[part]
    return value

class SocialHub:
    def __init__(self,path,service,principal,config):
        self.service,self.principal,self.config=service,principal,config
        self.owner=principal['client'];path=Path(path)
        if path.is_symlink():raise ValueError('social index symlink')
        path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
        self.db=sqlite3.connect(path,timeout=15);path.chmod(0o600)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS social_items(owner TEXT,source TEXT,id TEXT,version TEXT,kind TEXT,deleted INTEGER,payload TEXT,PRIMARY KEY(owner,source,id));
        CREATE TABLE IF NOT EXISTS social_seen(owner TEXT,source TEXT,id TEXT,version TEXT,PRIMARY KEY(owner,source,id));
        CREATE TABLE IF NOT EXISTS social_subscriptions(owner TEXT,source TEXT,enabled INTEGER,PRIMARY KEY(owner,source));
        CREATE VIRTUAL TABLE IF NOT EXISTS social_search USING fts5(owner UNINDEXED,source UNINDEXED,id UNINDEXED,text,tokenize='unicode61');
        ''')
    def close(self):self.db.close()
    def sources(self):
        sources=self.config.get('sources',{}).get(self.owner,{})
        if not isinstance(sources,dict) or len(sources)>32:raise ValueError('at most 32 explicit per-account sources')
        return sources
    def subscribe(self,source,enabled):
        if source not in self.sources() or type(enabled)is not bool:raise ValueError('configured source required')
        with self.db:self.db.execute('INSERT OR REPLACE INTO social_subscriptions VALUES(?,?,?)',(self.owner,source,enabled))
        return {'source':source,'enabled':enabled}
    def acknowledge(self,source,id,version):
        row=self.db.execute('SELECT version FROM social_items WHERE owner=? AND source=? AND id=?',(self.owner,source,id)).fetchone()
        if not row or row[0]!=version:raise ValueError('current item revision required')
        with self.db:self.db.execute('INSERT OR REPLACE INTO social_seen VALUES(?,?,?,?)',(self.owner,source,id,version))
        return {'acknowledged':True,'version':version}
    def refresh(self):
        unavailable=[];sources=self.sources();live=[]
        for alias,s in sources.items():
            subscription=self.db.execute('SELECT enabled FROM social_subscriptions WHERE owner=? AND source=?',(self.owner,alias)).fetchone()
            if subscription and not subscription[0]:continue
            try:
                if not isinstance(s,dict) or set(s)-{'tool','arguments','items','fields','kind','offset','pages','limit'} or not {'tool','items','fields','kind'}<=set(s) or s['kind'] not in {'inbox','content'}:raise ValueError('exact source configuration')
                tool=self.service.tools.get(s['tool'])
                if not tool or tool['annotations']['destructiveHint'] or (s['tool'].startswith('social_') and s['tool']!='social_feed_read') or not self.service.permitted(self.principal,tool):raise PermissionError('original source scope required')
                args=dict(s.get('arguments',{}));pages=s.get('pages',1);limit=s.get('limit',100)
                if type(pages)is not int or not 1<=pages<=32 or type(limit)is not int or not 1<=limit<=100:raise ValueError('source pagination quota')
                rows=[]
                for page in range(pages):
                    if s.get('offset'):args[s['offset']]=page*limit
                    result=self.service.call(self.principal,s['tool'],args)
                    if result.get('isError'):raise PermissionError('native read rejected')
                    items=field(result['structuredContent'],s['items'])
                    if not isinstance(items,list) or len(items)>1000:raise ValueError('source item budget')
                    rows.extend(items)
                    if len(rows)>3200:raise ValueError('source projection quota')
                    if not s.get('offset') or len(items)<limit:break
                normalized={}
                for raw in rows:
                    mapping=s['fields'];native=field(raw,mapping.get('id','id'))
                    if not isinstance(native,str) or not 1<=len(native)<=512:raise ValueError('native item identity required')
                    item={k:field(raw,v) for k,v in mapping.items()}
                    if set(item)-{'id','title','text','author','proof','version','deleted','permissions','origin','url','timestamp'}:raise ValueError('projection field allowlist')
                    # Only explicitly configured summaries are indexed. Ciphertext
                    # and private keys have no field and are never decrypted here.
                    item.update(id=native,source=alias,kind=s['kind'])
                    item['deleted']=item.get('deleted') is True
                    item['version']=str(item.get('version') or hashlib.sha256(encoded(item)).hexdigest())
                    if len(encoded(item))>65536:raise ValueError('item projection budget')
                    if sum(len(encoded(v)) for v in normalized.values())+len(encoded(item))>8*1024*1024:raise ValueError('source index byte quota')
                    normalized[native]=item
                with self.db:
                    self.db.execute('DELETE FROM social_items WHERE owner=? AND source=?',(self.owner,alias))
                    self.db.execute('DELETE FROM social_search WHERE owner=? AND source=?',(self.owner,alias))
                    for item in normalized.values():
                        self.db.execute('INSERT INTO social_items VALUES(?,?,?,?,?,?,?)',(self.owner,alias,item['id'],item['version'],s['kind'],item['deleted'],json.dumps(item)))
                        if not item['deleted']:self.db.execute('INSERT INTO social_search VALUES(?,?,?,?)',(self.owner,alias,item['id'],str(item.get('title') or '')+' '+str(item.get('text') or '')))
                live.append(alias)
            except Exception as error:
                unavailable.append({'source':alias,'reason':type(error).__name__})
        # Fail closed on revocation, offline sources, removed grants or disabled
        # subscriptions: an old private projection cannot outlive source access.
        with self.db:
            for table in ['social_items','social_search']:
                if live:self.db.execute('DELETE FROM '+table+' WHERE owner=? AND source NOT IN ('+','.join('?' for _ in live)+')',(self.owner,*live))
                else:self.db.execute('DELETE FROM '+table+' WHERE owner=?',(self.owner,))
        return unavailable
    def query(self,kind='all',query='',limit=50,offset=0,unread=False):
        if kind not in {'all','inbox','content'} or type(limit)is not int or not 1<=limit<=100 or type(offset)is not int or not 0<=offset<=100000 or not isinstance(query,str) or len(query)>512:raise ValueError('query bounds')
        unavailable=self.refresh();sql='SELECT i.payload,s.version FROM social_items i LEFT JOIN social_seen s ON s.owner=i.owner AND s.source=i.source AND s.id=i.id WHERE i.owner=? AND i.deleted=0';args=[self.owner]
        if kind!='all':sql+=' AND i.kind=?';args.append(kind)
        if unread:sql+=' AND (s.version IS NULL OR s.version<>i.version)'
        if query:
            sql+=' AND EXISTS(SELECT 1 FROM social_search f WHERE f.owner=i.owner AND f.source=i.source AND f.id=i.id AND social_search MATCH ?)';args.append('"'+query.replace('"','""')+'"')
        sql+=' ORDER BY i.source,i.id LIMIT ? OFFSET ?';args.extend([limit,offset])
        items=[]
        for payload,seen in self.db.execute(sql,args):
            item=json.loads(payload);item['unread']=seen!=item['version'];items.append(item)
        return {'items':items,'unavailable':unavailable,'limit':limit,'offset':offset,'native_permissions_rechecked':True}

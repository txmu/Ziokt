"""Bounded durable content repair, private grant delivery and account sync."""
import base64
import json
import secrets
import threading
import time
from .content_private import PrivateFabric,IDENTITY,RECEIPT
from .content_fabric import CHUNK_BYTES,merkle_verify
from .protocol import encoded
from .security import verify


class ContentMaintenance:
    def __init__(self,fabric,config):
        self.f=fabric;self.config=config;self.private=PrivateFabric(fabric);self.stop_event=threading.Event();self.thread=None
        self.interval=config.get('interval',60);self.contact_offset=0
        if type(self.interval)is not int or not 15<=self.interval<=3600:raise ValueError('maintenance interval')
        grace=config.get('gc_grace',14*86400)
        if type(grace)is not int or not 0<=grace<=365*86400:raise ValueError('maintenance garbage collection grace')

    def _job(self,id,action):
        now=int(time.time())
        with self.f.lock:old=self.f.db.execute('SELECT * FROM cf_background_jobs WHERE id=?',(id,)).fetchone()
        if old and old['next_at']>now:return None
        try:
            result=action()
            with self.f.transaction():self.f.db.execute('INSERT OR REPLACE INTO cf_background_jobs VALUES(?,\'ok\',0,?,\'\')',(id,now+self.interval))
            return result
        except Exception as error:
            attempts=min((old['attempts'] if old else 0)+1,12)
            with self.f.transaction():self.f.db.execute('INSERT OR REPLACE INTO cf_background_jobs VALUES(?,\'retry\',?,?,?)',(id,attempts,now+min(3600,15*2**attempts),type(error).__name__))
            return None

    def _deliver(self,row):
        from .content_server import remote
        header=json.loads(row['metadata']);envelope=json.loads(row['envelope'])
        peer=self.private._peer(header['recipient_node'])
        receipt=self.private.deliver(envelope) if header['recipient_node']==self.f.public else remote(peer,{'operation':'private.deliver','arguments':{'envelope':envelope}}) if peer else None
        if receipt is None:raise PermissionError('recipient peer not configured')
        value=verify(receipt,header['recipient_node'],RECEIPT)
        if value!={'id':row['id'],'revision':row['revision'],'recipient':header['recipient']}:raise ValueError('private delivery receipt')
        with self.f.transaction():
            self.f.db.execute('UPDATE cf_private_shares SET delivered=? WHERE id=? AND revision=?',(row['revision'],row['id'],row['revision']))
            if row['source']=='@reading-state' and row['state']=='ready':
                key=self.private._open(row['owner'],row['secret'],['share',row['id'],row['revision']])
                from .content_private import un64
                entries=json.loads(self.private._decrypt(key,header,-1,un64(header['metadata'])))['entries']
                if entries:
                    item=entries[-1];cursor=encoded([item['clock'],item['device'],item['kind'],item['target']]).decode()
                    self.f.db.execute('UPDATE cf_private_contacts SET cursor=? WHERE owner=? AND alias=?',(cursor,row['owner'],row['contact']))
                self.private.revoke(row['owner'],row['id'])
        return value

    def _refresh_contact(self,row):
        from .content_server import remote
        if row['node']==self.f.public:identity=self.private.identity(row['account'])
        else:
            peer=self.f.remote_peers[row['peer']]
            identity=remote(peer,{'operation':'private.identity','arguments':{'account':row['account']}})
        return self.private.contact(row['owner'],row['alias'],identity,row['peer'],bool(row['sync']))

    def _verify_replica(self,obj):
        from .content_server import remote
        meta=json.loads(obj['metadata']);total=(meta['size']+CHUNK_BYTES-1)//CHUNK_BYTES
        with self.f.lock:
            old=self.f.db.execute('SELECT * FROM cf_replica_checks WHERE object=?',(obj['id'],)).fetchone()
            remote_id=self.f.db.execute('SELECT remote FROM locations WHERE local=?',(obj['id'],)).fetchone()
        cursor=int(old['state'].split(':')[1]) if old and old['state'].startswith('checking:') else 0
        for pos in range(cursor,min(total,cursor+8)):
            try:self.f.read_chunk(obj['owner'],obj['id'],pos)
            except Exception:
                repaired=False
                for peer in list(self.f.remote_peers.values())[:4]:
                    try:
                        result=remote(peer,{'operation':'content.object.get','arguments':{'id':remote_id[0] if remote_id else obj['id'],'position':pos}})
                        data=base64.b64decode(result['data'],validate=True);merkle_verify(data,pos,result['proof'],meta['merkle_root'])
                        with self.f.lock,self.f.store(obj['owner']) as store:store.repair_chunk(obj['reference'],pos,data)
                        repaired=True;break
                    except (OSError,ValueError,KeyError,PermissionError):continue
                if not repaired:
                    with self.f.transaction():self.f.db.execute('INSERT OR REPLACE INTO cf_replica_checks VALUES(?,?,?,?)',(obj['id'],int(time.time()),'degraded','verified repair source unavailable'))
                    raise ValueError('replica corrupt and no verified source available')
        cursor=min(total,cursor+8);state='healthy' if cursor==total else 'checking:'+str(cursor)
        with self.f.transaction():self.f.db.execute('INSERT OR REPLACE INTO cf_replica_checks VALUES(?,?,?,\'\')',(obj['id'],int(time.time()),state))
        return {'object':obj['id'],'state':state,'checked_until':cursor}

    def run_once(self):
        from .content_server import sync
        now=int(time.time());p=self.private;f=self.f
        # Resume only explicit F2F download intents, retaining ordinary pause and
        # retry gates. No new source or native friend is discovered implicitly.
        with f.lock:
            exists=f.db.execute("SELECT 1 FROM sqlite_master WHERE name='cf_rs_downloads'").fetchone()
            transfers=f.db.execute("SELECT r.* FROM cf_rs_downloads r JOIN downloads d ON d.id=r.job WHERE d.state NOT IN ('complete','paused') LIMIT 4").fetchall() if exists else []
        if getattr(f,'retroshare_config',{}):
            from .content_server import _download_object
            for row in transfers:
                aliases=json.loads(row['sources'])
                if all(alias in f.remote_peers for alias in aliases):
                    self._job('retroshare:'+row['job'],lambda row=row,aliases=aliases:_download_object(f,row['owner'],json.loads(row['metadata']),row['object'],aliases,f.remote_peers,max_chunks=4,application=row['application']))

        with f.lock:
            keys=f.db.execute('SELECT owner FROM cf_private_keys WHERE created<? LIMIT 4',(now-30*86400,)).fetchall()
            contacts=f.db.execute('SELECT * FROM cf_private_contacts ORDER BY rowid LIMIT 32 OFFSET ?',(self.contact_offset,)).fetchall()
            self.contact_offset=self.contact_offset+32 if len(contacts)==32 else 0
            staging=f.db.execute("SELECT s.owner,s.id FROM cf_private_shares s LEFT JOIN cf_background_jobs j ON j.id='stage:'||s.id WHERE s.state='staging' AND s.expires>? AND coalesce(j.next_at,0)<=? ORDER BY s.rowid LIMIT 4",(now,now)).fetchall()
        for row in keys:self._job('key:'+row['owner'],lambda row=row:p.identity(row['owner'],True))
        with f.transaction():
            for owner in {row['owner'] for row in contacts}:p.backfill(owner)
        for row in contacts:self._job('contact:'+row['owner']+':'+row['alias'],lambda row=row:self._refresh_contact(row))
        for row in staging:self._job('stage:'+row['id'],lambda row=row:p.step(row['owner'],row['id']))
        with f.lock:
            active=f.db.execute("SELECT s.*,c.epoch AS contact_epoch FROM cf_private_shares s JOIN cf_private_contacts c ON c.owner=s.owner AND c.alias=s.contact WHERE s.state='ready' AND s.source<>'@reading-state' AND s.expires>? LIMIT 32",(now,)).fetchall()
        for row in active:
            if json.loads(row['metadata'])['key_epoch']!=row['contact_epoch']:self._job('rekey:'+row['id'],lambda row=row:p.rotate_share(row['owner'],row['id']))
        for row in contacts:
            if not row['sync']:continue
            with f.lock:pending=f.db.execute("SELECT 1 FROM cf_private_shares WHERE owner=? AND contact=? AND source='@reading-state' AND delivered<revision AND state<>'revoked'",(row['owner'],row['alias'])).fetchone()
            if pending:continue
            entries=p.snapshot(row['owner'],row['cursor'])
            if entries:
                share=p.create(row['owner'],'@reading-state',row['alias'],now+7*86400,snapshot=entries);p.step(row['owner'],share['id'])
        with f.lock:outbox=f.db.execute("SELECT s.* FROM cf_private_shares s LEFT JOIN cf_background_jobs j ON j.id='deliver:'||s.id||':'||s.revision WHERE s.delivered<s.revision AND s.state IN ('ready','revoked') AND coalesce(j.next_at,0)<=? ORDER BY s.rowid LIMIT 4",(now,)).fetchall()
        for row in outbox:self._job('deliver:'+row['id']+':'+str(row['revision']),lambda row=row:self._deliver(row))
        # Public catalogue pulls and local ciphertext verification are separate
        # from claims about the number of independent physical replicas.
        for alias in list(f.remote_peers)[:8]:self._job('catalogue:'+alias,lambda alias=alias:sync(f,alias,f.remote_peers))
        with f.lock:
            objects=f.db.execute('SELECT o.* FROM objects o LEFT JOIN cf_replica_checks c ON c.object=o.id ORDER BY coalesce(c.verified,0),o.id LIMIT 2').fetchall()
        for obj in objects:self._job('replica:'+obj['id'],lambda obj=obj:self._verify_replica(obj))
        with f.lock:
            inbox=f.db.execute("SELECT id,owner,envelope FROM cf_private_inbox WHERE state='ready' AND expires>? ORDER BY lease,id LIMIT 4",(now,)).fetchall()
        for row in inbox:
            header=json.loads(row['envelope'])['payload']
            with f.lock:done={r[0] for r in f.db.execute('SELECT position FROM cf_private_packets WHERE id=? AND revision=?',(row['id'],header['revision']))}
            for pos in [i for i in range(header['total']) if i not in done][:4]:self._job('private-replica:'+row['id']+':'+str(pos),lambda row=row,pos=pos:p.read(row['owner'],row['id'],pos))
            with f.transaction():f.db.execute('UPDATE cf_private_inbox SET lease=? WHERE id=?',(now+60,row['id']))
        p.collect(grace=self.config.get('gc_grace',14*86400));f.maintenance()
        with f.lock:
            jobs=[dict(r) for r in f.db.execute('SELECT id,state,attempts,next_at,error FROM cf_background_jobs ORDER BY id LIMIT 64')]
        return {'schema':'ziokt.content-maintenance.v1','jobs':jobs,'at':now}

    def start(self):
        def loop():
            while not self.stop_event.is_set():
                self._job('maintenance',self.run_once)
                self.stop_event.wait(self.interval)
        self.thread=threading.Thread(target=loop,name='content-maintenance',daemon=True);self.thread.start();return self

    def close(self):
        self.stop_event.set()
        if self.thread:self.thread.join(30)

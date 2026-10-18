"""Bounded local application RPC into encrypted, signed Ziokt community events."""
import argparse
import base64
import hashlib
import hmac
import secrets
import threading
from pathlib import Path
import re
import sys

from .ano import defence,evaluate
from .community import Community
from .protocol import ProtocolError,encoded,identifier,secure_read,strict_json

UUID=re.compile('[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\\Z')


class CompanionBridge:
    def __init__(self,path):
        self.path=Path(path);self.config_bytes=secure_read(path)
        config=strict_json(self.config_bytes)
        required={'schema','community_root','policy','owner','encryption_key','signing_key','application','application_key'}
        if not isinstance(config,dict) or not required<=set(config) or set(config)-required-{'inbox','vault_root','exchange_key','component_peers'} or config['schema']!='ziokt.companion-bridge.v1':raise ProtocolError('INVALID_BRIDGE','exact explicitly configured community application bridge required')
        identifier(config['application'],'application')
        self.inbox=None
        if 'inbox' in config:
            import os,stat
            value=Path(config['inbox'])
            if not value.is_absolute() or '..' in value.parts or value.is_symlink() or not value.is_dir():raise ProtocolError('INVALID_BRIDGE','fixed private application inbox required')
            st=value.stat()
            if os.name=='posix' and (st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)&0o077):raise ProtocolError('UNSAFE_FILE','owner-private inbox required')
            self.inbox=value
        self.vault_root=None
        if 'vault_root' in config:
            import os,stat
            value=Path(config['vault_root'])
            if not value.is_absolute() or '..' in value.parts or value.is_symlink() or not value.is_dir():raise ProtocolError('INVALID_BRIDGE','fixed private application vault root required')
            st=value.stat()
            if os.name=='posix' and (st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)&0o077):raise ProtocolError('UNSAFE_FILE','owner-private vault root required')
            self.vault_root=value
        for name in ('community_root','policy','encryption_key','signing_key','application_key'):
            if not isinstance(config[name],str) or not Path(config[name]).is_absolute() or '..' in Path(config[name]).parts:raise ProtocolError('INVALID_BRIDGE','fixed private application paths required')
        self.private=secure_read(config['signing_key'],32);self.appkey=secure_read(config['application_key'],32);self.app=config['application'];self._outbox_lock=threading.RLock()
        self.community=Community(config['community_root'],strict_json(secure_read(config['policy'])),config['owner'],secure_read(config['encryption_key'],32))
        with self.community.db:
            self.community.db.execute('CREATE TABLE IF NOT EXISTS watchat_delivery_acks (channel TEXT NOT NULL,event TEXT NOT NULL,PRIMARY KEY(channel,event))')
            self.community.db.execute('CREATE TABLE IF NOT EXISTS companion_outbox (application TEXT NOT NULL,id TEXT NOT NULL,sealed BLOB NOT NULL,PRIMARY KEY(application,id))')
        from .protocol import make_private
        community_root=Path(config['community_root']);community_root.mkdir(mode=0o700,parents=True,exist_ok=True);make_private(community_root)
        self._pending_path=community_root/('federation-pending-'+hmac.new(secure_read(config['application_key'],32),('Ziokt/pending/'+config['application']).encode(),hashlib.sha256).hexdigest()[:16]+'.jsonl')
        from .security import sign
        public=sign({},self.private,'test')['public_key']
        try:self.community._member(public,'chat' if self.app=='watchat' else 'files')
        except BaseException:self.community.close();raise
        self.links=None
        if 'exchange_key' in config or 'component_peers' in config:
            if not {'exchange_key','component_peers'}<=set(config) or self.vault_root is None:raise ProtocolError('INVALID_LINK','private exchange key, pinned peers and vault root required')
            key_path=Path(config['exchange_key'])
            if not key_path.is_absolute() or '..' in key_path.parts:raise ProtocolError('INVALID_LINK','absolute private exchange key path required')
            from .component_links import ComponentLinks
            self.links=ComponentLinks(self.community,self.app,self.private,secure_read(key_path,32),config['component_peers'],self.vault_root)
        self.drain_pending()

    def close(self):self.community.close()
    def _tag(self,value):return hmac.new(self.appkey,('Ziokt/companion/'+self.app+'/v1/'+value).encode(),hashlib.sha256).hexdigest()
    def _channel(self,a,b):return self._tag('/'.join(sorted((a,b))))

    def _outbox_cipher(self):
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
        return ChaCha20Poly1305(hmac.new(self.appkey,b'Ziokt/companion/outbox/v1',hashlib.sha256).digest())

    def _queue_pending(self,method,params):
        if method not in {'chat.append','file.publish','safefs.publish'} or not isinstance(params,dict):raise ProtocolError('METHOD_UNSUPPORTED','publish outbox operation required')
        body=encoded({'method':method,'params':params})
        if len(body)>16384:raise ProtocolError('BRIDGE_LIMIT','outbox entry exceeds budget')
        tag=self._tag('outbox');identity=hmac.new(self.appkey,body,hashlib.sha256).hexdigest()
        nonce=secrets.token_bytes(12);sealed=nonce+self._outbox_cipher().encrypt(nonce,body,tag.encode())
        with self._outbox_lock,self.community.db:
            count=self.community.db.execute('SELECT COUNT(*) FROM companion_outbox WHERE application=?',(tag,)).fetchone()[0]
            exists=self.community.db.execute('SELECT 1 FROM companion_outbox WHERE application=? AND id=?',(tag,identity)).fetchone()
            if count>=128 and not exists:raise ProtocolError('BRIDGE_LIMIT','durable outbox is full')
            self.community.db.execute('INSERT OR IGNORE INTO companion_outbox VALUES (?,?,?)',(tag,identity,sealed))

    def drain_pending(self):
        """Replay a bounded, encrypted SQLite outbox; duplicate publishes are idempotent."""
        with self._outbox_lock:
            # Migrate old private JSONL queues once. Never follow an attacker-controlled link.
            if self._pending_path.is_symlink():raise ProtocolError('UNSAFE_FILE','legacy outbox symlink denied')
            if self._pending_path.exists():
                raw=secure_read(self._pending_path,1024*1024)
                lines=raw.splitlines()
                if len(lines)>128:raise ProtocolError('BRIDGE_LIMIT','legacy outbox exceeds budget')
                for line in lines:
                    if not line:continue
                    entry=strict_json(line,16384)
                    if not isinstance(entry,dict) or set(entry)!={'method','params'}:raise ProtocolError('INVALID_BRIDGE','invalid legacy outbox entry')
                    self._queue_pending(entry['method'],entry['params'])
                self._pending_path.unlink()
            tag=self._tag('outbox')
            rows=self.community.db.execute('SELECT id,sealed FROM companion_outbox WHERE application=? ORDER BY id LIMIT 128',(tag,)).fetchall()
            for identity,sealed in rows:
                if not isinstance(sealed,bytes) or not 28<=len(sealed)<=16412:raise ProtocolError('INVALID_BRIDGE','invalid durable outbox frame')
                from cryptography.exceptions import InvalidTag
                try:body=self._outbox_cipher().decrypt(sealed[:12],sealed[12:],tag.encode())
                except InvalidTag:raise ProtocolError('DATA_AUTH_REJECTED','outbox authentication rejected')
                entry=strict_json(body,16384)
                if (not isinstance(entry,dict) or set(entry)!={'method','params'} or entry['method'] not in {'chat.append','file.publish','safefs.publish'} or not isinstance(entry['params'],dict) or
                        not hmac.compare_digest(identity,hmac.new(self.appkey,body,hashlib.sha256).hexdigest())):
                    raise ProtocolError('INVALID_BRIDGE','authenticated publish outbox entry required')
                remove=False
                try:self.call(entry['method'],entry['params']);remove=True
                except ProtocolError as exc:
                    if exc.code in {'IDEMPOTENCY_CONFLICT','ARTIFACT_DIGEST_MISMATCH','POLICY_DENIED','INVALID_BRIDGE','METHOD_UNSUPPORTED'}:remove=True
                except OSError:pass
                if remove:
                    with self.community.db:self.community.db.execute('DELETE FROM companion_outbox WHERE application=? AND id=?',(tag,identity))

    def call(self,method,params):
        if secure_read(self.path)!=self.config_bytes:raise ProtocolError('STALE_PLAN','application bridge configuration changed')
        if not isinstance(params,dict):raise ProtocolError('INVALID_BRIDGE','typed local parameters required')
        if method in {'package.build.references','package.verify.references','package.release.references'} or method.startswith('object.') or method in {'component.status','ano.laws','ano.calculate','ano.defence','tc16.run','vault.put','vault.get','vault.publish','tri.put','tri.get','tri.publish','package.build','package.verify','package.publish','sim.reminders.replace','sim.reminders.pull'}:
            from .companion_operations import execute
            return execute(self,method,params)
        if method in {'component.send','component.receive'}:
            if self.links is None:raise ProtocolError('POLICY_DENIED','component exchange is not configured')
            from .safefs import Vault
            vault=Vault(self.vault_root,self.app,self.appkey)
            if method=='component.send':
                if set(params)!={'target','kind','digest','operation'}:raise ProtocolError('INVALID_LINK','exact scoped send request required')
                name,data=vault.get(params['digest'])
                return self.links.send(params['target'],params['kind'],name,data,params['operation'])
            if set(params)!={'event','source'}:raise ProtocolError('INVALID_LINK','exact scoped receive request required')
            delivery=self.links.receive(params['event'],expected_source=params['source'])
            # Keep the received payload scoped to this application. Never evaluate it.
            namespace='links/'+delivery['source']+'/'+delivery['operation']+'/'+delivery['name']
            # Recipient receipts stay local: do not federate extra receipt events.
            scope=self._tag('component-receipt')
            with self.community.lock,self.community.db:
                self.community.db.execute('CREATE TABLE IF NOT EXISTS component_receipts (scope TEXT,event TEXT,digest TEXT,PRIMARY KEY(scope,event))')
                row=self.community.db.execute('SELECT digest FROM component_receipts WHERE scope=? AND event=?',(scope,params['event'])).fetchone()
                if row and (vault.objects/row[0][7:]).exists():
                    name,data=vault.get(row[0])
                    if name!=namespace or data!=delivery['data']:raise ProtocolError('IDEMPOTENCY_CONFLICT','local component receipt changed')
                    item={'digest':row[0],'sealed_size':len(vault.blob(row[0]))}
                else:
                    item=vault.put(namespace,delivery['data'])
                    self.community.db.execute('INSERT OR REPLACE INTO component_receipts VALUES (?,?,?)',(scope,params['event'],item['digest']))
            return {**{k:v for k,v in delivery.items() if k not in {'name','data'}},**item,'schema':'ziokt.component-delivery.v1','plaintext_disclosed':False}
        if method in {'file.publish','file.read'}:
            if self.inbox is None:raise ProtocolError('POLICY_DENIED','application file inbox not enabled')
            if set(params)!={'digest'} or not isinstance(params['digest'],str) or not re.fullmatch('sha256:[a-f0-9]{64}',params['digest']):raise ProtocolError('INVALID_BRIDGE','exact immutable sealed file reference required')
            from .security import sign
            public=sign({},self.private,'test')['public_key'];self.community._member(public,'files')
            digest=params['digest'];key='appfile-'+self._tag(digest)[:48];path=self.inbox/(digest[7:]+'.bin')
            events=self.community.view('files',key)['events']
            if method=='file.read':
                if not events:raise ProtocolError('OBJECT_UNAVAILABLE','scoped sealed file not replicated')
                blob=self.community.get_file(events[0]['body'])
                if 'sha256:'+hashlib.sha256(blob).hexdigest()!=digest:raise ProtocolError('ARTIFACT_DIGEST_MISMATCH','scoped sealed file changed')
                from .cli import write_binary_exclusive
                if path.exists():
                    if secure_read(path,8*1024*1024)!=blob:raise ProtocolError('ARTIFACT_DIGEST_MISMATCH','inbox object changed')
                else:write_binary_exclusive(path,blob)
                return {'digest':digest,'sealed_size':len(blob),'plaintext_disclosed':False}
            blob=secure_read(path,8*1024*1024)
            decision=defence({'immutable_digest':'sha256:'+hashlib.sha256(blob).hexdigest()==digest,'bounded_content':len(blob)<=self.community.limits['file_bytes']},('immutable_digest','bounded_content'))
            if decision['decision']!='allow':raise ProtocolError('POLICY_DENIED','sealed file failed admission')
            if events:
                if any(self.community.get_file(event['body'])!=blob for event in events):raise ProtocolError('IDEMPOTENCY_CONFLICT','scoped file reference changed')
                return {'event':events[0]['id'],'digest':digest,'duplicate':True,'plaintext_disclosed':False}
            manifest=self.community.put_file(blob)
            try:event=self.community.publish(self.private,'files',key,{'name':'Sealed application object',**manifest})
            except OSError:self._queue_pending('file.publish',params);raise
            return {'event':event,'digest':digest,'duplicate':False,'plaintext_disclosed':False}

        if method=='ano.evaluate':
            if set(params)!={'circuit'}:raise ProtocolError('INVALID_BRIDGE','exact Ano circuit required')
            return evaluate(params['circuit'])
        if method=='chat.append':
            if set(params)=={'id','from','to','ciphertext','attachments'} and params.get('attachments')==[]:
                params={**params,'attachment_digests':[]}
            fields={'id','from','to','ciphertext','attachments','attachment_digests'}
            if (set(params)!=fields or any(not isinstance(params[k],str) or not UUID.fullmatch(params[k]) for k in ('id','from','to')) or params['from']==params['to'] or
                    not isinstance(params['attachments'],list) or len(params['attachments'])>2 or
                    not isinstance(params['attachment_digests'],list) or len(params['attachment_digests'])!=len(params['attachments']) or
                    any(not isinstance(n,str) or not re.fullmatch('/uploads/[a-f0-9]{32}\\.bin',n) for n in params['attachments']) or
                    any(not isinstance(d,str) or not re.fullmatch('sha256:[a-f0-9]{64}',d) for d in params['attachment_digests'])):
                raise ProtocolError('INVALID_BRIDGE','bounded opaque chat event required')
            try:cipher=base64.b64decode(params['ciphertext'],validate=True)
            except (ValueError,TypeError):raise ProtocolError('INVALID_BRIDGE','sealed browser message required')
            decision=defence({'private_frame':len(cipher)==2048,'application_scope':self.app=='watchat','distinct_participants':params['from']!=params['to']},('private_frame','application_scope','distinct_participants'))
            if decision['decision']!='allow':raise ProtocolError('POLICY_DENIED','application defensive policy denied')
            channel=self._channel(params['from'],params['to']);key='watchat-'+self._tag(params['id'])[:48]
            packet=encoded({'schema':'ziokt.watchat-sealed.v1','id':params['id'],'sender':self._tag(channel+'/'+params['from']),
                'ciphertext':params['ciphertext'],'attachments':params['attachments'],'attachment_digests':params['attachment_digests']})
            events=self.community.view('chat',key)['events']
            if events:
                for event in events:
                    ref=strict_json(event['body']['text'].encode())
                    prior=self.community.get_file(ref['packet']) if ref.get('schema')=='ziokt.watchat-reference.v1' else b''
                    try:old=strict_json(prior)
                    except ProtocolError:old={}
                    if (event['body']['channel']!=channel or old.get('schema')!='ziokt.watchat-sealed.v1' or
                            old.get('id')!=params['id'] or old.get('sender')!=self._tag(channel+'/'+params['from']) or
                            old.get('ciphertext')!=params['ciphertext'] or old.get('attachments')!=params['attachments'] or
                            old.get('attachment_digests',[])!=params['attachment_digests']):
                        raise ProtocolError('IDEMPOTENCY_CONFLICT','opaque message identifier already has other content')
                return {'event':events[0]['id'],'duplicate':True,'plaintext_disclosed':False}
            body={'channel':channel,'text':encoded({'schema':'ziokt.watchat-reference.v1','packet':self.community.put_file(packet)}).decode()}
            try:event=self.community.publish(self.private,'chat',key,body)
            except OSError:self._queue_pending('chat.append',params);raise
            return {'event':event,'duplicate':False,'plaintext_disclosed':False}

        if method=='chat.pull':
            if set(params)!={'from','to'} or any(not isinstance(params[k],str) or not UUID.fullmatch(params[k]) for k in ('from','to')):raise ProtocolError('INVALID_BRIDGE','fixed opaque conversation required')
            channel=self._channel(params['from'],params['to']);messages=[]
            acked={row[0] for row in self.community.db.execute('SELECT event FROM watchat_delivery_acks WHERE channel=?',(channel,))}
            for event in self.community.view('chat')['events']:
                if event['body']['channel']!=channel:continue
                ref=strict_json(event['body']['text'].encode())
                if ref.get('schema')!='ziokt.watchat-reference.v1':continue
                packet=self.community.get_file(ref['packet'])
                if len(packet)>4096:raise ProtocolError('BRIDGE_LIMIT','opaque message packet exceeds budget')
                value=strict_json(packet);sender=value.get('sender')
                if value.get('schema')!='ziokt.watchat-sealed.v1' or sender not in {self._tag(channel+'/'+p) for p in (params['from'],params['to'])}:continue
                if event['id'] in acked:continue
                attachments=value.get('attachments',[]);digests=value.get('attachment_digests',[])
                if (not isinstance(attachments,list) or not isinstance(digests,list) or len(attachments)!=len(digests) or len(digests)>2 or
                        any(not isinstance(d,str) or not re.fullmatch('sha256:[a-f0-9]{64}',d) for d in digests)):continue
                source=params['from'] if sender==self._tag(channel+'/'+params['from']) else params['to']
                messages.append({'id':value['id'],'from':source,'to':params['to'] if source==params['from'] else params['from'],
                    'kind':'sealed','ciphertext':value['ciphertext'],'attachments':attachments,'attachment_digests':digests,'event':event['id']})
                if len(messages)>=12:break
            return {'messages':messages,'plaintext_disclosed':False}
        if method=='chat.ack':
            if (set(params)!={'from','to','events'} or any(not isinstance(params[k],str) or not UUID.fullmatch(params[k]) for k in ('from','to')) or
                    not isinstance(params['events'],list) or not 1<=len(params['events'])<=12 or
                    any(not isinstance(item,str) or not re.fullmatch('sha256:[a-f0-9]{64}',item) for item in params['events']) or len(set(params['events']))!=len(params['events'])):
                raise ProtocolError('INVALID_BRIDGE','bounded conversation delivery acknowledgement required')
            channel=self._channel(params['from'],params['to']);by_id={item['id']:item for item in self.community.view('chat')['events']}
            valid=[]
            allowed_senders={self._tag(channel+'/'+params['from']),self._tag(channel+'/'+params['to'])}
            for event_id in params['events']:
                event=by_id.get(event_id)
                if not event or event['body'].get('channel')!=channel:raise ProtocolError('POLICY_DENIED','acknowledgement is outside the selected conversation')
                ref=strict_json(event['body']['text'].encode());packet=self.community.get_file(ref['packet']);value=strict_json(packet)
                if value.get('schema')!='ziokt.watchat-sealed.v1' or value.get('sender') not in allowed_senders:raise ProtocolError('POLICY_DENIED','acknowledgement does not name a sealed conversation frame')
                valid.append((channel,event_id))
            with self.community.db:
                self.community.db.executemany('INSERT OR IGNORE INTO watchat_delivery_acks VALUES (?,?)',valid)
            return {'acknowledged':len(valid)}
        if method in {'safefs.publish','safefs.read'}:
            if self.vault_root is None:raise ProtocolError('POLICY_DENIED','application vault root not enabled')
            if set(params)!={'digest'} or not isinstance(params['digest'],str) or not re.fullmatch('sha256:[a-f0-9]{64}',params['digest']):raise ProtocolError('INVALID_BRIDGE','exact immutable sealed vault reference required')
            from .safefs import Vault,MAX_SEALED
            from .security import sign
            public=sign({},self.private,'test')['public_key'];self.community._member(public,'files')
            digest=params['digest'];key='safefs-'+self._tag(digest)[:48]
            vault=Vault(self.vault_root,self.app,self.appkey)
            events=self.community.view('files',key)['events']
            if method=='safefs.read':
                if not events:raise ProtocolError('OBJECT_UNAVAILABLE','scoped sealed vault object not replicated')
                blob=self.community.get_file(events[0]['body'])
                if 'sha256:'+hashlib.sha256(blob).hexdigest()!=digest:raise ProtocolError('ARTIFACT_DIGEST_MISMATCH','scoped sealed vault object changed')
                from .cli import write_binary_exclusive
                obj_path=self.vault_root/'objects'/digest[7:]
                if obj_path.exists():
                    if secure_read(obj_path,MAX_SEALED)!=blob:raise ProtocolError('ARTIFACT_DIGEST_MISMATCH','vault object changed locally')
                else:write_binary_exclusive(obj_path,blob)
                return {'digest':digest,'sealed_size':len(blob),'plaintext_disclosed':False}
            blob=vault.blob(digest)
            decision=defence({'immutable_digest':'sha256:'+hashlib.sha256(blob).hexdigest()==digest,'bounded_content':len(blob)<=self.community.limits['file_bytes']},('immutable_digest','bounded_content'))
            if decision['decision']!='allow':raise ProtocolError('POLICY_DENIED','sealed vault object failed admission')
            if events:
                if any(self.community.get_file(event['body'])!=blob for event in events):raise ProtocolError('IDEMPOTENCY_CONFLICT','scoped vault reference changed')
                return {'event':events[0]['id'],'digest':digest,'duplicate':True,'plaintext_disclosed':False}
            manifest=self.community.put_file(blob)
            try:event=self.community.publish(self.private,'files',key,{'name':'SafeFS encrypted object',**manifest})
            except OSError:self._queue_pending('safefs.publish',params);raise
            return {'event':event,'digest':digest,'duplicate':False,'plaintext_disclosed':False}

        raise ProtocolError('METHOD_UNSUPPORTED','fixed companion bridge operation required')



def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);args=parser.parse_args(argv)
    bridge=CompanionBridge(args.config)
    try:
        for _ in range(4096):
            raw=sys.stdin.buffer.readline(65538)
            if not raw:return 0
            request_id=None
            try:
                if len(raw)>65536 or not raw.endswith(b'\n'):raise ProtocolError('BRIDGE_LIMIT','bounded JSONL request required')
                value=strict_json(raw[:-1]);request_id=value.get('id') if isinstance(value,dict) else None
                if not isinstance(value,dict) or set(value)!={'id','method','params'} or type(request_id) is not int or not 0<=request_id<2**53:raise ProtocolError('INVALID_BRIDGE','correlated typed application request required')
                result={'id':request_id,'ok':True,'result':bridge.call(value['method'],value['params'])}
            except (ProtocolError,OSError,ValueError,KeyError,TypeError) as exc:result={'id':request_id,'ok':False,'error':{'code':getattr(exc,'code','BRIDGE_REJECTED')}}
            sys.stdout.buffer.write(encoded(result)+b'\n');sys.stdout.buffer.flush()
        return 0
    finally:bridge.close()

if __name__=='__main__':raise SystemExit(main())

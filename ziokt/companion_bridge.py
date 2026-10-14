"""Bounded local application RPC into encrypted, signed Ziokt community events."""
import argparse
import base64
import hashlib
import hmac
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
        if not isinstance(config,dict) or not required<=set(config) or set(config)-required-{'inbox','vault_root'} or config['schema']!='ziokt.companion-bridge.v1':raise ProtocolError('INVALID_BRIDGE','exact explicitly configured community application bridge required')
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
        self.private=secure_read(config['signing_key'],32);self.appkey=secure_read(config['application_key'],32);self.app=config['application']
        self.community=Community(config['community_root'],strict_json(secure_read(config['policy'])),config['owner'],secure_read(config['encryption_key'],32))
        from .protocol import make_private
        community_root=Path(config['community_root']);community_root.mkdir(mode=0o700,parents=True,exist_ok=True);make_private(community_root)
        self._pending_path=community_root/('federation-pending-'+hmac.new(secure_read(config['application_key'],32),('Ziokt/pending/'+config['application']).encode(),hashlib.sha256).hexdigest()[:16]+'.jsonl')
        from .security import sign
        public=sign({},self.private,'test')['public_key']
        try:self.community._member(public,'chat' if self.app=='watchat' else 'files')
        except BaseException:self.community.close();raise
        self.drain_pending()

    def close(self):self.community.close()
    def _tag(self,value):return hmac.new(self.appkey,('Ziokt/companion/'+self.app+'/v1/'+value).encode(),hashlib.sha256).hexdigest()
    def _channel(self,a,b):return self._tag('/'.join(sorted((a,b))))

    def _queue_pending(self,method,params):
        line=encoded({'method':method,'params':params})+b'\n'
        with open(self._pending_path,'ab') as f:f.write(line)

    def drain_pending(self):
        """Replay queued publish operations that previously failed due to transient errors."""
        if not self._pending_path.exists():return
        remaining=[]
        try:
            lines=self._pending_path.read_bytes().splitlines(keepends=False)
        except OSError:return
        for line in lines:
            if not line:continue
            try:
                entry=strict_json(line)
                if not isinstance(entry,dict) or not isinstance(entry.get('method'),str) or not isinstance(entry.get('params'),dict):continue
                self.call(entry['method'],entry['params'])
            except ProtocolError as exc:
                # Idempotent duplicates and digest conflicts are not re-queued.
                if exc.code in {'IDEMPOTENCY_CONFLICT','ARTIFACT_DIGEST_MISMATCH','STALE_PLAN','POLICY_DENIED','INVALID_BRIDGE','METHOD_UNSUPPORTED'}:continue
                remaining.append(line)
            except OSError:remaining.append(line)
        if remaining:self._pending_path.write_bytes(b'\n'.join(remaining)+b'\n')
        else:
            try:self._pending_path.unlink()
            except OSError:pass



    def call(self,method,params):
        if secure_read(self.path)!=self.config_bytes:raise ProtocolError('STALE_PLAN','application bridge configuration changed')
        if not isinstance(params,dict):raise ProtocolError('INVALID_BRIDGE','typed local parameters required')
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
            fields={'id','from','to','ciphertext','attachments'}
            if (set(params)!=fields or any(not isinstance(params[k],str) or not UUID.fullmatch(params[k]) for k in ('id','from','to')) or params['from']==params['to'] or
                    not isinstance(params['attachments'],list) or len(params['attachments'])>2 or
                    any(not isinstance(n,str) or not re.fullmatch('/uploads/[a-f0-9]{32}\\.bin',n) for n in params['attachments'])):
                raise ProtocolError('INVALID_BRIDGE','bounded opaque chat event required')
            try:cipher=base64.b64decode(params['ciphertext'],validate=True)
            except (ValueError,TypeError):raise ProtocolError('INVALID_BRIDGE','sealed browser message required')
            decision=defence({'private_frame':len(cipher)==2048,'application_scope':self.app=='watchat','distinct_participants':params['from']!=params['to']},('private_frame','application_scope','distinct_participants'))
            if decision['decision']!='allow':raise ProtocolError('POLICY_DENIED','application defensive policy denied')
            channel=self._channel(params['from'],params['to']);key='watchat-'+self._tag(params['id'])[:48]
            packet=encoded({'schema':'ziokt.watchat-sealed.v1','id':params['id'],'sender':self._tag(channel+'/'+params['from']),
                'ciphertext':params['ciphertext'],'attachments':params['attachments']})
            events=self.community.view('chat',key)['events']
            if events:
                for event in events:
                    ref=strict_json(event['body']['text'].encode())
                    if ref.get('schema')!='ziokt.watchat-reference.v1' or event['body']['channel']!=channel or self.community.get_file(ref['packet'])!=packet:
                        raise ProtocolError('IDEMPOTENCY_CONFLICT','opaque message identifier already has other content')
                return {'event':events[0]['id'],'duplicate':True,'plaintext_disclosed':False}
            body={'channel':channel,'text':encoded({'schema':'ziokt.watchat-reference.v1','packet':self.community.put_file(packet)}).decode()}
            try:event=self.community.publish(self.private,'chat',key,body)
            except OSError:self._queue_pending('chat.append',params);raise
            return {'event':event,'duplicate':False,'plaintext_disclosed':False}

        if method=='chat.pull':
            if set(params)!={'from','to'} or any(not isinstance(params[k],str) or not UUID.fullmatch(params[k]) for k in ('from','to')):raise ProtocolError('INVALID_BRIDGE','fixed opaque conversation required')
            channel=self._channel(params['from'],params['to']);messages=[]
            for event in self.community.view('chat')['events']:
                if event['body']['channel']!=channel:continue
                ref=strict_json(event['body']['text'].encode())
                if ref.get('schema')!='ziokt.watchat-reference.v1':continue
                packet=self.community.get_file(ref['packet'])
                if len(packet)>4096:raise ProtocolError('BRIDGE_LIMIT','opaque message packet exceeds budget')
                value=strict_json(packet);sender=value.get('sender')
                if value.get('schema')!='ziokt.watchat-sealed.v1' or sender not in {self._tag(channel+'/'+p) for p in (params['from'],params['to'])}:continue
                source=params['from'] if sender==self._tag(channel+'/'+params['from']) else params['to']
                messages.append({'id':value['id'],'from':source,'to':params['to'] if source==params['from'] else params['from'],
                    'kind':'sealed','ciphertext':value['ciphertext'],'attachments':value['attachments'],'event':event['id']})
                if len(messages)>=64:break
            return {'messages':messages,'plaintext_disclosed':False}
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

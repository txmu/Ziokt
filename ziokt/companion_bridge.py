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
        if not isinstance(config,dict) or set(config)!=required or config['schema']!='ziokt.companion-bridge.v1':raise ProtocolError('INVALID_BRIDGE','exact explicitly configured community application bridge required')
        identifier(config['application'],'application')
        for name in ('community_root','policy','encryption_key','signing_key','application_key'):
            if not isinstance(config[name],str) or not Path(config[name]).is_absolute() or '..' in Path(config[name]).parts:raise ProtocolError('INVALID_BRIDGE','fixed private application paths required')
        self.private=secure_read(config['signing_key'],32);self.appkey=secure_read(config['application_key'],32);self.app=config['application']
        self.community=Community(config['community_root'],strict_json(secure_read(config['policy'])),config['owner'],secure_read(config['encryption_key'],32))
        from .security import sign
        public=sign({},self.private,'test')['public_key']
        try:self.community._member(public,'chat' if self.app=='watchat' else 'files')
        except BaseException:self.community.close();raise

    def close(self):self.community.close()
    def _tag(self,value):return hmac.new(self.appkey,('Ziokt/companion/'+self.app+'/v1/'+value).encode(),hashlib.sha256).hexdigest()
    def _channel(self,a,b):return self._tag('/'.join(sorted((a,b))))

    def call(self,method,params):
        if secure_read(self.path)!=self.config_bytes:raise ProtocolError('STALE_PLAN','application bridge configuration changed')
        if not isinstance(params,dict):raise ProtocolError('INVALID_BRIDGE','typed local parameters required')
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
            event=self.community.publish(self.private,'chat',key,body)
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

"""Opt-in opaque forwarding to one operator-fixed native mainnet endpoint.

No HTTP caller can select a destination. TLS terminates at the original native
endpoint, not in the helper. Waiting for useful traffic never generates probes.
"""
from collections import deque
import ipaddress
import secrets
import socket
import threading
import time
from .protocol import ProtocolError
from .relay_stream import RelayHalf


class DirectRelay:
    def __init__(self, config, network, *, rewards=None):
        fields={'listen','port','target_host','target_port','network_id'}
        if not isinstance(config,dict) or set(config)!=fields or config['network_id']!=network:
            raise ValueError('exact direct relay configuration and matching network required')
        for key in ('port','target_port'):
            if type(config[key]) is not int or not 1<=config[key]<=65535:raise ValueError('literal bounded relay ports required')
        bind=ipaddress.ip_address(config['listen']);target=ipaddress.ip_address(config['target_host'])
        if not target.is_loopback:raise ValueError('direct relay target must be the operator local native service')
        self.rewards=rewards;self.reward_receipts={}
        self.network=network;self.target=(str(target),config['target_port']);self.lock=threading.RLock()
        self.pending=deque();self.sessions={};self.closed=threading.Event();self.reserved=0
        self.listener=socket.socket(socket.AF_INET6 if bind.version==6 else socket.AF_INET)
        self.listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        self.listener.bind((str(bind),config['port']));self.listener.listen(8);self.listener.settimeout(.5)
        self.thread=threading.Thread(target=self._accept,name='mainnet-direct-ingress',daemon=True);self.thread.start()

    def _prune(self):
        now=time.monotonic()
        while self.pending and self.pending[0][0]<=now:self.pending.popleft()[1].close()
        for key,(expires,a,b) in list(self.sessions.items()):
            if expires<=now or a.reason or b.reason:
                self.sessions.pop(key);self.reward_receipts.pop(key,None);a.close('relay_released');b.close('relay_released')

    def _accept(self):
        while not self.closed.is_set():
            with self.lock:self._prune()
            try:stream,_=self.listener.accept()
            except socket.timeout:continue
            except OSError:break
            with self.lock:
                if len(self.pending)>=4 or self.closed.is_set():stream.close()
                else:self.pending.append((time.monotonic()+30,stream))

    def call(self, side, operation, value, authorization=None):
        if side is None and operation=='open':
            if value!={}:raise ValueError('direct open accepts no target or credentials')
            with self.lock:
                self._prune()
                if self.closed.is_set():raise ProtocolError('RELAY_CLOSED','direct relay is stopped')
                if len(self.sessions)+self.reserved>=16:raise ProtocolError('RELAY_BUSY','bounded direct relay slots exhausted')
                if not self.pending:return {'state':'waiting','network_id':self.network,'transport':'direct','retry_ms':5000,'useful_work_verified':False}
                _,incoming=self.pending.popleft();self.reserved+=1
            a=b=outgoing=None
            try:
                outgoing=socket.create_connection(self.target,timeout=5)
                a=RelayHalf(incoming);b=RelayHalf(outgoing);token=secrets.token_urlsafe(32)
                with self.lock:
                    if self.closed.is_set():raise ProtocolError('RELAY_CLOSED','direct relay stopped while opening')
                    self.sessions[token]=(time.monotonic()+300,a,b)
                return {'state':'open','network_id':self.network,'transport':'direct','session':token,'a':{'session':'a'},'b':{'session':'b'},'useful_work_verified':False,'anonymity_verified':False}
            except BaseException:
                if a:a.close('open_failed')
                else:incoming.close()
                if b:b.close('open_failed')
                elif outgoing:outgoing.close()
                raise
            finally:
                with self.lock:self.reserved-=1
        if side not in {'a','b'} or operation not in {'read','write','ack','status','close'}:raise ProtocolError('NOT_FOUND','fixed direct relay operation required')
        fields={'session'}|({'frame'} if operation=='write' else {'sequence'} if operation=='ack' else set())
        if not isinstance(value,dict) or set(value)!=fields or value.get('session')!=side:raise ValueError('exact bounded direct relay fields required')
        if not isinstance(authorization,str) or not authorization.startswith('Bearer ') or not 40<=len(authorization[7:])<=64:raise ProtocolError('AUTH_REQUIRED','ephemeral direct relay capability required')
        with self.lock:
            self._prune();entry=self.sessions.get(authorization[7:])
            if entry is None:raise ProtocolError('AUTH_REJECTED','direct relay capability expired or revoked')
            half=entry[1 if side=='a' else 2]
            if operation=='close':
                self.sessions.pop(authorization[7:]);entry[1].close('helper_stopped');entry[2].close('helper_stopped')
                self.reward_receipts.pop(authorization[7:],None)
                return {'state':'closed'}
        if operation=='read':return half.read()
        if operation in {'write','ack'}:
            result=half.write(value['frame']) if operation=='write' else half.acknowledge(value['sequence'])
            if self.rewards is not None:
                with self.lock:
                    session=authorization[7:]
                    a,b=entry[1].status(),entry[2].status()
                    if a['state']==b['state']=='complete':
                        if session not in self.reward_receipts:self.reward_receipts[session]=self.rewards.observe(session,a,b)
                        result['reputation_receipt']=self.reward_receipts[session]
            return result
        return half.status()

    def close(self):
        self.closed.set();self.listener.close()
        with self.lock:
            for _,stream in self.pending:stream.close()
            self.pending.clear()
            for _,a,b in self.sessions.values():a.close('service_stopped');b.close('service_stopped')
            self.sessions.clear();self.reward_receipts.clear()
        self.thread.join(2)

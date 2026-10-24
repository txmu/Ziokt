"""Bounded opaque stream half for explicitly authorized browser relays.

Browsers need only HTTPS/XHR/JSON/base64. Encryption belongs to the original
endpoints (inner TLS/native protocol), never this forwarding worker. HTTP delivery
acknowledgements measure transport bytes, not useful-work or anonymity proofs.
"""
import base64
from collections import deque
import hashlib
import socket
import threading
import time
from .protocol import ProtocolError

FRAME_BYTES=4096


class RelayHalf:
    def __init__(self,stream,*,clock=time.monotonic,lifetime=300,byte_limit=4*1024*1024):
        if type(lifetime) is not int or not 1<=lifetime<=600 or type(byte_limit) is not int or not 4096<=byte_limit<=16*1024*1024:
            raise ValueError('bounded relay lifetime and byte budget required')
        self.stream=stream;self.clock=clock;self.expires=clock()+lifetime;self.limit=byte_limit
        self.condition=threading.Condition(threading.RLock());self.write_lock=threading.Lock()
        self.queue=deque();self.next_read=0;self.last_ack=-1;self.next_write=0;self.last_write=None
        self.read_bytes=0;self.write_bytes=0;self.acked_bytes=0;self.reason=None
        self.acked_hash=hashlib.sha256();self.written_hash=hashlib.sha256()
        self.rate_credit=8192;self.rate_at=clock()
        self.read_fin=False;self.write_fin=False;self.acked_fin=False
        stream.settimeout(1)
        self.thread=threading.Thread(target=self._reader,name='browser-relay-half',daemon=True);self.thread.start()

    def _live(self):
        if self.reason:raise ProtocolError('RELAY_CLOSED',self.reason)
        if self.clock()>=self.expires:
            self.close('lease_expired');raise ProtocolError('RELAY_EXPIRED','Relay lease expired; reconnect original application')

    def close(self,reason='cancelled'):
        with self.condition:
            if self.reason:return
            self.reason=reason;self.condition.notify_all()
        try:self.stream.shutdown(socket.SHUT_RDWR)
        except Exception:pass
        try:self.stream.close()
        except Exception:pass

    def _reader(self):
        try:
            while True:
                with self.condition:
                    self._live()
                    if self.read_fin:
                        self.condition.wait(.5);continue
                    if len(self.queue)>=2:
                        self.condition.wait(.5);continue
                try:data=self.stream.recv(FRAME_BYTES)
                except (socket.timeout,TimeoutError):continue
                with self.condition:
                    self._live()
                    if self.read_bytes+len(data)>self.limit:
                        self.close('read_budget');return
                    self.read_bytes+=len(data)
                    self.queue.append({'sequence':self.next_read,'kind':'data' if data else 'fin',
                                       'data':base64.b64encode(data).decode()})
                    self.next_read+=1;self.condition.notify_all()
                    if not data:self.read_fin=True
        except Exception:
            if not self.reason:self.close('native_read_failed')

    def read(self):
        with self.condition:
            self._live()
            return {'state':'frame','frame':dict(self.queue[0])} if self.queue else {'state':'idle','retry_ms':250}

    def acknowledge(self,sequence):
        with self.condition:
            self._live()
            if type(sequence) is not int or sequence<0:raise ProtocolError('RELAY_SEQUENCE','Bounded frame sequence required')
            if sequence==self.last_ack:return {'state':'acknowledged','duplicate':True}
            if not self.queue or self.queue[0]['sequence']!=sequence:raise ProtocolError('RELAY_SEQUENCE','Only the pending frame may be acknowledged')
            frame=self.queue.popleft();self.last_ack=sequence
            self.acked_bytes+=len(base64.b64decode(frame['data']));self.acked_hash.update(base64.b64decode(frame['data']))
            if frame['kind']=='fin':self.acked_fin=True
            self.condition.notify_all()
            return {'state':'acknowledged','duplicate':False}

    def write(self,frame):
        if not isinstance(frame,dict) or set(frame)!={'sequence','kind','data'} or type(frame['sequence']) is not int or not 0<=frame['sequence']<2**32 or frame['kind'] not in {'data','fin'} or not isinstance(frame['data'],str) or len(frame['data'])>5464:
            raise ProtocolError('RELAY_FRAME','Exact bounded ordered relay frame required')
        try:data=base64.b64decode(frame['data'],validate=True)
        except (ValueError,TypeError):raise ProtocolError('RELAY_FRAME','Invalid frame encoding') from None
        if base64.b64encode(data).decode()!=frame['data'] or len(data)>FRAME_BYTES or (frame['kind']=='fin')!= (len(data)==0):
            raise ProtocolError('RELAY_FRAME','Canonical data or empty FIN frame required')
        fingerprint=hashlib.sha256(frame['kind'].encode()+data).hexdigest()
        with self.write_lock,self.condition:
            self._live()
            if frame['sequence']==self.next_write-1 and self.last_write==fingerprint:
                return {'state':'native_written','duplicate':True,'bytes':len(data),'useful_work_verified':False}
            if frame['sequence']!=self.next_write or self.write_fin:raise ProtocolError('RELAY_SEQUENCE','Frame gap, replay conflict or closed write direction')
            now=self.clock();self.rate_credit=min(8192,self.rate_credit+max(0,now-self.rate_at)*8192);self.rate_at=now
            if len(data)>self.rate_credit:raise ProtocolError('RELAY_THROTTLED','Per-stream byte rate exhausted; retry the same frame')
            if self.write_bytes+len(data)>self.limit:
                self.close('write_budget');raise ProtocolError('RELAY_BUDGET','Relay byte budget exhausted')
            try:
                if frame['kind']=='fin':self.stream.shutdown(socket.SHUT_WR)
                else:self.stream.sendall(data)
            except Exception:
                # sendall may have partially written. Never replay into this stream.
                self.close('native_write_uncertain');raise ProtocolError('RELAY_WRITE_UNCERTAIN','Native write incomplete; connection closed') from None
            self.rate_credit-=len(data)
            self.next_write+=1;self.last_write=fingerprint;self.write_bytes+=len(data);self.written_hash.update(data)
            self.write_fin=frame['kind']=='fin'
            return {'state':'native_written','duplicate':False,'bytes':len(data),'useful_work_verified':False}

    def status(self):
        with self.condition:
            return {'state':'closed' if self.reason else 'complete' if self.acked_fin and self.write_fin else 'open',
                    'reason':self.reason,'read_bytes':self.read_bytes,'native_written_bytes':self.write_bytes,
                    'browser_acknowledged_bytes':self.acked_bytes,'buffered_frames':len(self.queue),
                    'acknowledged_sha256':self.acked_hash.hexdigest(),'written_sha256':self.written_hash.hexdigest(),
                    'useful_work_verified':False,'anonymity_verified':False}

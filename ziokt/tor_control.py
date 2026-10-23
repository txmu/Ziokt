"""Bounded authenticated local Tor descriptor publication observations.

Publication is a Tor HSDir receipt, not proof of end-to-end application health.
Onion names, relay paths and the authentication cookie are never exported.
"""
from collections import Counter
import ipaddress
from pathlib import Path
import socket
import threading
import time
from .protocol import ProtocolError,secure_read
from .carrier import onion_address


class DescriptorObserver:
    def __init__(self,host,port,cookie,services,timeout=15):
        if not ipaddress.ip_address(host).is_loopback or type(port) is not int or not 1<=port<=65535:
            raise ValueError('explicit local control endpoint required')
        self.services={onion_address(v)[:-6] for v in services}
        if not 1<=len(self.services)<=16:raise ValueError('bounded service set required')
        self.uploaded=set();self.counts=Counter();self.condition=threading.Condition();self.closed=False;self.failed=False
        self.socket=socket.create_connection((host,port),timeout=timeout);self.socket.settimeout(timeout)
        self.stream=self.socket.makefile('rwb');self.thread=None
        try:
            secret=secure_read(Path(cookie),32)
            if len(secret)!=32:raise ValueError('exact Tor cookie required')
            for command in ('AUTHENTICATE '+secret.hex(),'SETEVENTS HS_DESC'):
                self.stream.write(command.encode()+b'\r\n');self.stream.flush();self._reply()
            self.socket.settimeout(None)
            self.thread=threading.Thread(target=self._events,daemon=True);self.thread.start()
        except BaseException:
            self.close();raise

    def _line(self):
        line=self.stream.readline(8193)
        if not line or len(line)>8192:raise OSError('bounded Tor control line required')
        return line.decode('ascii','strict').rstrip('\r\n')

    def _event(self,line):
        fields=line.split()
        if len(fields)>=4 and fields[:2]==['650','HS_DESC'] and fields[3].removesuffix('.onion') in self.services:
            action=fields[2]
            if action not in {'UPLOAD','UPLOADED','FAILED','CREATED','REQUESTED','RECEIVED','IGNORE','CONTENT'}:return
            with self.condition:
                self.counts[action]=min(100000,self.counts[action]+1)
                if action=='UPLOADED':self.uploaded.add(fields[3].removesuffix('.onion'))
                self.condition.notify_all()

    def _reply(self):
        total=0
        for _ in range(64):
            line=self._line();total+=len(line)
            if total>32768:raise OSError('Tor control response budget')
            if line.startswith('650 '):self._event(line);continue
            if line.startswith('250 '):return
            if not line.startswith('250-'):raise OSError('Tor control command rejected')
        raise OSError('Tor control response line budget')

    def _events(self):
        try:
            while not self.closed:self._event(self._line())
        except (OSError,ValueError,UnicodeError):
            with self.condition:
                if not self.closed:self.failed=True
                self.condition.notify_all()

    def wait(self,timeout=180):
        deadline=time.monotonic()+timeout
        with self.condition:
            while self.uploaded!=self.services:
                remaining=deadline-time.monotonic()
                if remaining<=0 or self.failed or self.closed:
                    raise ProtocolError('TOR_DESCRIPTOR_UNPUBLISHED','configured onion services lack observed publication receipts')
                self.condition.wait(remaining)
        return self.health()

    def health(self):
        with self.condition:return {'configured_services':len(self.services),'uploaded_services':len(self.uploaded),'events':dict(self.counts),'control_responding':not self.failed and not self.closed,'application_verified':'not_assessed'}

    def close(self):
        self.closed=True
        try:self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:pass
        if self.thread:self.thread.join(2)
        self.stream.close();self.socket.close()
        with self.condition:self.condition.notify_all()

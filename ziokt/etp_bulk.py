"""FileShare v2: CDC object requests over authenticated, padded native ETP.

The v1 16 KiB wire format stays compatible. V2 streams arbitrarily sized Merkle
files as bounded objects, with a four-segment request window and range retries.
"""
import hashlib
import json
import secrets
import socket
import threading
import time
from .gateway_store import MAX_CHUNK, digest_ok, encoded

SEGMENT=56000
WINDOW=4


class BulkPeer:
    def __init__(self,records):self.records=records;self.lock=threading.Lock()
    def fetch(self,digest):
        if not digest_ok(digest):raise ValueError('invalid object address')
        with self.lock:
            request_id=secrets.token_hex(16);pending={};received={};total=None;next_offset=0;started=time.monotonic()
            def request(offset,attempt=0):
                self.records.send(encoded({'v':2,'id':request_id,'hash':digest,'offset':offset,'length':SEGMENT}))
                pending[offset]=(time.monotonic(),attempt)
            request(0)
            while pending:
                if time.monotonic()-started>120:raise TimeoutError('ETP object deadline')
                try:
                    response=self.records.recv(60000)
                    header,body=response.split(b'\n',1);message=json.loads(header)
                    if message.get('id')!=request_id or message.get('hash')!=digest:continue
                    offset=message.get('offset');size=message.get('size')
                    if type(offset) is not int or offset not in pending or type(size) is not int or not 0<=size<=MAX_CHUNK:raise ValueError('invalid object response')
                    if total is None:total=size;next_offset=min(SEGMENT,total)
                    if size!=total or len(body)!=min(SEGMENT,total-offset):raise ValueError('invalid segment')
                    received[offset]=body;del pending[offset]
                    while len(pending)<WINDOW and next_offset<total:
                        request(next_offset);next_offset+=SEGMENT
                except socket.timeout:
                    for offset,(_,attempt) in list(pending.items()):
                        if attempt>=3:raise TimeoutError('ETP segment retry budget')
                        request(offset,attempt+1)
            data=b''.join(received[offset] for offset in sorted(received))
            if len(data)!=total or hashlib.sha256(data).hexdigest()!=digest:raise ValueError('corrupt ETP object')
            return data


def serve_objects(records,store,stop):
    """Read-only source. No arbitrary paths, remote destinations or disk assembly."""
    while not stop.is_set():
        try:
            raw=records.recv(4096);request=json.loads(raw)
            if set(request)!={'v','id','hash','offset','length'} or request['v']!=2 or not isinstance(request['id'],str) or len(request['id'])!=32 or not digest_ok(request['hash']):continue
            offset=request['offset']
            if type(offset) is not int or not 0<=offset<MAX_CHUNK or request['length']!=SEGMENT:continue
            data=store.get(request['hash'])
            if offset>=len(data) and len(data)!=0:continue
            header=encoded({'v':2,'id':request['id'],'hash':request['hash'],'offset':offset,'size':len(data)})
            records.send(header+b'\n'+data[offset:offset+SEGMENT])
        except (OSError,ValueError,KeyError):continue
        except Exception:
            # A bad encrypted frame cannot terminate the read-only worker.
            if stop.wait(.05):return

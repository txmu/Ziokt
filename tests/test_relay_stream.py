"""Actual socket bytes/half-close/replay/backpressure, no simulated work credit."""
import base64
import socket
import time
import unittest
from ziokt.relay_stream import RelayHalf
from ziokt.protocol import ProtocolError


class RelayStreamTests(unittest.TestCase):
    def half(self,**kwargs):
        outer,inner=socket.socketpair();outer.settimeout(2)
        half=RelayHalf(inner,**kwargs)
        self.addCleanup(outer.close)
        def cleanup():half.close();half.thread.join(2)
        self.addCleanup(cleanup)
        return outer,half

    def frame(self,half):
        until=time.monotonic()+2
        while time.monotonic()<until:
            value=half.read()
            if value['state']=='frame':return value['frame']
            time.sleep(.005)
        self.fail('Actual stream reader did not produce a frame')

    def test_real_bidirectional_transport_and_exact_retry(self):
        a,left=self.half();b,right=self.half()
        a.sendall(b'opaque endpoint record')
        frame=self.frame(left)
        self.assertEqual(left.read()['frame'],frame)
        self.assertFalse(right.write(frame)['duplicate'])
        self.assertTrue(right.write(frame)['duplicate'])
        self.assertEqual(b.recv(4096),b'opaque endpoint record')
        left.acknowledge(frame['sequence']);self.assertTrue(left.acknowledge(frame['sequence'])['duplicate'])
        b.sendall(b'answer');reverse=self.frame(right);left.write(reverse);right.acknowledge(reverse['sequence'])
        self.assertEqual(a.recv(4096),b'answer')
        with self.assertRaises(ProtocolError):right.write({**frame,'data':base64.b64encode(b'tampered').decode()})
        self.assertFalse(right.status()['useful_work_verified'])

    def test_half_close_preserves_reverse_stream(self):
        a,left=self.half();b,right=self.half()
        a.shutdown(socket.SHUT_WR);fin=self.frame(left)
        self.assertEqual(fin['kind'],'fin');right.write(fin);left.acknowledge(fin['sequence'])
        self.assertEqual(b.recv(1),b'')
        b.sendall(b'still replying');frame=self.frame(right);left.write(frame);right.acknowledge(frame['sequence'])
        self.assertEqual(a.recv(100),b'still replying')

    def test_bounded_queue_expiry_and_bad_frames(self):
        now=[10];a,half=self.half(clock=lambda:now[0],lifetime=2)
        for bad in ({'sequence':True,'kind':'data','data':'YQ=='},{'sequence':0,'kind':'fin','data':'YQ=='},
                    {'sequence':0,'kind':'data','data':'A'*5468},{'sequence':2,'kind':'data','data':'YQ=='}):
            with self.assertRaises(ProtocolError):half.write(bad)
        a.sendall(b'x'*12000)
        self.frame(half);time.sleep(.02)
        self.assertLessEqual(half.status()['buffered_frames'],2)
        now[0]=12
        with self.assertRaises(ProtocolError):half.read()
        self.assertEqual(half.status()['state'],'closed')

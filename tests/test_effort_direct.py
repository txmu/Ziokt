"""Real sockets exercise fixed-target forwarding, capabilities and HTTP limits."""
import base64
import http.client
import json
import socket
import threading
import time
import unittest
from ziokt.effort_direct import DirectRelay
from ziokt.effort_web import effort_server
from ziokt.protocol import ProtocolError


def port():
    with socket.socket() as stream:stream.bind(('127.0.0.1',0));return stream.getsockname()[1]


class DirectTests(unittest.TestCase):
    def setUp(self):
        self.target=socket.socket();self.target.bind(('127.0.0.1',0));self.target.listen(2);self.target.settimeout(3);self.addCleanup(self.target.close)
        self.config={'listen':'127.0.0.1','port':port(),'target_host':'127.0.0.1','target_port':self.target.getsockname()[1],'network_id':'ziokt-main'}
        self.relay=DirectRelay(self.config,'ziokt-main');self.addCleanup(self.relay.close)

    def open(self):
        incoming=socket.create_connection(self.relay.listener.getsockname(),timeout=3);self.addCleanup(incoming.close)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            result=self.relay.call(None,'open',{})
            if result['state']=='open':break
            time.sleep(.01)
        self.assertEqual(result['state'],'open');native,_=self.target.accept();native.settimeout(3);self.addCleanup(native.close)
        return result,incoming,native

    def test_waiting_does_not_connect_or_count_fake_contribution(self):
        result=self.relay.call(None,'open',{});self.assertEqual(result['state'],'waiting');self.assertFalse(result['useful_work_verified'])
        self.assertEqual(self.relay.sessions,{})
        with self.assertRaises(ValueError):self.relay.call(None,'open',{'target':'http://evil.invalid'})

    def test_both_directions_native_write_retries_and_revocation(self):
        result,incoming,native=self.open();auth='Bearer '+result['session']
        def transfer(source,side,destination,target):
            source.sendall(b'opaque endpoint TLS records');deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                frame=self.relay.call(side,'read',{'session':side},auth)
                if frame['state']=='frame':break
                time.sleep(.01)
            self.assertEqual(frame['state'],'frame');self.assertEqual(base64.b64decode(frame['frame']['data']),b'opaque endpoint TLS records')
            receipt=self.relay.call(destination,'write',{'session':destination,'frame':frame['frame']},auth)
            self.assertEqual(receipt['state'],'native_written');self.assertFalse(receipt['useful_work_verified'])
            self.assertEqual(target.recv(4096),b'opaque endpoint TLS records')
            self.assertTrue(self.relay.call(destination,'write',{'session':destination,'frame':frame['frame']},auth)['duplicate'])
            self.relay.call(side,'ack',{'session':side,'sequence':frame['frame']['sequence']},auth)
        transfer(incoming,'a','b',native);transfer(native,'b','a',incoming)
        with self.assertRaises(ProtocolError):self.relay.call('a','read',{'session':'a'},'Bearer '+'z'*43)
        self.relay.call('a','close',{'session':'a'},auth)
        with self.assertRaises(ProtocolError):self.relay.call('b','read',{'session':'b'},auth)

    def test_fixed_destination_network_and_bounded_slots(self):
        for changes in [{'target_host':'169.254.169.254'},{'network_id':'other'},{'port':True},{'target_url':'http://evil.invalid'}]:
            with self.assertRaises(ValueError):DirectRelay({**self.config,**changes},'ziokt-main')
        self.relay.reserved=16
        with self.assertRaises(ProtocolError):self.relay.call(None,'open',{})
        self.relay.reserved=0

    def test_http_origin_target_injection_and_no_compute(self):
        class NoCompute:
            def issue(self):raise AssertionError('must not compute for direct forwarding')
        origin='http://127.0.0.1:0';server=effort_server(NoCompute(),origin,direct_relay=self.relay)
        thread=threading.Thread(target=server.serve_forever);thread.start();self.addCleanup(server.server_close);self.addCleanup(thread.join,2);self.addCleanup(server.shutdown)
        def request(path,body,request_origin=origin):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3);conn.request('POST',path,json.dumps(body),{'Host':'127.0.0.1:0','Origin':request_origin,'Content-Type':'application/json'});response=conn.getresponse();data=json.loads(response.read());conn.close();return response.status,data
        status,result=request('/api/people/direct/open',{});self.assertEqual(status,200);self.assertEqual(result['state'],'waiting')
        self.assertNotEqual(request('/api/people/direct/open',{},'https://evil.invalid')[0],200)
        self.assertNotEqual(request('/api/people/direct/open',{'target_host':'127.0.0.1'})[0],200)
        self.assertNotEqual(request('/api/people/direct/a/read',{'session':'a'})[0],200)
        self.assertNotEqual(request('/api/people/direct/open',{'arguments':{},'padding':'x'})[0],200)

if __name__=='__main__':unittest.main()

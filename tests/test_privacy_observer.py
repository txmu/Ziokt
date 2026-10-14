"""Owned loopback observer: relay-visible bytes, adjacent routes and padding."""
import socket
import unittest
import test_community_peer_proxy as proxy_fixture
from ziokt.community_network import sync_remote
from ziokt.protocol import encoded,strict_json
from ziokt.remote import padded_json,valid_padding

class PrivacyObserver(unittest.TestCase):
    setUp=proxy_fixture.PeerProxyTests.setUp
    start=proxy_fixture.PeerProxyTests.start
    proxy=proxy_fixture.PeerProxyTests.proxy

    def test_authenticated_relays_only_see_adjacent_route_and_inner_tls(self):
        observed={};
        for name,server in [('first',self.first),('last',self.last)]:
            observed[name]=bytearray();original=server.get_request
            def tap(original=original,name=name):
                stream,address=original();recv=stream.recv
                def capture(size,*args):
                    data=recv(size,*args)
                    if len(observed[name])<1024*1024:observed[name].extend(data)
                    return data
                stream.recv=capture
                return stream,address
            server.get_request=tap
        result=sync_remote(self.target,self.endpoint,self.context,self.private,publisher=self.public)
        self.assertFalse(result['runtime_ready']);self.assertEqual(self.target.view('wiki'),self.source.view('wiki'))
        for data in observed.values():
            self.assertGreater(len(data),100)
            for secret in (b'opaque through ordinary peers',b'community.checkpoint',b'community.event.put',self.key,self.private):self.assertNotIn(secret,data)
            size=int.from_bytes(data[:4],'big');frame=strict_json(bytes(data[4:4+size]))
            self.assertEqual(set(frame),{'schema','host','port'});self.assertEqual(frame['schema'],'ziokt.proxy-connect.v1')
        first=observed['first'];size=int.from_bytes(first[:4],'big')
        self.assertEqual(strict_json(bytes(first[4:4+size]))['port'],self.last.server_address[1])
        last=observed['last'];size=int.from_bytes(last[:4],'big')
        self.assertEqual(strict_json(bytes(last[4:4+size]))['port'],self.destination.server_port)
        # First relay is unable to decode the final application request.
        self.assertNotIn(encoded({'host':'127.0.0.1','port':self.destination.server_port}),first)

    def test_unauthenticated_http_probe_has_no_product_banner(self):
        for server in (self.first,self.last,self.destination):
            with socket.create_connection(('127.0.0.1',server.server_address[1]),timeout=2) as stream:
                stream.sendall(b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n');stream.settimeout(2)
                try:reply=stream.recv(4096)
                except (ConnectionError,socket.timeout):reply=b''
                for name in (b'Ziokt',b'Shadow6',b'Corium',b'Python',b'HTTP/1.'):self.assertNotIn(name,reply)

class PaddingTests(unittest.TestCase):
    def test_equal_small_frame_buckets_fresh_randomness_and_bounded_json(self):
        a=padded_json({'ok':True,'result':{'text':'x'}},262144)
        b=padded_json({'ok':True,'result':{'text':'x'*3000}},262144)
        again=padded_json({'ok':True,'result':{'text':'x'}},262144)
        self.assertEqual(len(a),16384);self.assertEqual(len(b),16384);self.assertNotEqual(a,again)
        for raw in (a,b,again):self.assertTrue(valid_padding(strict_json(raw)['padding']))
        self.assertFalse(valid_padding(['z']));self.assertFalse(valid_padding(['a'*4097]))

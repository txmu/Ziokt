import socket
import struct
import threading
import unittest

from ziokt.nat import COOKIE,stun_binding
from ziokt.protocol import ProtocolError
from ziokt.routes import admit_endpoint
from ziokt.transport import NativeTransport


class TraversalTests(unittest.TestCase):
    def test_actual_stun_binding_on_same_udp_socket_and_timeout_restored(self):
        server=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);server.bind(('127.0.0.1',0));server.settimeout(2);self.addCleanup(server.close)
        client=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);client.bind(('127.0.0.1',0));client.settimeout(.25);self.addCleanup(client.close)
        def respond():
            request,remote=server.recvfrom(1024)
            address=bytes(a^b for a,b in zip(socket.inet_aton('198.51.100.7'),struct.pack('!I',COOKIE)))
            value=bytes([0,1])+struct.pack('!H',54321^(COOKIE>>16))+address
            server.sendto(struct.pack('!HHI',0x101,12,COOKIE)+request[8:20]+struct.pack('!HH',0x20,len(value))+value,remote)
        worker=threading.Thread(target=respond);worker.start()
        result=stun_binding(client,{'host':'127.0.0.1','port':server.getsockname()[1]})
        worker.join(2);self.assertFalse(worker.is_alive())
        self.assertEqual((result['host'],result['port']),('198.51.100.7',54321));self.assertTrue(result['same_socket_required'])
        self.assertFalse(result['reachability_verified']);self.assertEqual(client.gettimeout(),.25)
        with self.assertRaises(ProtocolError):stun_binding(client,{'host':'127.0.0.1','port':server.getsockname()[1]},privacy='restricted')

    def test_existing_shadow6_reuse_has_no_core_spawn_or_direct_fallback(self):
        calls=[]
        class SDK:
            def connect_handle(self,service,**kwargs):calls.append((service,kwargs));return 'existing-handle'
        self.assertEqual(NativeTransport(SDK()).open('shared/content',kind='stream',reliable=True,ordered=True),'existing-handle')
        self.assertEqual(len(calls),1)
        carrier={'kind':'shadow6-stream','shadow6_root':'/reviewed/Shadow6','registry_path':'/private/services.json','service_name':'shared/content','lock_digest':'sha256:'+'a'*64,'sdk_digest':'sha256:'+'b'*64}
        endpoint={'host':'127.0.0.1','port':8443,'carrier':carrier,'connection_policy':{'mode':'shadow6','allow_direct_fallback':False}}
        self.assertEqual(admit_endpoint('private',endpoint)['mode'],'shadow6')
        endpoint['connection_policy']['allow_direct_fallback']=True
        with self.assertRaises(ProtocolError):admit_endpoint('private',endpoint)

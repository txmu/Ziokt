import http.client
import socket
import struct
import threading
import unittest
from ziokt.dns_server import servers
from ziokt.naming import Names
from ziokt.dns_wire import wire_name

class DNSServerTests(unittest.TestCase):
    def test_real_udp_tcp_and_doh_refuse_unrelated_no_forward(self):
        opened=servers(Names({}),port=0,doh_port=0)
        for server in opened:
            self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
            threading.Thread(target=server.serve_forever,daemon=True).start()
        udp,tcp,doh=opened
        query=struct.pack('!6H',17,0x100,1,0,0,0)+wire_name('example.com')+struct.pack('!HH',1,1)
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.settimeout(2);sock.sendto(query,udp.server_address);reply=sock.recv(4096)
            self.assertEqual(int.from_bytes(reply[2:4],'big')&15,5)
        with socket.create_connection(tcp.server_address,2) as sock:
            sock.sendall(struct.pack('!H',len(query))+query);size=int.from_bytes(sock.recv(2),'big');reply=sock.recv(size)
            self.assertEqual(int.from_bytes(reply[2:4],'big')&15,5)
        connection=http.client.HTTPConnection(*doh.server_address,timeout=2)
        connection.request('POST','/dns-query',query,{'Content-Type':'application/dns-message'})
        result=connection.getresponse();self.assertEqual(result.status,200)
        self.assertEqual(int.from_bytes(result.read()[2:4],'big')&15,5);connection.close()

if __name__=='__main__':unittest.main()

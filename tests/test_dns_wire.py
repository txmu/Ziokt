import struct
import time
import unittest
from ziokt.dns_wire import answer,wire_name,read_question

class DNSWireTests(unittest.TestCase):
    def query(self,name,kind=1):return struct.pack('!6H',42,0x0100,1,0,0,0)+wire_name(name)+struct.pack('!HH',kind,1)
    def test_no_fallback_for_unrelated_names_or_any_amplification(self):
        class Resolver:
            def resolve(self,name):raise AssertionError('must not query source')
        response=answer(self.query('example.com'),Resolver())
        header=struct.unpack('!6H',response[:12]);self.assertEqual(header[1]&15,5);self.assertFalse(header[1]&0xa0)
        response=answer(self.query('community.ziokt',255),Resolver())
        self.assertEqual(struct.unpack('!6H',response[:12])[3],0)
    def test_actual_wire_ipv4_and_bounded_tcp_response(self):
        class Resolver:
            def resolve(self,name):return {'records':[{'type':'A','value':'8.8.8.8','ttl':60}],'expires_at':int(time.time())+100}
        response=answer(self.query('community.ziokt'),Resolver())
        self.assertEqual(response[-4:],b'\x08'*4)
        self.assertEqual(struct.unpack('!6H',response[:12])[3],1)
        self.assertEqual(answer(self.query('community.ziokt'),Resolver(),tcp=True),response)
    def test_compressed_or_multi_question_and_bad_edns_rejected(self):
        class Resolver:pass
        for data in (b'',b'\0'*12,struct.pack('!6H',1,0,1,0,0,0)+b'\xc0\x0c\0\1\0\1',self.query('x.cor')+b'extra'):
            self.assertEqual(struct.unpack('!6H',answer(data,Resolver())[:12])[1]&15,1)

if __name__=='__main__':unittest.main()

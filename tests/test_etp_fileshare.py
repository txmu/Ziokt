"""Controlled schema/denial tests; positive native transfer is a separate CI job."""
import base64
import unittest
from ziokt.etp_fileshare import params,result
from ziokt.protocol import ProtocolError

class FileShareContracts(unittest.TestCase):
    def test_denies_paths_keys_nonliteral_peers_and_chunk_overflow(self):
        for method,args in [('etp.fileshare.chunk',{'hash':'a'*64,'index':True}),('etp.fileshare.chunk',{'hash':'a'*64,'index':1024}),
                            ('etp.fileshare.request',{'hash':'a'*64,'peer':'example.org:80'}),('etp.fileshare.manifest',{'hash':'../private'}),
                            ('etp.fileshare.list',{'path':'/etc/passwd'})]:
            with self.assertRaises(ProtocolError):params(method,args)

    def test_chunk_contract_never_accepts_unverified_or_misbound_bytes(self):
        args={'hash':'a'*64,'index':0}
        value={'schema':'ziokt.etp-fileshare-chunk.v1','hash':'a'*64,'index':0,'data_base64':[base64.b64encode(b'unit-fixture').decode()],'native_chunk_verified':True}
        self.assertEqual(result('etp.fileshare.chunk',args,value),value)
        for change in ({'native_chunk_verified':False},{'hash':'b'*64},{'index':True},{'data_base64':['A'*4097]}):
            with self.assertRaises(ProtocolError):result('etp.fileshare.chunk',args,{**value,**change})

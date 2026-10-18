import secrets
import tempfile
from pathlib import Path
import unittest
from ziokt.community import create_policy,RIGHTS
from ziokt.peer_directory import PeerDirectory,DOMAIN
from ziokt.tracker import Tracker
from ziokt.security import sign
from ziokt.protocol import ProtocolError

class TrackerTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.keys=[secrets.token_bytes(32) for _ in range(3)]
        self.public=[sign({},key,DOMAIN)['public_key'] for key in self.keys]
        policy=create_policy(self.keys[0],'tracker',{public:sorted(RIGHTS) for public in self.public},privacy='private')
        self.directory=PeerDirectory(Path(temporary.name)/'directory',policy,self.public[0],allowed_networks=['127.0.0.0/8'])
        self.addCleanup(self.directory.close);self.tracker=Tracker(self.directory)
    def advert(self):return self.directory.advertise(self.keys[1],[{'host':'127.0.0.1','port':20001,'fingerprint':'1'*64,'service':'proxy'}],'1'*64)
    def register(self,advert,**kwargs):return self.tracker.call('tracker.register',{'envelope':advert,'publish':True,'anonymous':False,'relay_authorization':None,**kwargs},self.public[1])
    def query(self):return self.tracker.call('tracker.query',{'limit':8},self.public[2])['records']
    def test_dht_gossip_records_never_implicitly_published_and_revocation_persists(self):
        advert=self.advert();self.assertEqual(self.query(),[])
        self.register(advert);self.assertEqual(self.query(),[advert])
        self.tracker.call('tracker.revoke',{'sequence':advert['payload']['sequence']},self.public[1]);self.assertEqual(self.query(),[])
        with self.assertRaises(ProtocolError):self.register(advert)
        self.register(self.advert());self.assertEqual(len(self.query()),1)
    def test_opt_in_identity_and_anonymous_clear_ip_fail_closed(self):
        advert=self.advert()
        with self.assertRaises(ProtocolError):self.register(advert,publish=False)
        with self.assertRaises(ProtocolError):self.register(advert,anonymous=True)
        with self.assertRaises(ProtocolError):self.tracker.call('tracker.register',{'envelope':advert,'publish':True,'anonymous':False,'relay_authorization':None},self.public[2])
        self.assertEqual(self.query(),[])
    def test_actual_mtls_register_query_and_revoke(self):
        import hashlib,threading
        from test_community_network import certificates
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import Encoding
        from ziokt.remote import remote_server,tls_context
        from ziokt.tracker import TrackerClient
        root=Path(self.directory.root)/'tls';root.mkdir()
        ca,pairs=certificates(root,'127.0.0.1')
        server_cert,server_key=pairs['server'][:2];client_cert,client_key=pairs['client'][:2]
        fingerprint=hashlib.sha256(x509.load_pem_x509_certificate(client_cert.read_bytes()).public_bytes(Encoding.DER)).hexdigest()
        context=tls_context(server_cert,server_key,ca,True)
        methods=['tracker.register','tracker.query','tracker.revoke','tracker.status']
        federation={'enabled':True,'federation_id':'tracker','providers':[]}
        server=remote_server(federation,context,root/'replay.db',{fingerprint:{'public_key':self.public[1],'methods':methods,'providers':['tracker']}},community=self.tracker,allow_mutations=True)
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        client=TrackerClient(self.directory,self.keys[1],{'host':'127.0.0.1','port':server.server_port},tls_context(client_cert,client_key,ca))
        advert=self.advert()
        self.assertTrue(client.call('tracker.register',{'envelope':advert,'publish':True,'anonymous':False,'relay_authorization':None})['registered'])
        self.assertEqual(client.call('tracker.query',{'limit':8})['records'],[advert])
        self.assertTrue(client.call('tracker.revoke',{'sequence':advert['payload']['sequence']})['revoked'])
        self.assertEqual(client.call('tracker.query',{'limit':8})['records'],[])

    def test_unknown_identity_and_oversized_results_rejected(self):
        with self.assertRaises(ProtocolError):self.tracker.call('tracker.query',{'limit':8},'0'*64)
        with self.assertRaises(ProtocolError):self.tracker.call('tracker.query',{'limit':64},self.public[1])

if __name__=='__main__':unittest.main()

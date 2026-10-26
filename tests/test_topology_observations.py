import json
import datetime
import os
from pathlib import Path
import secrets
import tempfile
import time
import unittest
from unittest.mock import patch

from ziokt.p2p_explorer import P2PExplorer
from ziokt.protocol import ProtocolError, encoded
from ziokt.security import sign
from ziokt.topology_observations import DOMAIN, ObservationStore


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=ObservationStore(self.root/'observer.db')
        self.key=secrets.token_bytes(32);self.public=sign({},self.key,DOMAIN)['public_key']
        self.source={'id':'a','kind':'signed','component':'corium','network_id':'primary','public_key':self.public,'path':str(self.root/'a.json')}

    def envelope(self,sequence=1,network='primary',offset=0,challenge='a'*64):
        now=time.time_ns()//1000000+offset
        return sign({'schema':'ziokt.topology-observation.v1','component':'corium','network_id':network,'sequence':sequence,'challenge':challenge,
                     'sampled_at_ms':now,'sent_at_ms':now,'graph':{'nodes':[{'id':'shared'},{'id':'peer'}],'edges':[{'source':'shared','target':'peer','relation':'peer'}]}},self.key,DOMAIN)

    def test_clock_calibration_signature_binding_replay_and_restart(self):
        now=time.time_ns()//1000000
        value=self.envelope(offset=60000)
        result=self.store.accept(self.source,value,started_ms=now-10,received_ms=now+10,challenge='a'*64)
        self.assertTrue(result['evidence']['signature_verified'])
        self.assertAlmostEqual(result['evidence']['clock_offset_ms'],-60000,delta=100)
        self.assertEqual(result['evidence']['clock_uncertainty_ms'],10)
        restarted=ObservationStore(self.root/'observer.db')
        with self.assertRaises(ProtocolError):restarted.accept(self.source,self.envelope(),started_ms=now,received_ms=now+10,challenge='a'*64)
        with self.assertRaises(ProtocolError):restarted.accept(self.source,self.envelope(sequence=2,network='foreign'),started_ms=now,received_ms=now+10)
        value['payload']['sequence']=3
        with self.assertRaises(ProtocolError):restarted.accept(self.source,value,started_ms=now,received_ms=now+10)
        with self.assertRaises(ProtocolError):restarted.latest(self.source,now+301000)

    def test_signed_multiobserver_deduplication_and_network_separation(self):
        sources=[]
        for index,network in enumerate(('primary','primary','secondary')):
            key=secrets.token_bytes(32);public=sign({},key,DOMAIN)['public_key']
            value=self.envelope(network=network);value=sign(value['payload'],key,DOMAIN)
            path=self.root/f'{index}.json';path.write_bytes(encoded(value))
            sources.append(dict(self.source,id=str(index),network_id=network,public_key=public,path=str(path)))
        explorer=P2PExplorer({'public':True,'sources':sources,'observation_db':str(self.root/'aggregate.db')})
        result=explorer.query('/api/p2p/topology')
        self.assertEqual(len(result['nodes']),4)
        self.assertEqual(len(result['edges']),2)
        self.assertEqual(sorted(len(node['observed_by']) for node in result['nodes']),[1,1,2,2])
        self.assertEqual(result['coverage']['verified_observers'],3)
        self.assertEqual(result['coverage']['global_completeness'],'unknown')
        self.assertNotIn('shared',json.dumps(result))
        sources[0]['path']=str(self.root/'missing')
        cached=explorer.query('/api/p2p/topology')
        self.assertEqual(len(cached['nodes']),4)

    def test_export_requires_collect_scope_and_never_includes_addresses(self):
        key_path=self.root/'key';key_path.write_bytes(self.key);key_path.chmod(0o600)
        token=self.root/'token';token.write_text('collector');token.chmod(0o600)
        snapshot=self.root/'snapshot';snapshot.write_text(json.dumps({'schema':'ziokt.p2p-snapshot.v1','component':'corium','observed_at':int(time.time()),'nodes':[{'id':'node','address':'secret-host:42'}],'edges':[]}))
        explorer=P2PExplorer({'public':True,'sources':[{'id':'local','kind':'snapshot','component':'corium','path':str(snapshot),'network_id':'primary'}],
            'observation_db':str(self.root/'out.db'),'observation_export':{'source_id':'local','key_file':str(key_path)},
            'viewers':[{'token_file':str(token),'scopes':['topology:read','topology:collect']}]})
        url='/api/p2p/observation?challenge='+'b'*64
        with self.assertRaises(ProtocolError):explorer.query(url)
        first=explorer.query(url,'Bearer collector');second=explorer.query(url,'Bearer collector')
        self.assertEqual(second['payload']['sequence'],first['payload']['sequence']+1)
        self.assertNotIn('secret-host',json.dumps(first))

    def test_missing_shadow6_configuration_never_invents_live_transports(self):
        explorer=P2PExplorer({'public':True,'sources':[{'id':'s6','kind':'shadow6','component':'shadow6','state_root':str(self.root/'absent')}]})
        result=explorer.query('/api/p2p/topology')
        self.assertEqual(result['nodes'],[]);self.assertEqual(result['sources'][0]['state'],'unavailable')

    def test_actual_https_challenge_collection_with_pinned_observer(self):
        import ssl,threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from urllib.parse import parse_qs,urlsplit
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        tls_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')]);now=datetime.datetime.now(datetime.timezone.utc)
        cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(tls_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False).sign(tls_key,hashes.SHA256())
        certificate=self.root/'ca.pem';certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM));private=self.root/'tls.key';private.write_bytes(tls_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(certificate,private)
        exporter=ObservationStore(self.root/'exporter.db');source=self.source;key=self.key;requests=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(inner):
                requests.append(inner.headers.get('Authorization'))
                if requests[-1]!='Bearer collector-token':inner.send_error(403);return
                challenge=parse_qs(urlsplit(inner.path).query)['challenge'][0]
                document=exporter.export(source,{'nodes':[{'id':'actual-https-node'}],'edges':[]},key,challenge)
                inner.send_response(200);inner.send_header('Content-Type','application/json');inner.end_headers();inner.wfile.write(encoded(document))
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.socket=context.wrap_socket(server.socket,server_side=True)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();self.addCleanup(server.server_close);self.addCleanup(worker.join,3);self.addCleanup(server.shutdown)
        token=self.root/'collector-token';token.write_text('collector-token');token.chmod(0o600)
        remote={k:v for k,v in self.source.items() if k!='path'};remote.update(url=f'https://localhost:{server.server_port}/api/p2p/observation',token_file=str(token))
        with patch.dict(os.environ,{'SSL_CERT_FILE':str(certificate)}):result=self.store.collect(remote)
        self.assertEqual(result['nodes'][0]['id'],'actual-https-node');self.assertTrue(result['evidence']['signature_verified'])
        self.assertEqual(requests,['Bearer collector-token'])
        proof=self.store.evidence(remote);self.assertEqual(proof['public_key'],self.public)

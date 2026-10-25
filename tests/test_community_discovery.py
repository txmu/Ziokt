import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import threading
import time
import unittest

from cryptography.hazmat.primitives import serialization
from test_community_network import certificates
from ziokt.community import create_policy, RIGHTS, Community
from ziokt.community_network import CommunityEndpoint, sync_remote
from ziokt.peer_directory import PeerDirectory, DiscoveryWorker, DOMAIN, close_directories
from ziokt.peer_proxy import proxy_server
from ziokt.protocol import ProtocolError, make_private
from ziokt.remote import tls_context, remote_server
from ziokt.security import sign


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.keys = [secrets.token_bytes(32) for _ in range(3)]
        self.public = [sign({}, k, DOMAIN)['public_key'] for k in self.keys]
        self.policy = create_policy(self.keys[0], 'discovery', {p: sorted(RIGHTS) for p in self.public})
        self.owner = self.public[0]
        self.directory = PeerDirectory(self.root/'db', self.policy, self.owner, allowed_networks=['127.0.0.0/8'])
        self.addCleanup(self.directory.close)

    def advert(self, i=1):
        return self.directory.advertise(self.keys[i], [{'host':'127.0.0.1','port':20000+i,'fingerprint':str(i)*64,'service':'proxy'}], str(i)*64)

    def test_persistent_replay_fork_scope_expiry_private_and_health(self):
        old = self.advert(); new = self.advert()
        self.assertEqual(self.directory.ingest([new]), 0)
        with self.assertRaises(ProtocolError): self.directory.ingest([old])
        self.assertEqual(self.directory.ingest([old], ignore_stale=True), 0)
        rotated = dict(new['payload']); rotated['client_fingerprint'] = '9'*64; rotated['sequence'] += 1
        self.directory.ingest([sign(rotated,self.keys[1],DOMAIN)])
        self.assertFalse(self.directory.certificate_admitted('1'*64,[old]))
        self.assertTrue(self.directory.certificate_admitted('9'*64))
        payload = dict(new['payload']); payload['client_fingerprint'] = '4'*64
        with self.assertRaises(ProtocolError): self.directory.ingest([sign(payload, self.keys[1], DOMAIN)])
        self.directory.observe(self.public[1], success=False)
        self.assertEqual(self.directory.peers(), [])
        self.directory.observe(self.public[1], success=True, elapsed_ms=12)
        self.assertEqual(len(self.directory.closest('0'*64)), 1)
        self.directory.db.execute('DELETE FROM records'); self.directory.db.commit()
        with self.assertRaises(ProtocolError): self.directory.ingest([old])
        for change in [{'expires':int(time.time())-1}, {'epoch':True}, {'policy':'sha256:'+'0'*64},
                       {'endpoints':[{'host':'10.0.0.1','port':3,'fingerprint':'1'*64,'service':'proxy'}]}]:
            with self.subTest(change=change), self.assertRaises(ProtocolError):
                self.directory.ingest([sign({**new['payload'], **change}, self.keys[1], DOMAIN)])

    def test_excluded_nodes_cannot_route_or_admit_a_certificate(self):
        self.advert()
        blocked=PeerDirectory(self.root/'blocked',self.policy,self.owner,allowed_networks=['127.0.0.0/8'],excluded_nodes=[self.public[1]])
        self.addCleanup(blocked.close)
        blocked.ingest(self.directory.export())
        self.assertEqual(blocked.peers(),[])
        self.assertFalse(blocked.certificate_admitted('1'*64))
        # Removing the exclusion permits the same signed identity again.
        blocked.excluded_nodes=frozenset()
        self.assertEqual(len(blocked.peers()),1)
        self.assertTrue(blocked.certificate_admitted('1'*64))

    def start(self, server):
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def stop(): server.shutdown(); server.server_close(); thread.join(5)
        self.addCleanup(stop)

    def test_real_gossip_discovers_two_keyless_hops_and_carries_mtls_sync(self):
        materials = []
        for i in range(3):
            path = self.root/str(i); path.mkdir()
            ca, pairs = certificates(path, '127.0.0.1'); materials.append((ca,pairs))
        ca_all = self.root/'all.pem'; ca_all.write_bytes(b''.join(ca.read_bytes() for ca,_ in materials))
        policy_path = self.root/'policy.json'; policy_path.write_text(json.dumps(self.policy)); make_private(policy_path)
        dirs, templates, fps, servers, configs = [], [], [], [], []
        for i, (_,pairs) in enumerate(materials):
            template = {'certificate':str(pairs['client'][0]),'private_key':str(pairs['client'][1]),'ca':str(ca_all)}
            templates.append(template)
            fps.append({role:hashlib.sha256(pairs[role][2].public_bytes(serialization.Encoding.DER)).hexdigest() for role in ['client','server']})
            directory_path = self.root/f'directory{i}.json'
            config = {'schema':'ziokt.discovery.v1','enabled':True,'root':str(self.root/f'peers{i}'), 'policy':str(policy_path),
                'owner':self.owner,'allowed_networks':['127.0.0.0/8'],'native_bindings':{},'client_tls':template,'hop_count':2}
            directory_path.write_text(json.dumps(config)); make_private(directory_path)
            server = proxy_server({'schema':'ziokt.peer-proxy.v1','enabled':True,'host':'127.0.0.1','port':0,
                'trusted_clients':[],'targets':[],'max_connections':4,'max_bytes':1024*1024,'max_seconds':30,'discovery':str(directory_path)},
                tls_context(*pairs['server'][:2],ca_all,server=True))
            self.start(server); servers.append(server)
            from ziokt.peer_directory import load_directory
            directory,_ = load_directory(directory_path); dirs.append(directory); configs.append(config)
        self.addCleanup(close_directories)
        content_key = secrets.token_bytes(32)
        source = Community(self.root/'source',self.policy,self.owner,content_key); self.addCleanup(source.close)
        target = Community(self.root/'target',self.policy,self.owner,content_key); self.addCleanup(target.close)
        source.publish(self.keys[0],'wiki','discovered',{'title':'private','text':'signed gossip route'})
        api = remote_server({'enabled':True,'federation_id':'discovery','providers':[]},
            tls_context(*materials[0][1]['server'][:2],ca_all,server=True),self.root/'api-replay.sqlite',
            {fps[0]['client']:{'public_key':self.owner,'methods':['community.status','community.checkpoint.create','community.checkpoint.get','community.checkpoint.release'],'providers':['discovery']}},
            allow_mutations=True,community=CommunityEndpoint(source,self.keys[0]))
        self.start(api)
        workers = []
        for i in range(3):
            keypath = self.root/f'key{i}'; keypath.write_bytes(self.keys[i]); make_private(keypath)
            endpoints = [{'host':'127.0.0.1','port':servers[i].server_address[1],'fingerprint':fps[i]['server'],'service':'proxy'}]
            if i == 0: endpoints.append({'host':'127.0.0.1','port':api.server_port,'fingerprint':fps[0]['server'],'service':'community'})
            bootstrap = self.root/f'bootstrap{i}.json'
            bootstrap.write_text(json.dumps({'schema':'ziokt.remote.v1',**templates[i],'host':'127.0.0.1','port':servers[0].server_address[1]})); make_private(bootstrap)
            config = {**configs[i],'signing_key':str(keypath),'endpoints':endpoints,'bootstrap':([] if i==0 else
                [{'public_key':self.owner,'tls_config':str(bootstrap),'server_fingerprint':fps[0]['server']}])}
            worker = DiscoveryWorker(dirs[i],config); workers.append(worker); self.addCleanup(worker.close)
        workers[0].cycle()
        self.assertTrue(workers[1].cycle()[0]['healthy'])
        self.assertTrue(workers[2].cycle()[0]['healthy'])
        workers[1].cycle()
        # All three records converge through TLS gossip, with no static target allowlist.
        for d in dirs: self.assertEqual(len({p['public_key'] for p in d.peers()}),3)
        carrier = dirs[0].build_route(2,templates[0],('127.0.0.1',api.server_port))
        sync_remote(target,{'host':'127.0.0.1','port':api.server_port,'connection_policy':{'mode':'peer-multihop','allow_direct_fallback':False},'carrier':carrier},
            tls_context(*materials[0][1]['client'][:2],ca_all),self.keys[0],publisher=self.owner)
        self.assertEqual(target.view('wiki'),source.view('wiki'))
        self.assertTrue(all(not hasattr(s,'community') for s in servers))
        revised = create_policy(self.keys[0],'discovery',{self.owner:sorted(RIGHTS)},epoch=1)
        policy_path.write_text(json.dumps(revised)); make_private(policy_path)
        with self.assertRaises(ProtocolError) as error: dirs[0].certificate_admitted(fps[1]['client'])
        self.assertEqual(error.exception.code,'STALE_POLICY')

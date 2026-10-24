"""Actual I2P router, public tunnels, SAM and end-to-end community mTLS."""
import base64
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest

from cryptography.hazmat.primitives import serialization
from test_community_network import certificates
from ziokt.community import Community, RIGHTS, create_policy
from ziokt.community_network import CommunityEndpoint, sync_remote
from ziokt.i2p import close_sessions
from ziokt.protocol import ProtocolError
from ziokt.remote import remote_server, tls_context
from ziokt.security import sign


@unittest.skipUnless(os.environ.get('ZIOKT_I2P_LIVE') == '1', 'explicit actual I2P network gate')
class LiveI2PTests(unittest.TestCase):
    def test_actual_sam_tunnels_and_mtls_community_sync(self):
        def port():
            with socket.socket() as available:
                available.bind(('127.0.0.1',0)); return available.getsockname()[1]
        with tempfile.TemporaryDirectory(prefix='ziokt-i2p-live-') as directory:
            root = Path(directory); data = root/'router'; data.mkdir(mode=0o700)
            shutil.copytree('/usr/share/i2pd/certificates',data/'certificates')
            sam_port, service_port = port(),port()
            config = root/'i2pd.conf'; tunnels = root/'tunnels.conf'
            config.write_text('daemon=false\nlog=stdout\nloglevel=warn\n[reseed]\nverify=true\n[http]\nenabled=false\n[httpproxy]\nenabled=false\n[socksproxy]\nenabled=false\n[sam]\nenabled=true\naddress=127.0.0.1\nport='+str(sam_port)+'\n')
            tunnels.write_text('[ziokt-ci]\ntype=server\nhost=127.0.0.1\nport='+str(service_port)+'\ninport=0\nkeys=ziokt-ci.dat\ninbound.length=2\noutbound.length=2\n')
            log = root/'router.log'
            source = target = server = thread = None
            with log.open('wb') as output:
                router = subprocess.Popen(['i2pd','--datadir='+str(data),'--conf='+str(config),'--tunconf='+str(tunnels)],stdout=output,stderr=output)
                try:
                    keys = data/'ziokt-ci.dat'; deadline = time.monotonic()+180
                    while not keys.exists() and router.poll() is None and time.monotonic() < deadline: time.sleep(1)
                    self.assertIsNone(router.poll(),'temporary I2P router exited')
                    self.assertTrue(keys.exists(),'I2P destination not generated')
                    raw = keys.read_bytes(); self.assertGreaterEqual(len(raw),387)
                    size = 387+int.from_bytes(raw[385:387],'big'); self.assertLessEqual(size,len(raw))
                    host = base64.b32encode(hashlib.sha256(raw[:size]).digest()).decode().lower().rstrip('=')+'.b32.i2p'
                    private,key = secrets.token_bytes(32),secrets.token_bytes(32)
                    public = sign({},private,'test')['public_key']
                    policy = create_policy(private,'i2p-live',{public:sorted(RIGHTS)})
                    source = Community(root/'source',policy,public,key); target = Community(root/'target',policy,public,key)
                    ca,pairs = certificates(root,host)
                    fingerprint = hashlib.sha256(pairs['client'][2].public_bytes(serialization.Encoding.DER)).hexdigest()
                    trusted = {fingerprint:{'public_key':public,'providers':['i2p-live'],
                        'methods':['community.status','community.checkpoint.create','community.checkpoint.get','community.checkpoint.release']}}
                    server = remote_server({'enabled':True,'federation_id':'i2p-live','providers':[]},
                        tls_context(*pairs['server'][:2],ca,server=True),root/'replay.sqlite',trusted,port=service_port,
                        allow_mutations=True,community=CommunityEndpoint(source,private))
                    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
                    source.publish(private,'wiki','actual-i2p',{'title':'I2P','text':'real SAM and public tunnels'})
                    endpoint = {'host':host,'port':443,'carrier':{'kind':'i2p-sam','proxy_host':'127.0.0.1',
                        'proxy_port':sam_port,'tunnel_length':2,'isolation_scope':'ci-owned-community'},
                        'connection_policy':{'mode':'anonymous','allow_direct_fallback':False}}
                    context = tls_context(*pairs['client'][:2],ca)
                    deadline = time.monotonic()+900; success = False
                    while time.monotonic() < deadline:
                        self.assertIsNone(router.poll(),'I2P router exited during actual transfer')
                        try:
                            sync_remote(target,endpoint,context,private,publisher=public); success = True; break
                        except OSError: time.sleep(5)
                        except ProtocolError as error:
                            if error.code != 'CARRIER_UNAVAILABLE': raise
                            time.sleep(5)
                    self.assertTrue(success,'actual I2P SAM stream did not complete mTLS sync')
                    self.assertEqual(source.view('wiki'),target.view('wiki'))
                    deadline=time.monotonic()+300
                    while True:
                        try:
                            sync_remote(target,endpoint,context,private,publisher=public);break
                        except ProtocolError as error:
                            if error.code!='CARRIER_UNAVAILABLE' or time.monotonic()>=deadline:raise
                            time.sleep(5)
                finally:
                    close_sessions()
                    if server is not None: server.shutdown(); server.server_close()
                    if thread is not None: thread.join(5)
                    if source is not None: source.close()
                    if target is not None: target.close()
                    router.terminate()
                    try: router.wait(10)
                    except subprocess.TimeoutExpired: router.kill(); router.wait()

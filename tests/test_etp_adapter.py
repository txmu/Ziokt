import base64
import hashlib
from pathlib import Path
import secrets
import tempfile
import tomllib
import unittest
from ziokt.etp import EtpGateway
from ziokt.protocol import ProtocolError
from ziokt.cli import write_binary_exclusive

class EtpAdapterTests(unittest.TestCase):
    def test_pinned_worker_contract_and_fail_closed_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);binary=root/'worker';config=root/'config.json';write_binary_exclusive(config,b'{}')
            binary.write_text('#!/usr/bin/python3\nimport sys,json\nfor line in sys.stdin:\n r=json.loads(line);print(json.dumps({"id":r["id"],"ok":True,"result":{"fixture":True,"accepted":True,"delivery_confirmed":False}}),flush=True)\n');binary.chmod(0o700)
            digest='sha256:'+hashlib.sha256(binary.read_bytes()).hexdigest();worker=EtpGateway(binary,digest,config);self.addCleanup(worker.close)
            self.assertTrue(worker.call('etp.stats',{})['fixture'])
            packet={'hops':['127.0.0.1:1','127.0.0.1:2'],'ciphertext':base64.b64encode(secrets.token_bytes(16384)).decode()}
            self.assertFalse(worker.call('etp.onion.send',packet)['delivery_confirmed'])
            for method,params in [('etp.send',packet),('etp.onion.send',{**packet,'hops':['127.0.0.1:1']}),('etp.onion.send',{**packet,'ciphertext':'plaintext'}),('etp.stats',{'command':'anything'})]:
                with self.assertRaises(ProtocolError):worker.call(method,params)
            config.write_text('{"changed":true}')
            with self.assertRaises(ProtocolError):worker.call('etp.stats',{})
    def test_execution_uses_private_reviewed_snapshot_even_if_original_is_replaced(self):
        from unittest.mock import patch
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);binary=root/'worker';config=root/'config.json';write_binary_exclusive(config,b'{}')
            binary.write_text('#!/usr/bin/env python3\nimport json,sys\nfor line in sys.stdin:\n r=json.loads(line);print(json.dumps({"id":r["id"],"ok":True,"result":{"reviewed":True}}),flush=True)\n');binary.chmod(0o700)
            gateway=EtpGateway(binary,'sha256:'+hashlib.sha256(binary.read_bytes()).hexdigest(),config);self.addCleanup(gateway.close)
            original=subprocess.Popen
            def replace_then_launch(command,**kwargs):
                self.assertNotEqual(command[0],str(binary))
                self.assertEqual(Path(command[0]).stat().st_mode&0o777,0o700)
                binary.write_text('#!/usr/bin/env python3\nraise RuntimeError("unreviewed replacement must never execute")\n')
                return original(command,**kwargs)
            with patch('ziokt.etp.subprocess.Popen',side_effect=replace_then_launch):
                self.assertTrue(gateway.call('etp.stats',{})['reviewed'])
            snapshot=gateway._snapshot.name;gateway.close();self.assertFalse(Path(snapshot).exists())
            with self.assertRaises(ProtocolError):gateway.call('etp.stats',{})

    def test_source_manifest_renamed_vm_and_feature_dependencies(self):
        root=Path(__file__).resolve().parents[1]/'companions/etp/src'
        value=tomllib.loads((root/'Cargo.toml').read_text());self.assertIn('tc16-tcc',value['features'])
        self.assertIn('pyo3-async-runtimes',value['dependencies']['pyo3-asyncio']['package'])
        source=(root/'src/extensions/tc16_tcc.rs').read_text();self.assertIn('pub regs: [u16; REG_COUNT]',source);self.assertNotIn('gas_limit',source)

class EtpRecordTests(unittest.TestCase):
    def test_real_aead_scope_direction_padding_and_corium_frame_boundary(self):
        import queue
        from ziokt.etp import EtpRecordSocket
        key=secrets.token_bytes(32)
        class Gateway:
            def __init__(self):self.inbox=queue.Queue();self.other=None;self.sent=[]
            def call(self,method,params):
                if method=='etp.onion.send':
                    packet=base64.b64decode(params['ciphertext']);self.sent.append(packet);self.other.inbox.put(packet);return {'accepted':True,'delivery_confirmed':False}
                packet=self.inbox.get(timeout=.2);return {'ciphertext':[base64.b64encode(packet[i:i+3072]).decode() for i in range(0,len(packet),3072)]}
            def close(self):pass
        a,b=Gateway(),Gateway();a.other=b;b.other=a
        route=['127.0.0.1:1','127.0.0.1:2'];client=EtpRecordSocket(a,route,key,'test');server=EtpRecordSocket(b,route,key,'test',server=True)
        self.assertEqual(client.send(b'private Corium signed frame'),27);self.assertEqual(len(a.sent[0]),16384);self.assertNotIn(b'private Corium',a.sent[0]);self.assertEqual(server.recv(4096),b'private Corium signed frame')
        server.send(b'response');self.assertEqual(client.recv(4096),b'response')
        client.send(b'wrong scope');wrong=EtpRecordSocket(b,route,key,'other',server=True)
        with self.assertRaises(ProtocolError):wrong.recv(4096)
        client.send(b'tamper');packet=b.inbox.get();b.inbox.put(packet[:-1]+bytes([packet[-1]^1]))
        with self.assertRaises(ProtocolError):server.recv(4096)

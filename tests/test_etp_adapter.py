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
    def test_native_health_requires_a_real_stats_round_trip_and_binds_fresh_challenge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);binary=root/'worker';config=root/'config.json';write_binary_exclusive(config,b'{}')
            binary.write_text('#!/usr/bin/env python3\nimport sys,json\nfor line in sys.stdin:\n r=json.loads(line)\n if r["method"]=="etp.shutdown":break\n print(json.dumps({"id":r["id"],"ok":True,"result":{"schema":"ziokt.etp-stats.v1","native":{"peers":0}}}),flush=True)\n');binary.chmod(0o700)
            gateway=EtpGateway(binary,'sha256:'+hashlib.sha256(binary.read_bytes()).hexdigest(),config);self.addCleanup(gateway.close)
            result=gateway.call('etp.health',{'challenge':'a'*32})
            self.assertEqual(result['component'],'etp');self.assertEqual(result['challenge'],'a'*32)
            self.assertEqual(result['checks']['native_engine_stats'],'passed')
            with self.assertRaises(ProtocolError):gateway.call('etp.health',{'challenge':'invalid'})

    def test_rejected_mailbox_operations_never_fabricate_health_or_ack(self):
        for code in ('METHOD_UNSUPPORTED','AUTHORIZATION_DENIED'):
            with self.subTest(code=code),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);binary=root/'rejecting-worker';config=root/'config.json';write_binary_exclusive(config,b'{}')
                binary.write_text('#!/usr/bin/env python3\nimport sys,json\nfor line in sys.stdin:\n r=json.loads(line)\n if r["method"]=="etp.shutdown":break\n print(json.dumps({"id":r["id"],"ok":False,"error":{"code":'+repr(code)+'}}),flush=True)\n');binary.chmod(0o700)
                worker=EtpGateway(binary,'sha256:'+hashlib.sha256(binary.read_bytes()).hexdigest(),config)
                try:
                    for method,params in [('etp.mailbox.status',{}),('etp.mailbox.request',{'frame_base64':base64.b64encode(bytes([2,6])).decode()})]:
                        with self.assertRaises(ProtocolError) as error:worker.call(method,params)
                        self.assertEqual(error.exception.code,'METHOD_UNSUPPORTED' if code=='METHOD_UNSUPPORTED' else 'ETP_REJECTED')
                        self.assertIsNotNone(worker.process)
                finally:worker.close()

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

class EtpForumAdapterTests(unittest.TestCase):
    """Actual pinned helper processes test IPC validation, not native ETP execution."""
    def worker(self,root,body):
        binary=root/'forum-ipc-fixture';config=root/'config.json';write_binary_exclusive(config,b'{}')
        binary.write_text('#!/usr/bin/env python3\nimport sys,json,base64,os\n'+body);binary.chmod(0o700)
        gateway=EtpGateway(binary,'sha256:'+hashlib.sha256(binary.read_bytes()).hexdigest(),config);self.addCleanup(gateway.close)
        return gateway
    def test_typed_forum_ipc_and_explicit_anonymous_author(self):
        with tempfile.TemporaryDirectory() as tmp:
            gateway=self.worker(Path(tmp),'''for line in sys.stdin:
 r=json.loads(line);m=r['method'];p=r['params']
 if m=='etp.shutdown':break
 if m=='etp.forum.identity':v={'schema':'ziokt.etp-forum-identity.v1','name':p['name'],'author_id':'ab'*32}
 elif m=='etp.forum.subscribe':v={'subscribed':True,'topic_hash':'cd'*32}
 elif m=='etp.forum.publish':v={'schema':'ziokt.etp-forum-publish.v1','id':'ef'*32,'stored':True,'dht_enqueued':False,'delivery_confirmed':False,'state':'stored_locally','gossip':'best_effort'}
 else:v={'post':{'id':p['id'],'topic_hash':'cd'*32,'author_id':None,'timestamp':1,'content_base64':[base64.b64encode(b'x'*3072).decode() for _ in range(10)]+[base64.b64encode(b'x'*2048).decode()],'parent_id':None,'signature_base64':'','parent_status':'not_reply'}}
 print(json.dumps({'id':r['id'],'ok':True,'result':v}),flush=True)
''')
            self.assertEqual(gateway.call('etp.forum.identity',{'name':'alice'})['author_id'],'ab'*32)
            self.assertTrue(gateway.call('etp.forum.subscribe',{'topic':'native'})['subscribed'])
            response=gateway.call('etp.forum.publish',{'topic':'native','content':'text','author':None})
            self.assertEqual(response['state'],'stored_locally');self.assertFalse(response['delivery_confirmed'])
            post=gateway.call('etp.forum.get',{'id':'ef'*32})['post'];self.assertEqual(sum(len(base64.b64decode(c)) for c in post['content_base64']),32768)
            invalid=[('etp.forum.publish',{'topic':'native','content':'text'}),('etp.forum.publish',{'topic':'native','content':'text','author':True}),('etp.forum.publish',{'topic':'native','content':'x'*32769,'author':None}),('etp.forum.publish',{'topic':'native','content':'text','author':None,'private_key':'00'*32}),('etp.forum.get',{'id':'not-a-hash'}),('etp.forum.subscribe',{'topic':'line\nbreak'}),('etp.forum.identity',{'name':'../seed'}),('etp.forum.delete',{})]
            sequence=gateway.sequence
            for method,params in invalid:
                with self.subTest(method=method,params=list(params)),self.assertRaises(ProtocolError):gateway.call(method,params)
            self.assertEqual(gateway.sequence,sequence)
    def test_native_unsupported_and_untyped_success_do_not_imply_forum_support(self):
        for reply,code in [("{'id':r['id'],'ok':False,'error':{'code':'METHOD_UNSUPPORTED'}}",'METHOD_UNSUPPORTED'),("{'id':r['id'],'ok':True,'result':{'fixture':True}}",'INVALID_RESPONSE')]:
            with tempfile.TemporaryDirectory() as tmp:
                gateway=self.worker(Path(tmp),"for line in sys.stdin:\n r=json.loads(line)\n if r['method']=='etp.shutdown':break\n print(json.dumps("+reply+"),flush=True)\n")
                with self.assertRaises(ProtocolError) as error:gateway.call('etp.forum.identity',{'name':'alice'})
                self.assertEqual(error.exception.code,code)
                if code=='METHOD_UNSUPPORTED':self.assertIsNotNone(gateway.process)
                else:self.assertIsNone(gateway.process)

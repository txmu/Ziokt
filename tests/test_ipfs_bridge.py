import base64
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest

from ziokt.content_api import invoke
from ziokt.content_etp_application import EtpApplications
from ziokt.content_fabric import Fabric
from ziokt.ipfs import BLOCK_BYTES,IpfsBridge,block_cid,cid_text,export_car,fetch_car,import_car,parse_cid,varint
from ziokt.protocol import ProtocolError


class IpfsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.fabric=Fabric(self.root/'first');self.addCleanup(self.fabric.close)

    def test_standard_empty_raw_cid_and_large_unixfs_repeated_leaves(self):
        cid,archive=export_car(b'')
        self.assertEqual(cid,'bafkreihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku')
        self.assertEqual(import_car(cid,archive),b'')
        payload=b'a'*BLOCK_BYTES*2+b'last leaf'
        cid,archive=export_car(payload)
        self.assertEqual(import_car(cid,archive),payload)
        self.assertEqual(parse_cid('ipfs://'+cid),parse_cid(cid))
        broken=bytearray(archive);broken[-1]^=1
        with self.assertRaises(ProtocolError):import_car(cid,bytes(broken))
        with self.assertRaises(ProtocolError):import_car(cid,archive[:-20])
        with self.assertRaises(ProtocolError):import_car(export_car(b'wrong root')[0],archive)

    def test_cidv0_and_inline_unixfs_file_from_independent_protobuf_fixture(self):
        # PBNode(Data=UnixFS(Type=File, Data="hello", filesize=5)).
        node=bytes.fromhex('0a0b0802120568656c6c6f1805')
        cid=block_cid(node,0x70)[2:];text=cid_text(cid)
        header=b'\xa2\x65roots\x81\xd8\x2a\x58\x23\0'+cid+b'\x67version\x01'
        archive=varint(len(header))+header+varint(len(cid)+len(node))+cid+node
        self.assertTrue(text.startswith('Qm'));self.assertEqual(import_car(text,archive),b'hello')

    def test_fabric_permissions_export_import_and_cid_integrity(self):
        bridge=IpfsBridge(self.fabric);cid,archive=export_car(b'Fabric and IPFS exchange')
        imported=bridge.ingest('alice',cid,archive)
        self.assertTrue(bridge.ingest('alice',cid,archive)['duplicate'])
        result=invoke(self.fabric,'alice','content.ipfs.export',{'id':imported['id']})
        self.assertEqual(result['cid'],cid);self.assertFalse(result['publicly_pinned'])
        self.assertEqual(invoke(self.fabric,'alice','content.ipfs.import',{'cid':cid,'archive':result['archive']})['id'],imported['id'])
        with self.assertRaises(PermissionError):invoke(self.fabric,'bob','content.ipfs.export',{'id':imported['id']})
        with self.assertRaises(ProtocolError):fetch_car({},'unconfigured',cid)

    def test_actual_gateway_car_to_etp_authorized_source_and_fabric(self):
        posts={};author='a'*64
        def transport(method,args):
            if method=='etp.forum.identity':return {'author_id':author}
            if method=='etp.forum.subscribe':return {'topic_hash':hashlib.sha256(args['topic'].encode()).hexdigest()}
            if method=='etp.forum.publish':
                identifier='b'*64;posts[identifier]={'author_id':author,'topic_hash':hashlib.sha256(args['topic'].encode()).hexdigest(),'content_base64':[base64.b64encode(args['content'].encode()).decode()]};return {'id':identifier}
            if method=='etp.forum.get':return {'post':posts.get(args['id'])}
            raise AssertionError(method)
        policies={owner:{'aliases':['writer'],'topics':['mesh'],'groups':['mesh.group'],'remote_authors':[author]} for owner in ('alice','bob')}
        adapter=EtpApplications({'gateway':{'binary':'unused-by-interface-fixture','digest':'sha256:'+'0'*64,'config':'unused'},'accounts':policies},transport=transport)
        self.fabric.native_etp=adapter
        cid,archive=export_car(b'ETP signed source points at real CID bytes')
        original=IpfsBridge(self.fabric).ingest('alice',cid,archive)
        args={'id':original['id'],'alias':'writer','topic':'mesh','public':True}
        with self.assertRaises(PermissionError):invoke(self.fabric,'alice','content.ipfs.etp.publish',dict(args,public=False))
        published=invoke(self.fabric,'alice','content.ipfs.etp.publish',args)
        self.assertEqual(published['cid'],cid);self.assertTrue(published['native_stored'])
        class Handler(BaseHTTPRequestHandler):
            def do_GET(inner):
                if not inner.path.startswith('/ipfs/'+cid+'?'):inner.send_error(404);return
                inner.send_response(200);inner.send_header('Content-Type','application/vnd.ipld.car');inner.end_headers();inner.wfile.write(archive)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        self.addCleanup(server.server_close);self.addCleanup(worker.join,2);self.addCleanup(server.shutdown)
        second=Fabric(self.root/'second');self.addCleanup(second.close);second.native_etp=adapter
        second.ipfs_gateways={'local-test':{'url':f'http://127.0.0.1:{server.server_port}'}}
        ingested=invoke(second,'bob','content.ipfs.etp.ingest',{'native_id':published['native_id'],'source':'local-test'})
        self.assertEqual(second.read_chunk('bob',ingested['id'],0),b'ETP signed source points at real CID bytes')
        self.assertTrue(ingested['cid_verified']);self.assertEqual(ingested['native_author'],author)
        with self.assertRaises(PermissionError):invoke(second,'unassigned','content.ipfs.etp.ingest',{'native_id':published['native_id'],'source':'local-test'})

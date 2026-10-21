"""Durable Fabric intake with a controlled gateway. Native positive evidence is CI.

The controlled gateway is not native FileShare/Forum/signature evidence; these
cases exercise SQLite, native Fabric byte verification and failure boundaries.
"""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from ziokt.content_etp_library import EtpLibrary,SCHEMA
from ziokt.content_fabric import Fabric
from ziokt.protocol import ProtocolError,encoded

class ControlledGateway:
    def __init__(self):
        self.bytes=b'bounded native-source fixture\n'*1200;self.on_chunk=None
        self.value={'schema':SCHEMA,'topic':'books','hash':'b'*64,'digest':'sha256:'+hashlib.sha256(self.bytes).hexdigest(),
                    'size':len(self.bytes),'mime':'text/plain','public':True,
                    'book':{'work_id':'work','edition_id':'first','title':'Source book','authors':['Alice'],'license':'CC0-1.0'}}
    def call(self,method,args):
        if method=='etp.forum.get':return {'post':{'id':'c'*64,'author_id':'a'*64,'topic_hash':'d'*64,'content_base64':[base64.b64encode(encoded(self.value)).decode()]}}
        if method=='etp.forum.subscribe':return {'subscribed':True,'topic_hash':'d'*64}
        if method=='etp.fileshare.status':return {'state':'locally_indexed'}
        if method=='etp.fileshare.manifest':return {'size':len(self.bytes),'chunk_bytes':16384}
        if method=='etp.fileshare.chunk':
            if self.on_chunk:self.on_chunk()
            return {'data_base64':[base64.b64encode(self.bytes[args['index']*16384:(args['index']+1)*16384]).decode()]}
        raise AssertionError('unexpected controlled operation '+method)

class LibraryIntakeTests(unittest.TestCase):
    def setUp(self):
        area=tempfile.TemporaryDirectory();self.addCleanup(area.cleanup);self.root=Path(area.name)
        self.fabric=Fabric(self.root);self.gateway=ControlledGateway()
        self.policy={'authors':['a'*64],'topics':['books'],'peers':['127.0.0.1:9988']}
        self.intake=EtpLibrary(self.fabric,self.gateway,lambda owner:self.policy if owner=='alice' else None)
        self.addCleanup(lambda:self.fabric.close())
    def begin(self,nonce='initial'):
        return self.intake.begin('alice','c'*64,'127.0.0.1:9988','native-book','private',nonce)['job']

    def test_persistent_partial_bytes_resume_and_complete_real_native_fabric_book(self):
        job=self.begin();self.assertEqual(self.begin(),job)
        self.assertEqual(self.intake.step('alice',job,1)['state'],'receiving')
        self.fabric.close();self.fabric=Fabric(self.root)
        self.intake=EtpLibrary(self.fabric,self.gateway,lambda owner:self.policy)
        result=self.intake.step('alice',job,8);self.assertEqual(result['state'],'complete')
        obj=result['object'];self.assertEqual(self.fabric.verify_object('alice',obj)['size'],len(self.gateway.bytes))
        data=b''.join(self.fabric.read_chunk('alice',obj,i) for i in range((len(self.gateway.bytes)+16383)//16384))
        self.assertEqual(data,self.gateway.bytes)
        self.assertEqual(self.fabric._get('alice','native-book','book')['title'],'Source book')
        with self.assertRaises(PermissionError):self.intake.status('bob',job)

    def test_delegation_revoked_during_native_read_never_publishes_or_writes_chunk(self):
        job=self.begin();self.gateway.on_chunk=lambda:self.policy['authors'].clear()
        with self.assertRaises(PermissionError):self.intake.step('alice',job)
        self.assertEqual(self.intake.status('alice',job)['state'],'failed')
        self.assertEqual(self.fabric.upload_status('alice','etp-lib-'+job[:48])['received_chunks'],0)
        self.assertEqual(self.fabric.db.execute('SELECT count(*) FROM records').fetchone()[0],0)

    def test_cancel_during_native_read_and_explicit_fresh_nonce(self):
        job=self.begin();self.gateway.on_chunk=lambda:self.intake.cancel('alice',job)
        self.assertEqual(self.intake.step('alice',job)['state'],'cancelled')
        self.assertEqual(self.fabric.db.execute('SELECT count(*) FROM records').fetchone()[0],0)
        self.gateway.on_chunk=None
        replacement=self.begin('retry');self.assertNotEqual(replacement,job)
        self.assertEqual(self.intake.step('alice',replacement)['state'],'complete')

    def test_wrong_sha256_no_success_and_existing_record_never_overwritten(self):
        self.gateway.value['digest']='sha256:'+'0'*64
        job=self.begin()
        with self.assertRaises((ProtocolError,ValueError)):self.intake.step('alice',job)
        self.assertEqual(self.intake.status('alice',job)['state'],'failed')
        self.assertEqual(self.fabric.db.execute('SELECT count(*) FROM records').fetchone()[0],0)

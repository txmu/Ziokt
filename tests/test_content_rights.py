"""Actual persistent local governance and independent copies, without global DRM."""
import json
import threading
import urllib.request,urllib.error
from test_content_fabric import FabricTests
from ziokt.content_fabric import Fabric
from ziokt.content_rights import Governance,metadata
from ziokt.content_server import server

class RightsTests(FabricTests):
    def test_claim_metadata_and_local_policies_keep_independent_copy(self):
        obj=self.upload();value={'id':'rights-book','work_id':'work','edition_id':'edition','file_id':obj['id'],'title':'Public work','authors':['Alice'],'license':'CC0-1.0','visibility':'public','rights':{'schema':'ziokt.content-rights.v1','attribution':[{'name':'Alice','role':'author'}],'source':'author release','license':{'type':'spdx','value':'CC0-1.0','url':'https://creativecommons.org/publicdomain/zero/1.0/'},'public_domain':True,'authorization_proofs':['sha256:'+'a'*64]}}
        self.fabric.create_book('alice',value)
        remote=Fabric(self.root/'independent',peers={self.fabric.public:{}})
        try:
            self.assertEqual(remote.ingest(self.fabric.export()['events'])['accepted'],1)
            governance=Governance(self.fabric)
            with self.assertRaises(PermissionError):governance.policy('operator','rights-book','deindex','complaint')
            policy=governance.policy('operator','rights-book','deindex','local index policy',allow=True)
            self.assertFalse(policy['physical_bytes_deleted']);self.assertEqual(self.fabric.search('bob')['items'],[])
            self.assertEqual(self.fabric.read_chunk('bob',obj['id'],0),b'Hello library')
            governance.policy('operator','rights-book','stop_distribution','pending review',allow=True)
            with self.assertRaises(PermissionError):self.fabric.read_chunk('bob',obj['id'],0)
            with self.assertRaises(PermissionError):self.fabric.export()
            self.assertEqual(self.fabric.read_chunk('alice',obj['id'],0),b'Hello library')
            self.assertEqual(remote._get('bob','rights-book')['rights'],value['rights'])
            governance.policy('operator','rights-book','resume_distribution','review complete',allow=True)
            self.assertEqual(len(self.fabric.export()['events']),1)
            governance.policy('operator','rights-book','reindex','review complete',allow=True)
            self.assertEqual(len(self.fabric.search('bob')['items']),1)
            # Withdrawal is distinct; physical reclamation requires an additional owner operation.
            self.fabric.withdraw('alice','rights-book')
            self.assertTrue(self.fabric.release_object('alice',obj['id'])['released'])
            self.assertEqual(remote._get('bob','rights-book')['title'],'Public work')
        finally:remote.close()

    def test_complaint_appeal_persistence_and_no_automatic_takedown(self):
        obj=self.upload();self.book(obj,'public')
        governance=Governance(self.fabric)
        report=governance.report('bob','book',{'claim':'copyright dispute','evidence':'source commitment','contact':'optional local contact'})
        self.assertFalse(report['legal_claim_verified']);self.assertFalse(report['distribution_stopped'])
        with self.assertRaises(PermissionError):governance.case('carol',report['id'])
        self.assertEqual(governance.case('alice',report['id'])['state'],'submitted')
        with self.assertRaises(PermissionError):governance.decide('operator',report['id'],'uphold','local decision')
        governance.decide('operator',report['id'],'uphold','local decision',allow=True)
        governance.appeal('alice',report['id'],'author supplied authorization')
        self.fabric.close();self.fabric=Fabric(self.root/'node');governance=Governance(self.fabric)
        case=governance.case('bob',report['id']);self.assertEqual(case['state'],'appealed');self.assertEqual(len(case['events']),3)
        self.assertEqual(self.fabric.read_chunk('bob',obj['id'],0),b'Hello library')
        self.assertEqual(len(self.fabric.export()['events']),1)
        self.assertNotIn('copyright dispute',json.dumps(self.fabric.export()))

    def test_http_admin_scope_cannot_be_replaced_by_content_write(self):
        obj=self.upload();self.book(obj,'public')
        http=server(self.fabric,{'port':0,'tokens':[{'account':'alice','token':'writer-token','scopes':['content:write']},{'account':'operator','token':'admin-token','scopes':['content:admin']}]})
        worker=threading.Thread(target=http.serve_forever);worker.start()
        try:
            raw=json.dumps({'operation':'content.policy','arguments':{'record':'book','action':'stop_distribution','reason':'local policy'}}).encode()
            # Endpoint uses the same authenticated application RPC contract as existing clients.
            for token,expected in [('writer-token',403),('admin-token',200)]:
                request=urllib.request.Request('http://127.0.0.1:'+str(http.server_port)+'/api',raw,{'Content-Type':'application/json','Authorization':'Bearer '+token})
                try:
                    with urllib.request.urlopen(request) as response:self.assertEqual(response.status,expected)
                except urllib.error.HTTPError as error:
                    self.assertEqual(error.code,expected);error.close()
        finally:http.shutdown();http.server_close();worker.join()

import base64
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from ziokt.content_fabric import Fabric
from ziokt.content_private import PrivateFabric
from ziokt.content_maintenance import ContentMaintenance
from ziokt.content_server import server,remote


class PrivateContentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.left=Fabric(Path(self.temp.name)/'left');self.right=Fabric(Path(self.temp.name)/'right')
        self.left.peers={self.right.public:{}};self.right.peers={self.left.public:{}}
        self.nodes=[]
        for fabric,owner in ((self.left,'alice'),(self.right,'bob')):
            config={'port':0,'tokens':[{'account':owner,'token':owner*10,'scopes':['content:read','content:write','library:read','library:write']},
                                     {'account':'peer','token':'p'*40,'scopes':['content:read','content:replicate']} ]}
            http=server(fabric,config);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            self.nodes.append((http,thread));self.addCleanup(fabric.close)
        self.left.remote_peers={'other':{'url':'http://127.0.0.1:'+str(self.nodes[1][0].server_port),'public_key':self.right.public,'token':'p'*40}}
        self.right.remote_peers={'other':{'url':'http://127.0.0.1:'+str(self.nodes[0][0].server_port),'public_key':self.left.public,'token':'p'*40}}
        self.addCleanup(self.stop)
        self.lp=PrivateFabric(self.left);self.rp=PrivateFabric(self.right)
        li=self.lp.identity('alice');ri=self.rp.identity('bob')
        self.lp.contact('alice','bob',ri,'other',True);self.rp.contact('bob','alice',li,'other',True)

    def stop(self):
        for http,thread in self.nodes:http.shutdown();http.server_close();thread.join(2)

    def upload(self,fabric,owner,data):
        id='upload-'+owner
        fabric.begin(owner,id,len(data),'sha256:'+hashlib.sha256(data).hexdigest(),'text/plain')
        fabric.put(owner,id,0,data);return fabric.finish(owner,id)

    def test_cross_account_ciphertext_delivery_rotation_revocation_and_physical_gc(self):
        plaintext=b'PRIVATE ACCOUNT CONTENT';obj=self.upload(self.left,'alice',plaintext)
        share=self.lp.create('alice',obj['id'],'bob',int(time.time())+3600);self.lp.step('alice',share['id'])
        worker=ContentMaintenance(self.left,{});worker.run_once()
        self.assertEqual(base64.b64decode(self.rp.read('bob',share['id'],0)['data']),plaintext)
        self.assertEqual(self.left.export()['events'],[])
        for path in self.lp.files.iterdir():self.assertNotIn(plaintext,path.read_bytes())
        old=json.loads(self.left.db.execute('SELECT envelope FROM cf_private_shares WHERE id=?',(share['id'],)).fetchone()[0])
        self.rp.identity('bob',True)
        with self.assertRaises(PermissionError):self.rp.read('bob',share['id'],0)
        self.lp.contact('alice','bob',self.rp.identity('bob'),'other',True)
        self.lp.rotate_share('alice',share['id']);self.lp.step('alice',share['id']);worker.run_once()
        self.assertEqual(base64.b64decode(self.rp.read('bob',share['id'],0)['data']),plaintext)
        self.lp.revoke('alice',share['id']);worker.run_once()
        with self.assertRaises(PermissionError):self.rp.read('bob',share['id'],0)
        with self.assertRaises((PermissionError,ValueError)):self.rp.deliver(old)
        self.lp.collect('alice',0);self.rp.collect('bob',0)
        self.assertFalse(list(self.lp.files.iterdir()));self.assertFalse(list(self.rp.files.iterdir()))
        self.assertEqual(self.left.db.execute('SELECT count(*) FROM objects').fetchone()[0],0)
        self.assertEqual(self.left.db.execute("SELECT state FROM cf_private_shares WHERE id=?",(share['id'],)).fetchone()[0],'revoked')

    def test_e2ee_reading_state_converges_with_explicit_reciprocal_consent(self):
        for fabric,owner,page in ((self.left,'alice',2),(self.right,'bob',5)):
            obj=self.upload(fabric,owner,b'same book')
            fabric.create_book(owner,{'id':'shared-book','work_id':'work','edition_id':'edition','file_id':obj['id'],'title':'Book','authors':['Author'],'license':'CC0-1.0','visibility':'private'})
            fabric.state(owner,'reader','shared-book',{'chapter':page})
        from ziokt.library_personal import PersonalLibrary
        library=PersonalLibrary(self.left)
        library.save('alice','note','note-one','shared-book','Private note',{'chapter':1},0)
        library.save('alice','bookmark','mark-one','shared-book','Private bookmark',{'chapter':2},0)
        library.collection_manage('alice','my-books','create',0,'Collection')
        library.collection_manage('alice','my-books','add',1,book='shared-book')
        lw=ContentMaintenance(self.left,{});rw=ContentMaintenance(self.right,{})
        lw.run_once();rw.run_once()
        left=json.loads(self.left.db.execute("SELECT settings FROM subscriptions WHERE owner='alice' AND kind='reader' AND target='shared-book'").fetchone()[0])
        right=json.loads(self.right.db.execute("SELECT settings FROM subscriptions WHERE owner='bob' AND kind='reader' AND target='shared-book'").fetchone()[0])
        self.assertEqual(left,right)
        self.assertEqual(left,{'chapter':2 if self.left.public>self.right.public else 5})
        target=PersonalLibrary(self.right)
        self.assertEqual(target.list('bob','note','shared-book')['items'][0]['text'],'Private note')
        self.assertEqual(target.list('bob','bookmark','shared-book')['items'][0]['label'],'Private bookmark')
        self.assertEqual(target.collection_get('bob','my-books')['items'][0]['id'],'shared-book')
        self.assertEqual(self.left.export()['events'],[])

    def test_replica_ciphertext_corruption_is_repaired_from_a_verified_peer(self):
        data=b'verified autonomous repair';source=self.upload(self.left,'alice',data);target=self.upload(self.right,'bob',data)
        with self.right.transaction():self.right.db.execute('INSERT INTO locations VALUES(?,?,?,?)',(source['id'],target['id'],'bob',int(time.time())))
        # Source must explicitly authorize distribution, just as a normal remote download does.
        self.left.create_book('alice',{'id':'book','work_id':'work','edition_id':'edition','file_id':source['id'],'title':'Repair source','authors':['Alice'],'license':'CC0-1.0','visibility':'public'})
        row=self.right.db.execute('SELECT * FROM objects WHERE id=?',(target['id'],)).fetchone()
        with self.right.store('bob') as store:
            tag=store.db.execute('SELECT tag FROM members WHERE object=?',(row['reference'],)).fetchone()[0]
            path=store.data/tag;blob=bytearray(path.read_bytes());blob[-1]^=1;path.write_bytes(blob)
        with self.assertRaises(ValueError):self.right.read_chunk('bob',target['id'],0)
        result=ContentMaintenance(self.right,{})._verify_replica(row)
        self.assertEqual(result['state'],'healthy');self.assertEqual(self.right.read_chunk('bob',target['id'],0),data)

    def test_peer_transport_requires_replication_scope(self):
        peer=dict(self.left.remote_peers['other'],token='bob'*10)
        with self.assertRaises(Exception):remote(peer,{'operation':'private.identity','arguments':{'account':'bob'}})


if __name__=='__main__':unittest.main()

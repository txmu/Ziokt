"""Real native owner publication, block inclusion, node ZDNS and website delivery."""
import http.client,json,sqlite3,threading,time,unittest
from pathlib import Path
from ziokt.gateway import Gateway,Server,handler
from ziokt.gateway_store import Store
from ziokt.security import sign
import test_native_naming as native_fixture
from test_native_integration import C


@unittest.skipUnless(C.exists(),'Corium checkout required')
class GatewaySitesTests(unittest.TestCase):
    def setUp(self):
        native_fixture.NativeNamingTests.setUp(self)
        self.objects=self.fixture.root/'var/lib/corix/p2p/objects';self.store=Store(self.objects)
        token=self.fixture.root/'gateway.token';token.write_text('a'*64);token.chmod(0o600)
        self.gateway=Gateway({'objects':str(self.objects),'dht_db':str(self.fixture.root/'var/lib/corix/p2p/dht.db'),'forum_db':str(self.fixture.forum),'state_root':str(self.fixture.root),'network':'default','admin_token':str(token)})
        self.addCleanup(self.gateway.close)
        self.server=Server(('127.0.0.1',0),handler(self.gateway));threading.Thread(target=self.server.serve_forever,daemon=True).start();self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
    def get(self,path,method='GET'):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10);c.request(method,path);r=c.getresponse();value=r.status,dict(r.getheaders()),r.read();c.close();return value
    def publish(self,value,operation):
        target=self.store.put(json.dumps(value).encode());native_fixture.NativeNamingTests.update(self,operation,target);self.fixture.run_core('blockchain_mine_block')
    execute=native_fixture.NativeNamingTests.execute
    def test_legacy_static_native_owner_binding_and_paths(self):
        page=self.store.put(b'<h1>Actual native site</h1>');js=self.store.put(b'export const works=true;')
        self.publish({'files':{'index.html':page,'nested/app.mjs':js}},'publish-site')
        status,headers,body=self.get('/corix/corium/');self.assertEqual(status,200);self.assertIn(b'Actual native',body);self.assertIn('sandbox allow-scripts',headers['Content-Security-Policy']);self.assertNotIn('allow-same-origin',headers['Content-Security-Policy']);self.assertEqual(headers['X-Ziokt-Resolver'],'node-zdns')
        self.assertEqual(self.get('/gateway/c/corium/nested/app.mjs')[2],b'export const works=true;');self.assertEqual(self.get('/corix/corium')[0],308)
        self.assertEqual(self.get('/corix/corium/','HEAD')[2],b'')
        for path in ['/corix/corium/%2e%2e/key','/corix/corium/%2fsecret','/corix/not-owned/','/corix/unapproved.corium/']:
            self.assertNotEqual(self.get(path)[0],200)
        with sqlite3.connect(self.fixture.forum) as db:db.execute("UPDATE nns_records SET target_hash=? WHERE domain_name='corium'",(self.store.put(b'{"files":{}}'),))
        self.assertNotEqual(self.get('/corix/corium/')[0],200)
    def test_multiple_signed_subdomain_delegations_and_private_denial(self):
        key=bytes(range(32));public=sign({},key,'test')['public_key'];expiry=int(time.time())+300
        page=self.store.put(b'<h1>Deep delegated site</h1>');manifest=self.store.put(json.dumps({'files':{'index.html':page}}).encode())
        declarations={};parent=1
        for name,delegate in [('corium',public),('team.corium',public),('blog.team.corium',None)]:
            payload={'network_id':'default','component':'corium','path':name,'parent_revision':parent,'revision':1,'expires_at':expiry,'delegate':delegate,'descriptor':{'public_dns':[],'services':{'corium':{'object':'sha256:'+manifest,'access':'public'}},'private':None}}
            declarations[name]=sign(payload,key,'Ziokt/name-delegation/v1');parent=1
        value={'ziokt_naming':{'network_id':'default','owner':public,'revision':1,'expires_at':expiry,'published_suffixes':['corix'],'delegations':declarations}}
        self.publish(value,'delegate-site')
        self.assertEqual(self.get('/corix/blog.team.corium/')[2],b'<h1>Deep delegated site</h1>')
        self.assertNotEqual(self.get('/corix/missing.blog.team.corium/')[0],200)
        payload=declarations['blog.team.corium']['payload'];payload['descriptor']['services']['corium']['access']='authenticated';declarations['blog.team.corium']=sign(payload,key,'Ziokt/name-delegation/v1')
        self.publish(value,'private-site');self.assertEqual(self.get('/corix/blog.team.corium/')[0],403)

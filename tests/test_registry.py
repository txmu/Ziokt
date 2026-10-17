"""Approval boundaries, immutable digests, crash-safe native submissions and public signatures."""
import hashlib,json,tempfile,threading,time,unittest,http.client
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ziokt.registry import Registry
from ziokt.gateway_store import encoded,database
from ziokt.gateway import Gateway,Server,handler
from ziokt.mcp import Service,McpError

class RegistryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.registry=Registry(self.root/'registry.db','test')
  self.external={'kind':'external_chain','target':'chain-a','description':'Real chain registration','weight':150,'genesis_hash':'a'*64,'verifier_hash':'b'*64}
  self.engine={'kind':'pouw_engine','target':'engine-a','description':'Verified engine','weight':7,'pkg_id':'compute/test:0','compute_program_hash':'c'*64,'verifier_script_hash':'d'*64}
 def test_whitelist_digest_unique_revoke(self):
  item=self.registry.submit('applicant',self.external);self.assertEqual(self.registry.list()['registrations'],[])
  with self.assertRaises(ValueError):self.registry.decide('owner',item['id'],'e'*64,'approve',None)
  result=self.registry.decide('owner',item['id'],item['digest'],'approve',None);self.assertTrue(result['effective'])
  duplicate=self.registry.submit('other',self.external)
  with self.assertRaises(ValueError):self.registry.decide('owner',duplicate['id'],duplicate['digest'],'approve',None)
  self.registry.decide('owner',item['id'],item['digest'],'revoke',None);self.assertEqual(self.registry.list()['registrations'],[])
 def test_pouw_native_receipt_and_uncertain_outcome(self):
  calls=[]
  def native(action,payload):calls.append((action,json.loads(payload)));return 'f'*64
  item=self.registry.submit('applicant',self.engine)
  result=self.registry.decide('owner',item['id'],item['digest'],'approve',native)
  self.assertEqual(calls[0][1]['reward_weight'],7);self.assertEqual(result['native_transaction'],'f'*64)
  with self.assertRaises(ValueError):self.registry.decide('owner',item['id'],item['digest'],'approve',native)
  self.assertEqual(len(calls),1)
  self.engine['target']='engine-b';item=self.registry.submit('applicant',self.engine)
  with self.assertRaises(ValueError):self.registry.decide('owner',item['id'],item['digest'],'approve',lambda *a:'uncertain')
  self.assertEqual(self.registry.list('submitting')['registrations'][0]['id'],item['id'])
  with self.assertRaises(ValueError):self.registry.decide('owner',item['id'],item['digest'],'approve',native)
 def test_validation_and_owner_scope(self):
  for change in ({'weight':True},{'weight':0},{'weight':1.5},{'genesis_hash':'x'},{'extra':'bad'}):
   with self.assertRaises(ValueError):self.registry.submit('a',{**self.external,**change})
  token=self.root/'token';token.write_text('owner-secret');token.chmod(0o600)
  gateway=self.root/'gateway.json';gateway.write_text(json.dumps({'network':'test','objects':str(self.root/'objects'),'forum_db':str(self.root/'forum.db'),'registry_db':str(self.root/'registry.db'),'admin_token':str(token)}));gateway.chmod(0o600)
  service=Service({'state':str(self.root/'mcp'),'gateway':str(gateway),'issuer':'https://example.test','writes_enabled':True,'admin_token':str(token),'clients':{'applicant':{'scopes':['corium:registry:submit','corium:registry:read']},'owner':{'scopes':['ziokt:admin','corium:registry:read']}}})
  applicant={'client':'applicant','scopes':{'corium:registry:submit','corium:registry:read'}}
  item=service.call(applicant,'corium_registration_submit',{'entry':self.external},'a'*16)['structuredContent']
  args={'registration_id':item['id'],'digest':item['digest'],'decision':'approve','confirm':True}
  with self.assertRaises(McpError):service.call(applicant,'corium_registration_decide',args,'b'*16)
  owner={'client':'owner','scopes':{'ziokt:admin','corium:registry:read'}}
  self.assertFalse(service.call(owner,'corium_registration_decide',args,'c'*16)['isError'])
 def test_public_signed_submission_and_replay(self):
  config={'network':'test','objects':str(self.root/'objects'),'forum_db':str(self.root/'forum.db'),'registry_db':str(self.root/'registry.db')}
  server=Server(('127.0.0.1',0),handler(Gateway(config)));threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
  key=Ed25519PrivateKey.generate();payload={'schema':'ziokt.registry.v1','network':'test','entry':self.external,'timestamp':int(time.time()),'nonce':'e'*64,'public_key':key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()};payload['signature']=key.sign(encoded(payload)).hex()
  def post(path,payload):
   conn=http.client.HTTPConnection('127.0.0.1',server.server_port);conn.request('POST',path,json.dumps(payload),{'Content-Type':'application/json'});r=conn.getresponse();status=r.status;r.read();conn.close();return status
  self.assertEqual(post('/api/gateway/registrations',payload),201)
  self.assertEqual(post('/api/gateway/registrations',payload),403)
  self.assertEqual(post('/api/gateway/registrations/decide',{}),403)
  self.assertEqual(self.registry.list()['registrations'],[])

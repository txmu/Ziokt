"""Real provisioned MCP and signed native Community; no source stubs."""
import json,tempfile,unittest
from pathlib import Path
from ci.gui_fixture import configuration
from ziokt.mcp import Service

class SocialHubTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  gateway=configuration(self.root);self.config=json.loads(Path(gateway['mcp_config']).read_text())
  self.config['social_federation']={'enabled':True,'network':'test','sources':{'ziokt-operator':{'forum':{'tool':'community_forum_list','kind':'content','arguments':{'limit':30,'offset':0},'items':'items','fields':{'id':'native_id','title':'body.title','text':'body.text','proof':'proof','author':'author','deleted':'deleted'}}}}}
  self.service=Service(self.config);self.addCleanup(self.service.close)
  self.config['clients']['ziokt-operator']['scopes']=self.service.scopes
  self.principal={'client':'ziokt-operator','scopes':set(self.service.scopes)}
 def call(self,name,args):
  result=self.service.call(self.principal,name,args,key='socialtestoperation'+name.replace('_',''))
  self.assertFalse(result['isError'],result);return result['structuredContent']
 def test_native_search_notifications_dedup_and_scope_revocation(self):
  self.call('community_forum_post',{'title':'Native title','body':'searchable native words','operation':'socialtestpost123','reply_to':''})
  first=self.call('social_query',{'query':'searchable'})
  self.assertEqual(len(first['items']),1);item=first['items'][0];self.assertTrue(item['unread']);self.assertIn('signature',item['proof'])
  self.call('social_acknowledge',{'source':'forum','id':item['id'],'version':item['version']})
  self.assertEqual(self.call('social_query',{'unread':True})['items'],[])
  self.assertEqual(len(self.call('social_query',{})['items']),1)
  self.principal['scopes']={s for s in self.service.scopes if s!='community:read'}
  result=self.call('social_query',{});self.assertEqual(result['items'],[]);self.assertEqual(len(result['unavailable']),1)
 def test_source_cannot_invoke_writes_or_other_account(self):
  source=self.config['social_federation']['sources']['ziokt-operator']['forum'];source['tool']='community_forum_post'
  self.assertEqual(self.call('social_query',{})['items'],[])
  self.principal={'client':'other','scopes':set(self.service.scopes)}
  self.assertEqual(self.call('social_query',{})['items'],[])

import base64,hashlib,json,secrets,tempfile,threading,unittest
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import xml.etree.ElementTree as ET
from ziokt.content_fabric import Fabric
from ziokt.content_server import server
from ziokt.community import Community,create_policy
from ziokt.community_application import CommunityApplication
from ziokt.security import sign

class FeedTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.f=Fabric(self.root/'state');self.token='t'*40;self.restricted='r'*40
  self.f.create_group('alice','books.open');self.f.create_group('alice','books.private',visibility='private');self.f.post('alice',['books.open'],'Public <script>','Original <script>alert(1)</script>',message_id='<public@feed.test>');self.f.post('alice',['books.private'],'Private title','Private bytes',message_id='<private@feed.test>')
  # An ordinary account named public must never become the anonymous identity.
  self.f.create_group('public','books.reserved',visibility='private');self.f.post('public',['books.reserved'],'Reserved private','Never public')
  self.http=server(self.f,{'port':0,'public_read':True,'tokens':[{'account':'alice','token':self.token,'scopes':['feeds:read','library:read','netnews:read']},{'account':'alice','token':self.restricted,'scopes':['library:read','netnews:read']}]});self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.base='http://127.0.0.1:'+str(self.http.server_port)
 def tearDown(self):self.http.shutdown();self.http.server_close();self.thread.join();self.f.close();self.temp.cleanup()
 def get(self,path,token=None,extra=None):
  headers=dict(extra or {})
  if token:headers['Authorization']='Basic '+base64.b64encode(('alice:'+token).encode()).decode()
  return urlopen(Request(self.base+path,headers=headers),timeout=5)
 def test_standard_formats_conditional_get_privacy_and_xml_escaping(self):
  for fmt in ('rss','atom','json'):
   with self.get('/feeds/all.'+fmt) as response:
    raw=response.read();etag=response.headers['ETag'];self.assertIn('Authorization',response.headers['Vary']);self.assertNotIn(b'Private bytes',raw);self.assertNotIn(b'Reserved private',raw)
   if fmt=='rss':self.assertEqual(ET.fromstring(raw).attrib['version'],'2.0');self.assertIn(b'&lt;script&gt;',raw)
   elif fmt=='atom':self.assertEqual(ET.fromstring(raw).tag,'{http://www.w3.org/2005/Atom}feed')
   else:
    parsed=json.loads(raw);self.assertEqual(parsed['version'],'https://jsonfeed.org/version/1.1');self.assertNotIn('content_html',parsed['items'][0])
   with self.assertRaises(HTTPError) as error:self.get('/feeds/all.'+fmt,extra={'If-None-Match':etag})
   self.assertEqual(error.exception.code,304)
  with self.get('/feeds/netnews.json?group=books.open') as response:self.assertEqual(len(json.load(response)['items']),1)
  with self.assertRaises(HTTPError) as error:self.get('/feeds/netnews.json?group=books.private')
  self.assertEqual(error.exception.code,403)
 def test_authenticated_private_feed_and_withdrawal(self):
  with self.get('/feeds/all.json',self.token) as response:
   raw=response.read();items=json.loads(raw)['items'];self.assertEqual(len(items),2);self.assertNotIn(self.token.encode(),raw);self.assertIn('private',response.headers['Cache-Control'])
  private=next(item for item in items if item['title']=='Private title');self.assertEqual(private['_ziokt']['native_id'],'<private@feed.test>')
  self.f.withdraw('alice','<private@feed.test>')
  with self.get('/feeds/all.json',self.token) as response:self.assertNotIn(b'Private title',response.read())
  with self.assertRaises(HTTPError) as error:self.get('/feeds/all.json','wrong')
  self.assertEqual(error.exception.code,403)
 def test_native_community_delegation_proof_and_observed_time(self):
  owner=secrets.token_bytes(32);member=secrets.token_bytes(32);key=secrets.token_bytes(32);owner_public=sign({},owner,'test')['public_key'];member_public=sign({},member,'test')['public_key'];policy=create_policy(owner,'feed-native',{owner_public:['forum'],member_public:['forum']},privacy='private')
  for name,data in [('policy.json',json.dumps(policy).encode()),('encryption.key',key),('member.key',member)]:path=self.root/name;path.write_bytes(data);path.chmod(0o600)
  with Community(self.root/'community',policy,owner_public,key):pass
  config={'root':str(self.root/'community'),'owner':owner_public,'policy':str(self.root/'policy.json'),'encryption_key':str(self.root/'encryption.key'),'accounts':{'alice':{'public_key':member_public,'signing_key':str(self.root/'member.key')}}};self.f.community_config=config
  adapter=CommunityApplication(config,'alice',write=True)
  try:posted=adapter.post('Native Community','Original authorized content','feed-post-1')
  finally:adapter.close()
  with self.get('/feeds/community.json',self.token) as response:
   result=json.load(response);etag=response.headers['ETag'];item=result['items'][0];self.assertEqual(item['_ziokt']['proof'],posted['proof']);self.assertEqual(item['_ziokt']['date_kind'],'first_observed');self.assertEqual(item['content_text'],'Original authorized content')
  with self.assertRaises(HTTPError) as error:self.get('/feeds/community.json',self.token,{'If-None-Match':etag})
  self.assertEqual(error.exception.code,304)
  with self.get('/feeds/all.json',self.restricted) as response:self.assertNotIn(b'Original authorized content',response.read())
  with self.assertRaises(HTTPError) as error:self.get('/feeds/community.json')
  self.assertEqual(error.exception.code,403)

if __name__=='__main__':unittest.main()

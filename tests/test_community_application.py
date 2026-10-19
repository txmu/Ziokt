import json,secrets,tempfile,unittest
from pathlib import Path
from ziokt.community import Community,create_policy
from ziokt.community_application import CommunityApplication
from ziokt.security import sign,verify

class CommunityApplicationTests(unittest.TestCase):
 def test_independent_member_authority_original_proof_and_persistent_idempotency(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);owner=secrets.token_bytes(32);member=secrets.token_bytes(32);key=secrets.token_bytes(32)
   owner_public=sign({},owner,'test')['public_key'];member_public=sign({},member,'test')['public_key']
   policy=create_policy(owner,'api-test',{owner_public:['forum'],member_public:['forum']},privacy='private')
   for name,data in [('policy.json',json.dumps(policy).encode()),('encryption.key',key),('member.key',member)]:
    path=root/name;path.write_bytes(data);path.chmod(0o600)
   with Community(root/'community',policy,owner_public,key):pass
   config={'root':str(root/'community'),'owner':owner_public,'policy':str(root/'policy.json'),'encryption_key':str(root/'encryption.key'),'accounts':{'alice':{'public_key':member_public,'signing_key':str(root/'member.key')}}}
   adapter=CommunityApplication(config,'alice',write=True)
   try:
    posted=adapter.post('A native post','Actual native Community event','operation-00001')
    self.assertTrue(adapter.post('A native post','Actual native Community event','operation-00001')['duplicate'])
    verified=verify(posted['proof'],member_public,'Ziokt/community-event/v1')
    self.assertEqual(verified['body']['text'],'Actual native Community event')
   finally:adapter.close()
   reader=CommunityApplication(config,'alice')
   try:self.assertEqual(len(reader.list()['items']),1)
   finally:reader.close()
   with self.assertRaises(PermissionError):CommunityApplication(config,'unmapped')

if __name__=='__main__':unittest.main()

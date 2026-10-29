"""Actual HTTP peer and Fabric bytes: optional backend denial and verified fallback."""
import base64,hashlib,tempfile,threading,unittest
from pathlib import Path
from ziokt.content_fabric import Fabric
from ziokt.content_server import server,_download_object

class RetroShareFallbackTests(unittest.TestCase):
 def test_disabled_backend_falls_back_only_with_explicit_permission(self):
  with tempfile.TemporaryDirectory() as temp:
   source=Fabric(Path(temp)/'source');target=Fabric(Path(temp)/'target')
   http=None
   try:
    data=b'actual content bytes'*1000;source.begin('alice','upload',len(data),'sha256:'+hashlib.sha256(data).hexdigest())
    for pos,start in enumerate(range(0,len(data),16384)):source.put('alice','upload',pos,data[start:start+16384])
    obj=source.finish('alice','upload');meta=__import__('json').loads(source.object_info('alice',obj['id'])['metadata'])
    http=server(source,{'port':0,'tokens':[{'account':'alice','token':'t'*40,'scopes':['content:read','content:write']}]});thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    peer={'url':'http://127.0.0.1:'+str(http.server_port),'token':'t'*40,'retroshare':{'peer':'a'*32,'fallback':False}}
    failed=_download_object(target,'alice',meta,obj['id'],['source'],{'source':peer},max_chunks=4);self.assertNotEqual(failed['state'],'complete')
    with target.transaction():target.db.execute('DELETE FROM source_health')
    peer['retroshare']['fallback']=True
    completed=_download_object(target,'alice',meta,obj['id'],['source'],{'source':peer},max_chunks=4)
    self.assertEqual(completed['state'],'complete');self.assertTrue(completed['verified']);self.assertEqual(target.read_chunk('alice',completed['object']['id'],0),data[:16384])
   finally:
    if http:http.shutdown();http.server_close();thread.join()
    source.close();target.close()

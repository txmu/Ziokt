"""Local atomicity and denial unit tests; real native mesh lives in CI."""
import tempfile,unittest,time
from pathlib import Path
from ziokt.content_fabric import Fabric
from ziokt.content_etp import EtpNews

class EtpContentBoundaryTests(unittest.TestCase):
    def test_native_authorization_cannot_be_implicit(self):
        with tempfile.TemporaryDirectory() as area:
            f=Fabric(Path(area)/'fabric')
            try:
                class Unused:
                    def call(self,*args):raise AssertionError('unauthorized native call')
                bridge=EtpNews(f,Unused())
                with self.assertRaises(PermissionError):bridge.authorize('alice','author','native-forum','news.bridge',expires=int(time.time())+60)
                with self.assertRaises(PermissionError):bridge.accept_authorization('alice','a'*64)
                with self.assertRaises(PermissionError):bridge.grant('alice','nonexistent')
            finally:f.close()

    def test_nested_content_mutation_rolls_back_as_one_import(self):
        with tempfile.TemporaryDirectory() as area:
            f=Fabric(Path(area)/'fabric')
            try:
                f.create_group('alice','news.bridge')
                with self.assertRaisesRegex(RuntimeError,'interrupted'):
                    with f.transaction():
                        f.post('alice',['news.bridge'],'test','must roll back',message_id='<atomic@example.invalid>')
                        raise RuntimeError('interrupted mapping transaction')
                self.assertEqual(f.articles('alice','news.bridge')['items'],[])
                self.assertEqual(f.export()['events'],[])
            finally:f.close()

    def test_application_policy_status_and_offline_errors(self):
        import json,threading,urllib.request,urllib.error
        from ziokt.content_server import server
        with tempfile.TemporaryDirectory() as area:
            f=Fabric(Path(area)/'fabric');f.create_group('alice','news.bridge')
            native={'gateway':{'binary':str(Path(area)/'missing-native-binary'),'digest':'sha256:'+'0'*64,'config':str(Path(area)/'missing-native-config')},'accounts':{'alice':{'aliases':['author'],'topics':['native-forum'],'groups':['news.bridge'],'remote_authors':[]}}}
            http=server(f,{'port':0,'native_etp':native,'tokens':[{'account':'alice','token':'test-content-account','scopes':['content:read','content:write']}]})
            thread=threading.Thread(target=http.serve_forever);thread.start()
            def call(operation,arguments):
                raw=json.dumps({'operation':operation,'arguments':arguments}).encode()
                request=urllib.request.Request('http://127.0.0.1:'+str(http.server_port)+'/api',raw,{'Authorization':'Bearer test-content-account','Content-Type':'application/json'})
                with urllib.request.urlopen(request) as response:return json.load(response)
            try:
                self.assertEqual(call('content.etp.status',{})['grants'],[])
                with self.assertRaises(urllib.error.HTTPError) as denied:call('content.etp.authorize',{'alias':'unassigned','topic':'native-forum','group':'news.bridge','expires':int(time.time())+60})
                self.assertEqual(denied.exception.code,403);denied.exception.close()
                with self.assertRaises(urllib.error.HTTPError) as offline:call('content.etp.authorize',{'alias':'author','topic':'native-forum','group':'news.bridge','expires':int(time.time())+60})
                self.assertEqual(offline.exception.code,503);self.assertEqual(json.load(offline.exception)['code'],'ETP_UNAVAILABLE');offline.exception.close()
                self.assertEqual(f.articles('alice','news.bridge')['items'],[])
            finally:http.shutdown();http.server_close();thread.join();f.close()

    def test_native_inventory_ipc_rejects_inconsistent_cursor(self):
        from ziokt.etp import _forum_result,_forum_params
        from ziokt.protocol import ProtocolError
        params={'topic':'native-topic','author_id':'a'*64,'snapshot':'b'*64,'after':'','limit':2}
        result={'schema':'ziokt.etp-forum-scan.v1','state':'page','topic_hash':'c'*64,'author_id':'a'*64,'snapshot':'b'*64,'ids':['1'*64,'2'*64],'after':'2'*64,'complete':True}
        self.assertEqual(_forum_result('etp.forum.scan',params,result),result)
        with self.assertRaises(ProtocolError):_forum_result('etp.forum.scan',params,{**result,'after':'3'*64})
        with self.assertRaises(ProtocolError):_forum_result('etp.forum.scan',params,{**result,'ids':[],'after':'','complete':False})
        with self.assertRaises(ProtocolError):_forum_params('etp.forum.scan',{**params,'limit':True})

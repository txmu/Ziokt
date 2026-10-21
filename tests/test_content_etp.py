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

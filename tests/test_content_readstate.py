"""Durable read marks using actual SQLite and shared authenticated API dispatch."""
import tempfile
import unittest
from pathlib import Path
from ziokt.content_fabric import Fabric
from ziokt.content_api import invoke,required_scopes


class ReadStateTests(unittest.TestCase):
    def test_restart_isolation_retry_and_offline_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'node';fabric=Fabric(root)
            try:
                fabric.create_group('alice','news.public',visibility='public')
                article=fabric.post('alice',['news.public'],'Subject','Body')['id']
                args={'article':article,'is_read':True,'revision':0}
                result=invoke(fabric,'alice','netnews.readstate.update',args)
                self.assertEqual(result,invoke(fabric,'alice','netnews.readstate.update',args))
                self.assertFalse(invoke(fabric,'bob','netnews.readstate.get',{'article':article})['is_read'])
                invoke(fabric,'alice','netnews.readstate.update',{'article':article,'is_read':False,'revision':1})
                with self.assertRaisesRegex(ValueError,'revision conflict'):
                    invoke(fabric,'alice','netnews.readstate.update',args)
                fabric.close();fabric=Fabric(root)
                self.assertEqual(invoke(fabric,'alice','netnews.readstate.get',{'article':article}),{'article':article,'is_read':False,'revision':2})
            finally:fabric.close()

    def test_final_authorization_and_strict_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            fabric=Fabric(Path(temp)/'node')
            try:
                fabric.create_group('alice','news.private',visibility='private')
                article=fabric.post('alice',['news.private'],'Private','Secret')['id']
                for operation,args in [('netnews.readstate.get',{'article':article}),('netnews.readstate.update',{'article':article,'is_read':True,'revision':0})]:
                    with self.assertRaises(PermissionError):invoke(fabric,'bob',operation,args)
                with self.assertRaises(ValueError):invoke(fabric,'alice','netnews.readstate.update',{'article':article,'is_read':True,'revision':True})
                self.assertEqual(required_scopes('netnews.readstate.get'),{'netnews:read'})
                self.assertEqual(required_scopes('netnews.readstate.update'),{'netnews:write'})
                fabric.withdraw('alice',article)
                with self.assertRaises(PermissionError):invoke(fabric,'alice','netnews.readstate.get',{'article':article})
            finally:fabric.close()


if __name__=='__main__':unittest.main()

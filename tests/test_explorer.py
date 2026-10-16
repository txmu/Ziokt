"""Read-only explorer over a real native chain, served through the public handler."""
import http.client
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from test_native_integration import C
from ziokt.effort_web import EffortPool,effort_server
from ziokt.explorer import ChainExplorer
from ziokt.protocol import ProtocolError
from test_effort_web import FakeChain

class ExplorerTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0,str(C))
        from test_core import Fixture
        self.fixture=Fixture();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.explorer=ChainExplorer(self.fixture.root,'default')

    def test_native_inclusion_lookup_validation_and_no_payload_disclosure(self):
        self.fixture.run_core('blockchain_create_transaction set_nickname \'{"nickname":"PRIVATE-PAYLOAD-MARKER"}\' >/dev/null; blockchain_mine_block >/dev/null')
        before=self.fixture.semantic()
        summary=self.explorer.query('/api/explorer/summary')
        self.assertEqual(summary['tip_height'],1);self.assertEqual(summary['active_validators'],1)
        self.assertFalse(summary['irreversible_finality'])
        blocks=self.explorer.query('/api/explorer/blocks')['blocks']
        self.assertEqual([b['height'] for b in blocks],[1,0]);self.assertEqual(blocks[0]['confirmations'],1)
        detail=self.explorer.query('/api/explorer/block/'+blocks[0]['hash'])
        tx=detail['transactions'][0];self.assertEqual(tx['type'],'set_nickname')
        fact=self.explorer.query('/api/explorer/transaction/'+tx['hash'])
        self.assertEqual(fact['transaction']['phase'],'included');self.assertEqual(fact['transaction']['confirmations'],1)
        self.assertNotIn('PRIVATE-PAYLOAD-MARKER',json.dumps(fact));self.assertNotIn('public_key',fact['transaction'])
        for path in ['/api/explorer/blocks?before=-1','/api/explorer/blocks?before=1&before=2','/api/explorer/block/1 OR 1=1','/api/explorer/summary?sql=DROP','/api/explorer/transaction/../../identity.key','/api/explorer/blocks?before='+('1'*2048)]:
            with self.subTest(path=path),self.assertRaises(ProtocolError):self.explorer.query(path)
        with self.assertRaises(ProtocolError) as error:self.explorer.query('/api/explorer/block/999')
        self.assertEqual(error.exception.code,'NOT_FOUND')
        self.assertEqual(self.fixture.semantic(),before)

    def test_real_http_assets_api_origin_and_missing_chain_fail_closed(self):
        pool=EffortPool(FakeChain(),'a'*64,self.fixture.root/'web');self.addCleanup(pool.close)
        server=effort_server(pool,'http://127.0.0.1:0',explorer=self.explorer)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(thread.join,2);self.addCleanup(server.shutdown)
        def get(path,host='127.0.0.1:0'):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            conn.request('GET',path,headers={'Host':host});response=conn.getresponse();data=response.read();conn.close();return response.status,data
        self.assertEqual(get('/explorer/')[0],200);self.assertIn(b'textContent',get('/explorer/app.js')[1])
        self.assertEqual(json.loads(get('/api/explorer/summary')[1])['tip_height'],0)
        self.assertEqual(get('/api/explorer/summary','evil.invalid')[0],403)
        self.assertEqual(get('/api/explorer/block/999')[0],404)
        with sqlite3.connect(self.explorer.path) as db:db.execute('DROP TABLE blocks')
        status,data=get('/api/explorer/summary');self.assertEqual(status,503);self.assertEqual(json.loads(data)['error'],'CHAIN_UNAVAILABLE')

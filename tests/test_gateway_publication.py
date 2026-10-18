import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ziokt.gateway_bootstrap import publish

class GatewayPublicationTests(unittest.TestCase):
    def test_real_object_storage_bounded_signed_batches_no_optimistic_nns(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);forum=root/'forum.db'
            with sqlite3.connect(forum) as db:db.execute('CREATE TABLE nns_records(domain_name TEXT PRIMARY KEY,target_hash TEXT)')
            config={'objects':str(root/'objects'),'dht_db':None,'forum_db':str(forum)}
            with patch('ziokt.gateway.Gateway') as gateway:
                report=publish(config);submitted=[call.args for call in gateway.return_value.native.call_args_list]
                self.assertFalse(report['consensus_confirmed']);self.assertGreater(len(submitted),32)
                with sqlite3.connect(forum) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM nns_records').fetchone()[0],0)
                with sqlite3.connect(forum) as db:db.executemany('INSERT INTO nns_records VALUES (?,?)',[(call[1],'a'*64) for call in submitted if call[0]=='register'])
                gateway.return_value.native.reset_mock();report=publish(config)
                batches=[json.loads(call.args[1])['records'] for call in gateway.return_value.native.call_args_list if call.args[0]=='bind']
                self.assertGreater(len(batches),1);self.assertTrue(all(1<=len(batch)<=32 for batch in batches))
                self.assertEqual(sum(map(len,batches)),report['submitted_updates'])
                with sqlite3.connect(forum) as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM nns_records WHERE target_hash!='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'").fetchone()[0],0)
            with patch('ziokt.gateway.Gateway') as gateway:
                gateway.return_value.native.side_effect=OSError('native submission failed')
                with self.assertRaises(OSError):publish(config)

if __name__=='__main__':unittest.main()

import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest

from ziokt.doomsday import snapshot,restore,inspect
from ziokt.protocol import ProtocolError


class SurvivalTests(unittest.TestCase):
    def test_live_wal_database_offline_replicas_and_cold_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);signing=root/'sign';key=root/'encryption'
            for path in (signing,key):path.write_bytes(secrets.token_bytes(32));path.chmod(0o600)
            database=root/'live.db';db=sqlite3.connect(database);self.addCleanup(db.close)
            db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE events (body TEXT)');db.execute("INSERT INTO events VALUES ('survives offline')");db.commit()
            config={'signing_key_file':str(signing),'encryption_key_file':str(key),'artifacts':[{'id':'community/events.db','path':str(database),'kind':'sqlite'}],
                    'replicas':[str(root/'usb-a'),str(root/'usb-b')]}
            result=snapshot(config,root/'cold.zds')
            self.assertEqual([value['state'] for value in result['replicas']],['verified','verified'])
            self.assertNotIn(b'survives offline',(root/'cold.zds').read_bytes())
            replica=root/'usb-b'/('snapshot-'+result['sha256']+'.zds')
            (root/'cold.zds').unlink()
            restored=restore(replica,key.read_bytes(),result['publisher'],root/'recovered')
            self.assertFalse(restored['services_activated'])
            with sqlite3.connect(root/'recovered/community/events.db') as recovered:self.assertEqual(recovered.execute('SELECT body FROM events').fetchone()[0],'survives offline')
            with self.assertRaises(ProtocolError):restore(replica,key.read_bytes(),result['publisher'],root/'recovered')
            with self.assertRaises(ProtocolError):inspect(replica,secrets.token_bytes(32),result['publisher'])
            with self.assertRaises(ProtocolError):inspect(replica,key.read_bytes(),'f'*64)
            damaged=bytearray(replica.read_bytes());damaged[-1]^=1;replica.write_bytes(damaged)
            with self.assertRaises(ProtocolError):restore(replica,key.read_bytes(),result['publisher'],root/'invalid')
            self.assertFalse((root/'invalid').exists())

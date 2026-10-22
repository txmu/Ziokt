import json
from pathlib import Path
import sqlite3
import stat
import subprocess
import tempfile
import unittest
from tools import deploy_frozen_services as deploy


class FrozenTests(unittest.TestCase):
    def test_committed_source_is_frozen_hashed_idempotent_and_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir();runtime=root/'runtime'
            def git(*args):return subprocess.check_output(['git',*args],cwd=source,stderr=subprocess.DEVNULL,text=True)
            git('init');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
            (source/'entry.py').write_text('print("fixture")\n');git('add','entry.py');git('commit','-m','fixture')
            previous=deploy.ROOT;deploy.ROOT=source
            try:
                release,commit=deploy.stage(runtime,'HEAD')
                self.assertEqual(json.loads((release/'DEPLOYED_BUILD.json').read_text())['source_commit'],commit)
                self.assertEqual(stat.S_IMODE((release/'entry.py').stat().st_mode),0o444)
                self.assertEqual(stat.S_IMODE(release.stat().st_mode),0o555)
                self.assertEqual(deploy.stage(runtime,'HEAD'),(release,commit))
                (release/'entry.py').chmod(0o644);(release/'entry.py').write_text('tampered')
                with self.assertRaises(ValueError):deploy.stage(runtime,'HEAD')
            finally:deploy.ROOT=previous
    def test_sqlite_backup_preserves_data_and_is_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.db';backup=Path(directory)/'backup.db'
            with sqlite3.connect(source) as db:db.execute('create table content(value)');db.execute('insert into content values (?)',('preserved',))
            deploy.backup_database(source,backup)
            with sqlite3.connect(backup) as db:self.assertEqual(db.execute('select value from content').fetchone()[0],'preserved');db.execute('delete from content')
            with sqlite3.connect(source) as db:self.assertEqual(db.execute('select count(*) from content').fetchone()[0],1)
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode),0o600)

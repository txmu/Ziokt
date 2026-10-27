"""Reproduce the shipped zipapp from a foreign cwd with no source import path."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

class StandaloneMailTests(unittest.TestCase):
    def test_two_independent_configs_sync_from_zipapp_without_checkout_on_import_path(self):
        repo=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);foreign=base/'foreign';foreign.mkdir()
            env=dict(os.environ);env.pop('PYTHONPATH',None)
            subprocess.run([sys.executable,str(repo/'ci/build.py')],cwd=foreign,env=env,check=True,stdout=subprocess.DEVNULL,timeout=30)
            application=repo/'dist/ziokt.pyz';states=[]
            for name in ('first','second'):
                state=base/name;config=base/(name+'.json')
                config.write_text(json.dumps({'state':str(state),'internet':{'account':name,'from_address':name+'@example.invalid','local_recipient':name,'allowed_senders':[]}}));config.chmod(0o600)
                run=subprocess.run([sys.executable,str(application),'mail','--config',str(config),'internet-sync','--once'],cwd=foreign,env=env,check=True,capture_output=True,text=True,timeout=15)
                result=json.loads(run.stdout);self.assertEqual(result['account'],name);self.assertEqual(result['outbox'],{})
                self.assertEqual(result['read_receipts']['policy'],'deny')
                self.assertTrue((state/'internet/internet-mail.db').is_file());states.append(state)
            self.assertNotEqual(states[0],states[1])

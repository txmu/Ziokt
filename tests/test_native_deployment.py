"""Real files/SQLite backups; never restart host services during verification."""
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import deploy_native_gateway as deployment


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ziokt-native-deployment-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root/'config').mkdir()
        (self.root/'bin').mkdir()
        self.target = self.root/'bin/corix_v108.sh'
        self.target.write_text('#!/bin/bash\ntrue\n')
        self.source = self.root/'reviewed.sh'
        self.source.write_text('#!/bin/bash\nprintf reviewed\n')
        state = self.root/'corium'
        self.chain = state/'var/lib/corix/networks/test-upgrade/blockchain/chain.db'
        self.chain.parent.mkdir(parents=True)
        for db in (self.chain, self.root/'forum.db', self.root/'dht.db'):
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute('CREATE TABLE evidence(value TEXT)')
                connection.execute('INSERT INTO evidence VALUES (?)', ('preserve-confirmed-state',))
        config = {'corix': str(self.target), 'corix_digest': 'sha256:'+'1'*64,
                  'forum_db': str(self.root/'forum.db'), 'dht_db': str(self.root/'dht.db'),
                  'service_units':{'p2p':'fixture-p2p','consensus':'fixture-consensus','relayer':'fixture-relayer','gateway':'fixture-gateway','mcp':'fixture-mcp','telegram':'fixture-telegram'}, 'state_root': str(state), 'network': 'test-upgrade', 'dns_config': 'preserve-this-setting'}
        (self.root/'config/gateway.json').write_text(json.dumps(config))
        (self.root/'config/federation.json').write_text(json.dumps({'providers': [{'native_project': 'corium', 'entrypoint_digest': 'sha256:'+'1'*64}]}))
        (self.root/'config/runtime-digests.json').write_text(json.dumps({'digests': {'corix_v108.sh': '1'*64}}))

    def test_native_upgrade_updates_both_pins_and_preserves_confirmed_database(self):
        original_run = subprocess.run
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            if command[0] == 'bash': return original_run(command, **kwargs)
            return subprocess.CompletedProcess(command, 3 if 'is-active' in command else 0)

        with patch.object(deployment.os, 'geteuid', return_value=0), patch.object(deployment.subprocess, 'run', side_effect=run), patch.object(deployment.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"healthy":true}')):
            receipt = deployment.deploy(self.root, self.source)
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        config = json.loads((self.root/'config/gateway.json').read_text())
        federation = json.loads((self.root/'config/federation.json').read_text())
        self.assertEqual(config['corix_digest'], federation['providers'][0]['entrypoint_digest'])
        self.assertEqual(config['corix_digest'], 'sha256:'+digest)
        self.assertEqual(config['dns_config'], 'preserve-this-setting')
        with closing(sqlite3.connect(Path(receipt['backup'])/'chain.db')) as db:
            self.assertEqual(db.execute('SELECT value FROM evidence').fetchone()[0], 'preserve-confirmed-state')
        with closing(sqlite3.connect(self.chain)) as db:
            self.assertEqual(db.execute('SELECT value FROM evidence').fetchone()[0], 'preserve-confirmed-state')
        self.assertTrue(any('restart' in command for command in commands))

    def test_restart_permission_failure_leaves_sources_and_pins_untouched(self):
        paths = (self.target, self.root/'config/federation.json', self.root/'config/gateway.json')
        before = [path.read_bytes() for path in paths]
        original_run = subprocess.run

        def run(command, **kwargs):
            if command[0] == 'bash': return original_run(command, **kwargs)
            if command[0] == 'sudo': raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 3)

        with patch.object(deployment.os, 'geteuid', return_value=1000), patch.object(deployment.subprocess, 'run', side_effect=run):
            with self.assertRaises(subprocess.CalledProcessError):
                deployment.deploy(self.root, self.source)
        self.assertEqual([path.read_bytes() for path in paths], before)
        self.assertFalse((self.root/'private-bootstrap-backup').exists())


if __name__ == '__main__':
    unittest.main()

"""Real Corium compute dispatch and signed proof material, no native compilation."""
import base64
import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import unittest

from test_native_integration import C
from ziokt.client import NativeClient
from ziokt.config import fingerprint
from ziokt.protocol import ProtocolError


class ComputeNativeTests(unittest.TestCase):
    def test_native_engine_zero_fixed_dispatch_receipt_and_proof(self):
        sys.path.insert(0, str(C))
        from test_core import Fixture
        fixture = Fixture(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        # Produce a real signed empty next block whose hash has a nonce-zero
        # solution. This exercises the original hash engine deterministically,
        # without changing its production difficulty or risking random timeouts.
        with closing(sqlite3.connect(fixture.chain)) as db:
            previous, weight = db.execute('SELECT hash,total_weight FROM blocks ORDER BY total_weight DESC,height DESC LIMIT 1').fetchone()
        chosen = None
        for timestamp in range(1, 1000000):
            block = json.dumps({'height': 1, 'previous_hash': previous, 'timestamp': timestamp, 'transactions': []}, separators=(',', ':'))
            candidate = hashlib.sha256(block.encode()).hexdigest()
            if hashlib.sha256(('default'+fixture.identity+'0'+candidate).encode()).hexdigest().startswith('000'):
                chosen = timestamp; break
        self.assertIsNotNone(chosen)
        next_hash = fixture.add_empty_block(1, previous=previous, timestamp=chosen)
        with closing(sqlite3.connect(fixture.chain)) as db, db:
            db.execute('UPDATE blocks SET total_weight=? WHERE height=1', (weight+1000,))
            db.execute("INSERT OR REPLACE INTO chain_state VALUES ('chain_info',?)", (next_hash+'|1',))
        fixture.run_core('_update_chain_state_cache')
        for path in fixture.root.rglob('*'):
            if path.is_dir(): path.chmod(0o700)
        (fixture.etc/'identity.key').chmod(0o600)
        config = fixture.etc/'corix.conf'
        engine = 'corium/internal-engine-zero-v1'; resource = 'compute:'+engine
        config.write_text('[ziokt]\nenabled=TRUE\nfederation_id=test\nprovider_id=corium-local\nallow_mutations=TRUE\nallowed_operations=compute.run\nallowed_resources='+resource+'\n'); config.chmod(0o600)
        client = NativeClient('test', {'native_project': 'corium', 'provider_id': 'corium-local',
            'root': str(C), 'native_config': str(config), 'state_root': str(fixture.root), 'network_id': 'default',
            'entrypoint_digest': fingerprint(C/'corix_v108.sh')})
        with self.assertRaises(ProtocolError):
            client.call('operation.prepare', {'operation_id': 'bad-engine', 'action': 'compute.run', 'resource': 'compute:unknown', 'arguments': {}, 'expected_revision': None})
        plan = client.call('operation.prepare', {'operation_id': 'engine-zero', 'action': 'compute.run', 'resource': resource, 'arguments': {}, 'expected_revision': None})
        done = client.call('operation.commit', {'operation_id': 'engine-zero', 'plan_digest': plan['plan_digest']})
        self.assertEqual(done['state'], 'committed'); receipt = done['result']
        self.assertTrue(receipt['native_signature_verified']); self.assertFalse(receipt['proof_verified'])
        self.assertEqual(receipt['engine_id'], engine); self.assertEqual(len(receipt['proofs']), 1)
        proof = json.loads(base64.b64decode(receipt['proofs'][0]['data_base64']))
        self.assertEqual(proof['engine_id'], engine); self.assertEqual(proof['proof_data']['submitter_id'], fixture.identity)
        self.assertEqual(proof['proof_data']['nonce'], '0')
        self.assertEqual(client.call('operation.commit', {'operation_id': 'engine-zero', 'plan_digest': plan['plan_digest']}), done)


if __name__ == '__main__': unittest.main()

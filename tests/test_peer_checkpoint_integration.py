import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec
import test_checkpoint_format as fixtures
from ziokt.checkpoint_format import canonical, chunk_bytes, seal, digest, CheckpointError
from ziokt.checkpoint_store import CheckpointStore, export_bundle
from ziokt.checkpoint_restore import materialize_local
from tools.verify_peer_checkpoints import verify_peer_checkpoints


class PeerCheckpointIntegrationTests(unittest.TestCase):
    def setUp(self):
        fixtures.CheckpointTests.setUp(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

        # Create two sets of independent keys (Signer 1 and Signer 2)
        self.keys1 = self.keys
        self.keys2 = {role: ec.generate_private_key(ec.SECP256K1()) for role in ['primary', 'dna']}

        self.manifest1 = seal(self.chains, self.keys1, 100, scope='explicit-signer-bootstrap')
        self.manifest2 = seal(self.chains, self.keys2, 100, scope='explicit-signer-bootstrap')

        self.policy = {
            'expected': self.expected,
            'signers': {
                role: [
                    self.manifest1['signatures'][role]['identity'],
                    self.manifest2['signatures'][role]['identity']
                ]
                for role in ['primary', 'dna']
            }
        }

        # Export bundles to files
        self.bundle1 = self.root / 'bundle1.zip'
        self.bundle2 = self.root / 'bundle2.zip'
        export_bundle(self.bundle1, self.manifest1, self.objects)
        export_bundle(self.bundle2, self.manifest2, self.objects)

    def test_verify_peer_checkpoints_and_auto_import(self):
        import_store_dir = self.root / 'imported_store'
        materialize_dir = self.root / 'materialized'

        sources = [self.bundle1.as_uri(), self.bundle2.as_uri()]
        result = verify_peer_checkpoints(
            self.policy,
            sources,
            quorum=2,
            import_to=import_store_dir,
            materialize_to=materialize_dir
        )

        self.assertEqual(result['independent_signers'], 2)
        self.assertTrue(result['installed'])
        self.assertFalse(result['independent_history_replay_proved'])
        self.assertEqual(result['verification_level'], 'explicitly trusted sources; historical validity not independently proven')
        self.assertEqual(result['pair_commitment'], self.manifest1['pair_commitment'])

        # Verify imported store
        signers_set = {role: set(self.policy['signers'][role]) for role in ['primary', 'dna']}
        imported_store = CheckpointStore(import_store_dir, self.expected, signers_set)
        current = imported_store.current(allow_bootstrap=True)
        self.assertEqual(current.manifest['snapshot_hash'], self.manifest1['snapshot_hash'])

        # Verify materialized SQLite databases
        for role, chain in self.chains.items():
            chain_db_path = materialize_dir / role / 'chain.db'
            self.assertTrue(chain_db_path.is_file())
            with sqlite3.connect(chain_db_path) as db:
                self.assertEqual(
                    db.execute('SELECT height,hash FROM blocks ORDER BY height').fetchall(),
                    [(0, chain['genesis_hash']), (1, chain['block_hash'])]
                )


if __name__ == '__main__':
    unittest.main()

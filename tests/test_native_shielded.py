"""Shielded assets through real native mint, mempool, miner and recovery."""
from contextlib import closing
import json
import shlex
import sqlite3
import sys
import unittest

from test_native_integration import C
from ziokt import _runtime as r
from ziokt import shielded_wallet as w
from ziokt.protocol import ProtocolError


class NativeShieldedTests(unittest.TestCase):
    def test_mainnet_native_admission_rejects_shielded_transactions_without_state_change(self):
        sys.path.insert(0, str(C))
        try:
            from test_core import Fixture
        finally:
            sys.path.pop(0)
        f = Fixture()
        f.network_id = 'ziokt-main'
        f.setUp()
        self.addCleanup(f.doCleanups)
        for path in f.root.rglob('*'):
            if path.is_dir():
                path.chmod(0o700)

        def state():
            with closing(sqlite3.connect(f.chain)) as db:
                return (db.execute('SELECT hash FROM blocks ORDER BY height').fetchall(),
                        db.execute('SELECT hash FROM transactions ORDER BY hash').fetchall(),
                        db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'zkn_shield_%' ORDER BY name").fetchall())

        before = state()
        for kind in ('zkn_shield_deposit', 'zkn_shield_transfer', 'zkn_shield_withdraw'):
            payload = {'network_id': f.network_id}
            # Deposit requires the existing native owner, rather than the
            # anonymous fresh outer identity used by transfers and withdrawals.
            private = (f.etc / 'identity.key').read_bytes() if kind == 'zkn_shield_deposit' else None
            tx = w.sign_transaction(f.network_id, kind, payload, private)
            with self.subTest(kind=kind), self.assertRaises(ProtocolError) as error:
                r.asset_submit_gift(f.root, f.network_id, tx, kind)
            self.assertEqual(error.exception.code, 'PRIVACY_REJECTED')
            self.assertEqual(state(), before)
        with closing(sqlite3.connect(':memory:')) as db:
            status = r.zs_query(db, f.network_id, 'privacy.status', {})
        self.assertFalse(status['production_shielding_enabled'])
        self.assertFalse(status['independently_audited'])

    def test_minted_asset_transfer_withdraw_and_rebuild(self):
        sys.path.insert(0, str(C))
        try:
            from test_core import Fixture
        finally:
            sys.path.pop(0)
        f = Fixture()
        f.network_id = 'test-native-shielded'
        f.core_timeout = 240
        f.setUp()
        self.addCleanup(f.doCleanups)
        for path in f.root.rglob('*'):
            if path.is_dir():
                path.chmod(0o700)
        (f.etc / 'identity.key').chmod(0o600)
        (f.etc / 'corix.conf').write_text('[ziokt]\nenabled=TRUE\nfederation_id=test\nprovider_id=corium-local\nzkn_enabled=TRUE\n')
        (f.etc / 'corix.conf').chmod(0o600)
        # Every real packed block creates a signed snapshot mint for the next
        # block; no direct fixture writes manufacture tokens or shielded notes.
        f.run_core('for i in {1..17}; do blockchain_create_transaction set_nickname \'{"nickname":"shielded-fixture"}\' >/dev/null; blockchain_mine_block >/dev/null; done')
        with closing(sqlite3.connect(f.chain)) as db:
            tokens = db.execute('SELECT token_id FROM zkn_tokens ORDER BY token_id LIMIT 16').fetchall()
        self.assertEqual(len(tokens), 16)
        notes, witnesses, keys = {}, {}, {}
        for (token,) in tokens:
            address, private = w.receiver()
            note, witness = w.note(f.network_id, token, address)
            identifier = r.zs_note_id(note)
            notes[identifier], witnesses[identifier], keys[identifier] = note, witness, private
            payload = {'version': r.ZS_VERSION, 'network_id': f.network_id,
                       'token_id': token, 'blind': witness['blind'], 'note': note}
            f.run_core('blockchain_create_transaction zkn_shield_deposit ' + shlex.quote(json.dumps(payload)) + ' >/dev/null')
        f.run_core('blockchain_mine_block >/dev/null; blockchain_mine_block >/dev/null')
        with closing(sqlite3.connect(f.chain)) as db:
            anchor = db.execute('SELECT hash FROM blocks ORDER BY height DESC LIMIT 1 OFFSET 1').fetchone()[0]
            self.assertEqual(db.execute('SELECT COUNT(*) FROM zkn_shield_notes').fetchone()[0], 16)
        selected = sorted(notes)[7]
        address, output_keys = w.receiver()
        output, output_witness = w.note(f.network_id, witnesses[selected]['token_id'], address)
        value = w.transfer(f.network_id, notes, anchor, selected, witnesses[selected], keys[selected], output, output_witness)
        tx = w.sign_transaction(f.network_id, 'zkn_shield_transfer', value)
        result = r.asset_submit_gift(f.root, f.network_id, tx, 'zkn_shield_transfer')
        self.assertEqual(result['phase'], 'pending-native-consensus')
        # A different native signer cannot spend the same note twice, including
        # while its first spend is still only in the mempool.
        duplicate = w.sign_transaction(f.network_id, 'zkn_shield_transfer', value)
        with self.assertRaises(ProtocolError):
            r.asset_submit_gift(f.root, f.network_id, duplicate, 'zkn_shield_transfer')
        f.run_core('blockchain_mine_block >/dev/null; blockchain_mine_block >/dev/null')
        with self.assertRaises(ProtocolError):
            r.asset_submit_gift(f.root, f.network_id, duplicate, 'zkn_shield_transfer')
        output_id = r.zs_note_id(output)
        ring = dict(notes)
        del ring[sorted(ring)[0]]
        ring[output_id] = output
        with closing(sqlite3.connect(f.chain)) as db:
            anchor = db.execute('SELECT hash FROM blocks ORDER BY height DESC LIMIT 1 OFFSET 1').fetchone()[0]
        withdrawal = w.withdraw(f.network_id, ring, anchor, output_id, output_witness, output_keys, '7' * 64)
        r.asset_submit_gift(f.root, f.network_id, w.sign_transaction(f.network_id, 'zkn_shield_withdraw', withdrawal), 'zkn_shield_withdraw')
        f.run_core('blockchain_mine_block >/dev/null')

        def state():
            with closing(sqlite3.connect(f.chain)) as db:
                return (db.execute('SELECT note_id,public_key,commitment,ciphertext,height FROM zkn_shield_notes ORDER BY note_id').fetchall(),
                        db.execute('SELECT image,height,transaction_hash FROM zkn_shield_images ORDER BY image').fetchall(),
                        db.execute('SELECT owner FROM zkn_tokens WHERE token_id=?', (output_witness['token_id'],)).fetchone())

        confirmed = state()
        self.assertEqual(len(confirmed[0]), 17)
        self.assertEqual(len(confirmed[1]), 2)
        self.assertEqual(confirmed[2], ('7' * 64,))
        f.run_core('_internal_rebuild_derived_state')
        self.assertEqual(state(), confirmed)


if __name__ == '__main__':
    unittest.main()

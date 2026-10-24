"""Local encrypted receiver recovery, canonical snapshots and secret-free output."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_shielded_ownership as shielded
from ziokt import _runtime as r
from ziokt import shielded_wallet as w


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = shielded.ShieldedTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        temporary = tempfile.TemporaryDirectory(prefix='ziokt-wallet-recovery-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.chain = self.root/'var/lib/corix/networks'/self.f.network/'blockchain/chain.db'
        self.chain.parent.mkdir(parents=True, mode=0o700)
        for path in self.root.rglob('*'):
            if path.is_dir(): path.chmod(0o700)
        self.backup()
        self.wallet = {'network_id': self.f.network, 'keys': self.f.private,
                       'address': w.address_from_keys(self.f.private)}
        self.password = b'locally-held-recovery-password'

    def backup(self):
        with closing(sqlite3.connect(self.chain)) as db:
            self.f.db.backup(db)
        self.chain.chmod(0o600)

    def test_recovery_rejects_future_spend_and_malformed_canonical_anchor(self):
        recovered=w.recover_wallet(self.root,self.wallet)
        image=recovered['recovery']['notes'][0]['key_image']
        with closing(sqlite3.connect(self.chain)) as db,db:
            db.execute('INSERT INTO zkn_shield_images VALUES(?,?,?)',(image,999,'d'*64))
        before=hashlib.sha256(self.chain.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'spend height'):w.recover_wallet(self.root,self.wallet)
        self.assertEqual(hashlib.sha256(self.chain.read_bytes()).hexdigest(),before)
        with closing(sqlite3.connect(self.chain)) as db,db:
            db.execute('DELETE FROM zkn_shield_images')
            db.execute("UPDATE blocks SET hash='malformed' WHERE height=(SELECT max(height) FROM blocks)")
        with self.assertRaises(ValueError):w.recover_wallet(self.root,self.wallet)

    def test_local_recovery_finds_note_and_spend_without_changing_chain(self):
        before = hashlib.sha256(self.chain.read_bytes()).hexdigest()
        value = w.recover_wallet(self.root, self.wallet)
        notes = value['recovery']['notes']
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['witness'], self.f.input)
        self.assertEqual(notes[0]['note_id'], self.f.identifier)
        self.assertFalse(notes[0]['spent'])
        self.assertEqual(hashlib.sha256(self.chain.read_bytes()).hexdigest(), before)
        original = self.root/'canonical-before.db'
        shutil.copyfile(self.chain, original)
        self.f.apply('zkn_shield_transfer', self.f.value)
        self.backup()
        spent = w.recover_wallet(self.root, value)
        self.assertTrue(spent['recovery']['notes'][0]['spent'])
        # Recompute from the replacement canonical snapshot rather than trusting
        # an encrypted but stale "spent" flag from a previously observed fork.
        shutil.copyfile(original, self.chain)
        restored = w.recover_wallet(self.root, spent)
        self.assertFalse(restored['recovery']['notes'][0]['spent'])

    def test_invalid_backup_receiver_network_and_note_are_rejected(self):
        other = copy.deepcopy(self.wallet)
        other['address'] = w.receiver()[0]
        with self.assertRaisesRegex(ValueError, 'disagree'):
            w.recover_wallet(self.root, other)
        other = dict(self.wallet, network_id='ziokt-main')
        with patch.object(r,'ZS_MAINNET_ENABLED',False), self.assertRaisesRegex(ValueError, 'enabled mainnet'):
            w.validate_wallet(other)
        with patch.object(r, 'corium_db') as database:
            for network in ('test-../../outside', 'test-'+'a'*65, 'test-\x00'):
                with self.subTest(network=network), self.assertRaises(ValueError):
                    w.recover_wallet(self.root, dict(self.wallet, network_id=network))
            database.assert_not_called()
        with closing(sqlite3.connect(self.chain)) as db, db:
            db.execute('UPDATE zkn_shield_notes SET note_id=? WHERE public_key=?',
                       ('0' * 64, self.wallet['address']['public_key']))
        with self.assertRaisesRegex(ValueError, 'inconsistent'):
            w.recover_wallet(self.root, self.wallet)

    def test_envelope_size_limits_match_encrypt_and_decrypt(self):
        boundary = ['x' * 8190] * 7 + ['y' * 8165]
        envelope = w.encrypt_wallet(boundary, self.password)
        self.assertEqual(w.decrypt_wallet(envelope, self.password), boundary)
        with self.assertRaisesRegex(ValueError, 'bounded'):
            w.encrypt_wallet(boundary + ['x'], self.password)
        envelope['ciphertext'] += 'AAAA'
        with self.assertRaisesRegex(ValueError, 'bounded'):
            w.decrypt_wallet(envelope, self.password)
        with self.assertRaises(ValueError):
            w.decrypt_wallet({}, 'plaintext-password')

    def test_recovery_cli_encrypts_output_and_does_not_print_witnesses(self):
        source, password, output = (self.root/name for name in ('wallet.json', 'password.key', 'recovered.json'))
        source.write_text(json.dumps(w.encrypt_wallet(self.wallet, self.password)))
        password.write_bytes(self.password)
        source.chmod(0o600)
        password.chmod(0o600)
        command = [sys.executable, '-m', 'ziokt.shielded_wallet', 'recover', '--wallet', str(source),
                   '--password-file', str(password), '--root', str(self.root), '--output', str(output)]
        process = subprocess.run(command, text=True, capture_output=True, timeout=15, check=True)
        self.assertEqual(json.loads(process.stdout)['unspent_notes'], 1)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        for secret in (*self.wallet['keys'].values(), self.f.input['blind'], self.f.input['token_id']):
            self.assertNotIn(secret, process.stdout + process.stderr + output.read_text())
        recovered = w.decrypt_wallet(json.loads(output.read_text()), self.password)
        self.assertEqual(recovered['recovery']['notes'][0]['witness'], self.f.input)
        repeated = subprocess.run(command, text=True, capture_output=True, timeout=15)
        self.assertNotEqual(repeated.returncode, 0)
        self.assertEqual(w.decrypt_wallet(json.loads(output.read_text()), self.password), recovered)

    def test_public_image_pages_do_not_identify_spent_notes(self):
        self.f.apply('zkn_shield_transfer', self.f.value)
        page = r.zs_query(self.f.db, self.f.network, 'zkn.shield.images', {'limit': 1})
        self.assertEqual(page['images'][0]['image'], self.f.value['proof']['image'])
        self.assertFalse(page['spent_notes_identifiable'])
        self.assertNotIn(self.f.identifier, json.dumps(page))
        self.assertEqual(r.zs_query(self.f.db, self.f.network, 'zkn.shield.images', {'cursor': page['images'][0]['image']})['images'], [])
        for limit in (0, 65, True):
            with self.assertRaises(ValueError):
                r.zs_query(self.f.db, self.f.network, 'zkn.shield.images', {'limit': limit})


if __name__ == '__main__':
    unittest.main()

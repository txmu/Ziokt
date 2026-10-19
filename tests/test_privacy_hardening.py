"""Adversarial admission and fixed-size native-crypto boundary checks."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

import test_shielded_ownership as shielded
from ziokt import _runtime as r
from ziokt import shielded_wallet as w
from ziokt.protocol import ProtocolError


class CryptoBoundaryTests(unittest.TestCase):
    def test_ffi_rejects_wrong_lengths_and_unknown_operations_before_loading_library(self):
        with patch.object(r, 'zs_lib') as library:
            for name, values in (
                ('crypto_core_ristretto255_scalar_reduce', (b'x' * 32,)),
                ('crypto_core_ristretto255_from_hash', (b'x' * 65,)),
                ('crypto_core_ristretto255_scalar_add', (b'x' * 32,)),
                ('crypto_core_ristretto255_scalar_mul', (b'x' * 32, bytearray(32))),
                ('sodium_memzero', (b'x' * 32,)),
            ):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    r.zs_op(name, *values)
            library.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'noncanonical scalar'):
            r.zs_sadd(b'\xff' * 32, bytes(32))

    def test_scalar_randomness_rejects_zero_with_bounded_retry(self):
        with patch.object(r._zs_random, 'token_bytes', return_value=bytes(64)) as random:
            with self.assertRaisesRegex(ValueError, 'randomness'):
                r.zs_random_scalar()
            self.assertEqual(random.call_count, 8)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.f = shielded.ShieldedTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.db = self.f.db
        self.db.execute('CREATE TABLE transactions(type TEXT,data TEXT,public_key TEXT,block_height INTEGER)')

    def pending(self, kind, value, public='pending-key'):
        self.db.execute('INSERT INTO transactions VALUES (?,?,?,NULL)', (kind, json.dumps(value), public))

    def check(self, kind, value, sender=None):
        return r.asset_privacy_pending(self.db, self.f.network, kind, value, sender or self.f.owner)

    def deposit(self, token, address=None):
        address = address or w.receiver()[0]
        note, witness = w.note(self.f.network, token, address)
        self.db.execute('INSERT OR IGNORE INTO zkn_tokens VALUES (?,?,0)', (token, self.f.owner))
        return {'version': r.ZS_VERSION, 'network_id': self.f.network, 'token_id': token,
                'blind': witness['blind'], 'note': note}

    def test_deposit_reserves_asset_across_transparent_and_private_paths(self):
        value = self.deposit('a' * 64)
        r.zs_validate(self.db, self.f.network, 'zkn_shield_deposit', value, self.f.owner)
        self.pending('zkn_shield_deposit', value)
        another = self.deposit(value['token_id'])
        with self.assertRaisesRegex(ProtocolError, 'pending ownership'):
            self.check('zkn_shield_deposit', another)
        with self.assertRaisesRegex(ProtocolError, 'pending ownership'):
            self.check('zkn_private_transfer', {'token_id': value['token_id']})
        self.db.execute('DELETE FROM transactions')
        self.pending('zkn_transfer', {'token_id': value['token_id']})
        with self.assertRaisesRegex(ProtocolError, 'pending ownership'):
            self.check('zkn_shield_deposit', value)

    def test_pending_one_time_keys_and_commitments_cannot_be_reused(self):
        address, _ = w.receiver()
        first = self.deposit('a' * 64, address)
        second = self.deposit('b' * 64, address)
        r.zs_validate(self.db, self.f.network, 'zkn_shield_deposit', second, self.f.owner)
        self.pending('zkn_shield_deposit', first)
        with self.assertRaisesRegex(ProtocolError, 'one-time'):
            self.check('zkn_shield_deposit', second)
        second = copy.deepcopy(first)
        second['token_id'] = 'c' * 64
        second['note']['public_key'] = w.receiver()[0]['public_key']
        with self.assertRaisesRegex(ProtocolError, 'one-time'):
            self.check('zkn_shield_deposit', second)

    def test_pending_spend_conflicts_across_transfer_and_withdraw(self):
        self.pending('zkn_shield_transfer', self.f.value)
        value = {'proof': {'image': self.f.value['proof']['image']}}
        with self.assertRaisesRegex(ProtocolError, 'nullifier'):
            self.check('zkn_shield_withdraw', value)

    def test_consensus_validation_does_not_depend_on_local_pending_contents(self):
        self.pending('zkn_shield_transfer', self.f.value)
        with self.assertRaises(ProtocolError):
            self.check('zkn_shield_transfer', self.f.value)
        r.zs_validate(self.db, self.f.network, 'zkn_shield_transfer', self.f.value, self.f.owner)

    def test_confirmed_and_pending_review_requests_share_one_quota(self):
        self.f.request()
        public = 'reviewer-public-key'
        sender = hashlib.sha256(public.encode()).hexdigest()
        body = json.loads(self.db.execute('SELECT body FROM privacy_requests').fetchone()[0])
        self.f.apply('privacy_review_request', body, sender=sender, tx='8' * 64)
        for i in range(7):
            pending = dict(body, nonce=f'{i:064x}')
            self.pending('privacy_review_request', pending, public)
        value = dict(body, nonce='7' * 64)
        with self.assertRaisesRegex(ProtocolError, 'quota'):
            self.check('privacy_review_request', value, sender)

    def test_pending_revoke_excludes_votes_and_disclosures(self):
        self.pending('privacy_review_revoke', {'request_id': '9' * 64})
        for kind in ('privacy_review_vote', 'privacy_review_disclose', 'privacy_review_revoke'):
            with self.subTest(kind=kind), self.assertRaisesRegex(ProtocolError, 'closure'):
                self.check(kind, {'request_id': '9' * 64})

    def test_repeated_disclosure_and_vote_are_reserved(self):
        public = 'voter-public'
        sender = hashlib.sha256(public.encode()).hexdigest()
        value = {'request_id': '9' * 64, 'decision': 'approve'}
        self.pending('privacy_review_vote', value, public)
        with self.assertRaisesRegex(ProtocolError, 'vote'):
            self.check('privacy_review_vote', value, sender)
        value = {'request_id': '8' * 64, 'note_id': self.f.identifier}
        self.pending('privacy_review_disclose', value)
        with self.assertRaisesRegex(ProtocolError, 'disclosure'):
            self.check('privacy_review_disclose', value)

    def test_unusable_electorate_is_rejected_before_submission(self):
        self.f.request()
        body = json.loads(self.db.execute('SELECT body FROM privacy_requests').fetchone()[0])
        body['nonce'] = '7' * 64
        self.db.execute('UPDATE validators SET stake=0')
        with self.assertRaisesRegex(ValueError, 'electorate'):
            r.zs_validate(self.db, self.f.network, 'privacy_review_request', body, self.f.owner)

    def test_all_ring_sizes_verify_and_bind_the_ciphertext(self):
        notes = dict(self.f.notes)
        for i in range(16, 64):
            token = hashlib.sha256(('extended-ring-' + str(i)).encode()).hexdigest()
            address, _ = w.receiver()
            note, witness = w.note(self.f.network, token, address)
            self.db.execute('INSERT INTO zkn_tokens VALUES (?,?,0)', (token, self.f.owner))
            value = {'version': r.ZS_VERSION, 'network_id': self.f.network, 'token_id': token,
                     'blind': witness['blind'], 'note': note}
            r.zs_apply(self.db, self.f.network, 'zkn_shield_deposit', value, self.f.owner, f'{i:064x}', 1)
            notes[r.zs_note_id(note)] = note
        for size in (16, 32, 64):
            ring = dict(self.f.notes)
            ring.update(list((k, n) for k, n in notes.items() if k not in ring)[:size-16])
            value = w.transfer(self.f.network, ring, self.f.anchor, self.f.identifier,
                               self.f.input, self.f.private, self.f.output, self.f.output_witness)
            with self.subTest(size=size):
                r.zs_validate(self.db, self.f.network, 'zkn_shield_transfer', value, self.f.owner)
                value = copy.deepcopy(value)
                value['note']['ciphertext'] = self.f.notes[self.f.identifier]['ciphertext']
                with self.assertRaises(ValueError):
                    r.zs_validate(self.db, self.f.network, 'zkn_shield_transfer', value, self.f.owner)


if __name__ == '__main__':
    unittest.main()

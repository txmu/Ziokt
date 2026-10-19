"""Shielded assets through real native mint, mempool, miner and recovery."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
import shlex
import sqlite3
import sys
import unittest

from test_native_integration import C
from ziokt import _runtime as r
from ziokt import shielded_wallet as w
from ziokt.protocol import ProtocolError
from ziokt.config import fingerprint
from ziokt.mcp import Service, McpError


class NativeShieldedTests(unittest.TestCase):
    def fixture(self, network):
        sys.path.insert(0, str(C))
        try:
            from test_core import Fixture
        finally:
            sys.path.pop(0)
        f = Fixture()
        f.network_id = network
        f.core_timeout = 240
        f.setUp()
        self.addCleanup(f.doCleanups)
        for path in f.root.rglob('*'):
            if path.is_dir():
                path.chmod(0o700)
        (f.etc / 'identity.key').chmod(0o600)
        return f

    def test_mainnet_native_admission_rejects_shielded_transactions_without_state_change(self):
        f = self.fixture('ziokt-main')

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
        f.run_core('blockchain_create_transaction zkn_shield_transfer ' +
                   shlex.quote(json.dumps({'network_id': f.network_id})), ok=False)
        self.assertEqual(state(), before)

    def test_minted_asset_transfer_withdraw_and_rebuild(self):
        f = self.fixture('test-native-shielded')
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
            if len(notes) == 1:
                alternate_note, alternate_witness = w.note(f.network_id, token, w.receiver()[0])
                duplicate = dict(payload, blind=alternate_witness['blind'], note=alternate_note)
                f.run_core('blockchain_create_transaction zkn_shield_deposit ' + shlex.quote(json.dumps(duplicate)), ok=False)
                f.run_core('blockchain_create_transaction zkn_transfer ' + shlex.quote(json.dumps({'token_id': token, 'recipient': '7' * 64, 'nonce': 1})), ok=False)
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
        provider = {'native_project': 'corium', 'provider_id': 'corium-local', 'root': str(C),
                    'native_config': str(f.etc/'corix.conf'), 'entrypoint_digest': fingerprint(C/'corix_v108.sh'),
                    'network_id': f.network_id, 'state_root': str(f.root)}
        federation, admin = f.root/'federation.json', f.root/'admin.key'
        federation.write_text(json.dumps({'schema': 'ziokt.federation.v1', 'enabled': True,
                                          'federation_id': 'test', 'providers': [provider]}))
        admin.write_text('a' * 64)
        federation.chmod(0o600)
        admin.chmod(0o600)
        service = Service({'schema': 'ziokt.mcp.v1', 'issuer': 'https://privacy.test',
                           'origins': ['https://privacy.test'], 'state': str(f.root/'mcp-state'),
                           'admin_token': str(admin), 'bridges': {}, 'federation': str(federation),
                           'clients': {'reader': {'redirect_uris': ['https://privacy.test/callback'], 'scopes': ['corium:read']}}})
        token = service.issue('reader', {'corium:read'})
        principal = service.auth('Bearer ' + token['access_token'])
        tool = 'corium_local_zkn_shield_images'
        self.assertFalse(service.tools[tool]['annotations']['destructiveHint'])
        with self.assertRaises(McpError):
            service.call(dict(principal, scopes={'ziokt:read'}), tool, {'params': {}})
        first = service.call(principal, tool, {'params': {'limit': 1}})['structuredContent']
        second = service.call(principal, tool, {'params': {'limit': 1, 'cursor': first['next_cursor']}})['structuredContent']
        self.assertEqual(len(first['images']) + len(second['images']), 2)
        self.assertIsNone(second['next_cursor'])
        with self.assertRaises(ValueError):
            service.call(principal, tool, {'params': {'limit': 65}})

    def test_cli_and_concurrent_native_plans_share_review_quota(self):
        f = self.fixture('default')
        body = {'network_id': 'default', 'case_commitment': 'd' * 64,
                'legal_basis_commitment': 'e' * 64, 'recipient_key': 'f' * 64,
                'scope': ['a' * 64], 'expires_height': 100, 'nonce': '0' * 64}
        for i in range(7):
            payload = dict(body, nonce=f'{i:064x}')
            f.run_core('blockchain_create_transaction privacy_review_request ' + shlex.quote(json.dumps(payload)) + ' >/dev/null')
        private = (f.etc / 'identity.key').read_bytes()

        def submit(i):
            tx = w.sign_transaction('default', 'privacy_review_request', dict(body, nonce=f'{i:064x}'), private)
            try:
                return r.asset_submit_gift(f.root, 'default', tx, 'privacy_review_request')['phase']
            except ProtocolError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, (7, 8)))
        self.assertCountEqual(outcomes, ['pending-native-consensus', 'PRIVACY_CONFLICT'])
        f.run_core('blockchain_create_transaction privacy_review_request ' +
                   shlex.quote(json.dumps(dict(body, nonce='9' * 64))), ok=False)
        with closing(sqlite3.connect(f.chain)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM transactions WHERE type='privacy_review_request' AND block_height IS NULL").fetchone()[0], 8)
        f.run_core('blockchain_mine_block >/dev/null')
        with closing(sqlite3.connect(f.chain)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM privacy_requests').fetchone()[0], 8)


if __name__ == '__main__':
    unittest.main()

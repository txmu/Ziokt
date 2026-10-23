"""Actual Ristretto proofs, state transitions, reorgs and no-backdoor reviews."""
import base64
import copy
import hashlib
import json
import sqlite3
import unittest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization
from ziokt import _runtime as r
from ziokt import shielded_wallet as w


class ShieldedTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE blocks(height INTEGER,hash TEXT); CREATE TABLE zkn_tokens(token_id TEXT PRIMARY KEY,owner TEXT,nonce INTEGER); CREATE TABLE validators(public_key_hash TEXT,stake INTEGER,status TEXT);')
        self.network='test-privacy';self.owner='a'*64;self.anchor='b'*64
        self.db.executemany('INSERT INTO blocks VALUES (?,?)',[(1,self.anchor),(2,'c'*64)])
        self.db.executemany('INSERT INTO validators VALUES (?,100,\'active\')',[(str(i)*64,) for i in range(1,5)])
        r.zs_tables(self.db);self.notes={};self.keys={};self.witness={}
        for i in range(16):
            token=hashlib.sha256(str(i).encode()).hexdigest();address,keys=w.receiver();note,witness=w.note(self.network,token,address)
            self.db.execute('INSERT INTO zkn_tokens VALUES (?,?,0)',(token,self.owner))
            value={'version':r.ZS_VERSION,'network_id':self.network,'token_id':token,'blind':witness['blind'],'note':note}
            r.zs_apply(self.db,self.network,'zkn_shield_deposit',value,self.owner,hashlib.sha256(('deposit'+str(i)).encode()).hexdigest(),1)
            identifier=r.zs_note_id(note);self.notes[identifier]=note;self.keys[identifier]=keys;self.witness[identifier]=witness
        self.identifier=sorted(self.notes)[7];self.input=self.witness[self.identifier];self.private=self.keys[self.identifier]
        address,self.output_keys=w.receiver();self.output,self.output_witness=w.note(self.network,self.input['token_id'],address)
        self.value=w.transfer(self.network,self.notes,self.anchor,self.identifier,self.input,self.private,self.output,self.output_witness)
        self.db.commit()

    def apply(self,kind,value,sender=None,tx=None,height=2):
        with self.db:r.zs_apply(self.db,self.network,kind,value,sender or self.owner,tx or hashlib.sha256(r.zs_json(value)).hexdigest(),height)

    def request(self):
        self.reviewer=X25519PrivateKey.generate();key=self.reviewer.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
        request={'network_id':self.network,'case_commitment':'d'*64,'legal_basis_commitment':'e'*64,'recipient_key':key,'scope':[self.identifier],'expires_height':30,'nonce':'f'*64}
        self.apply('privacy_review_request',request,tx='9'*64)
        return request

    def approve(self):
        for voter in ('1','2','3'):self.apply('privacy_review_vote',{'network_id':self.network,'request_id':'9'*64,'decision':'approve'},sender=voter*64)

    def test_real_transfer_ciphertext_and_double_spend(self):
        decoded=w.open_note(self.network,self.output,self.output_keys);self.assertEqual(decoded,self.output_witness)
        self.assertEqual(len(base64.b64decode(self.output['ciphertext'])),2048)
        with self.assertRaises((InvalidTag,ValueError)):w.open_note(self.network,self.output,self.private)
        raw=json.dumps(self.value)
        self.assertNotIn(self.input['token_id'],raw);self.assertNotIn(self.input['blind'],raw);self.assertNotIn(self.private['spend_key'],raw)
        self.assertNotIn('recipient',self.value);self.assertNotIn('token_id',self.value)
        self.apply('zkn_shield_transfer',self.value)
        with self.assertRaisesRegex(ValueError,'double spend'):self.apply('zkn_shield_transfer',self.value)
        # Another valid proof by the same secret has exactly the same nullifier.
        other=w.transfer(self.network,self.notes,self.anchor,self.identifier,self.input,self.private,self.output,self.output_witness)
        self.assertEqual(other['proof']['image'],self.value['proof']['image'])
        self.assertNotEqual(other['proof']['challenge'],self.value['proof']['challenge'])

    def test_transfer_then_withdraw_preserves_exact_asset(self):
        self.apply('zkn_shield_transfer',self.value,tx='4'*64)
        identifier=r.zs_note_id(self.output);ring=dict(self.notes);ring.pop(sorted(ring)[0]);ring[identifier]=self.output
        self.db.execute('INSERT INTO blocks VALUES (3,?)',('a'*64,));self.db.commit()
        value=w.withdraw(self.network,ring,'c'*64,identifier,self.output_witness,self.output_keys,'7'*64)
        self.apply('zkn_shield_withdraw',value,tx='6'*64,height=3)
        self.assertEqual(self.db.execute('SELECT owner FROM zkn_tokens WHERE token_id=?',(self.input['token_id'],)).fetchone()[0],'7'*64)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM zkn_shield_images').fetchone()[0],2)

    def test_native_relayer_signature_uses_fresh_identity_and_wallet_is_encrypted(self):
        tx=w.sign_transaction(self.network,'zkn_shield_transfer',self.value)
        r.asset_signed_gift(tx,self.network,'zkn_shield_transfer')
        other=w.sign_transaction(self.network,'zkn_shield_transfer',self.value)
        self.assertNotEqual(tx['public_key'],other['public_key'])
        envelope=w.encrypt_wallet(self.private,b'wallet-password-test-strong')
        self.assertNotIn(self.private['spend_key'],json.dumps(envelope))
        self.assertEqual(w.decrypt_wallet(envelope,b'wallet-password-test-strong'),self.private)
        with self.assertRaises(InvalidTag):w.decrypt_wallet(envelope,b'wrong-wallet-password-strong')

    def test_forged_proofs_asset_substitution_and_network_replay(self):
        for mutate in ('network','ciphertext','scalar','recipient_key','image','duplicate_ring','unknown_note','anchor'):
            value=copy.deepcopy(self.value)
            if mutate=='network':value['network_id']='test-other'
            elif mutate=='ciphertext':value['note']['ciphertext']=base64.b64encode(bytes(2048)).decode()
            elif mutate=='scalar':value['proof']['responses'][0][0]='ff'*32
            elif mutate=='recipient_key':value['note']['public_key']=r.zs_base(r.zs_random_scalar()).hex()
            elif mutate=='image':value['proof']['image']='00'*32
            elif mutate=='duplicate_ring':value['ring'][0]=value['ring'][1]
            elif mutate=='unknown_note':value['ring'][0]='0'*64;value['ring'].sort()
            else:value['anchor']='0'*64
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):self.apply('zkn_shield_transfer',value)
        address,_=w.receiver();note,witness=w.note(self.network,'0'*64,address)
        with self.assertRaisesRegex(ValueError,'asset/network'):w.transfer(self.network,self.notes,self.anchor,self.identifier,self.input,self.private,note,witness)
        # Even bypassing wallet checks cannot prove a different committed asset.
        with self.assertRaisesRegex(ValueError,'conservation witness'):
            r.zs_ring_sign(self.network,{},[self.notes[i] for i in sorted(self.notes)],note['commitment'],7,r.zs_scalar(self.private['spend_key']),r.zs_ssub(r.zs_scalar(self.input['blind']),r.zs_scalar(witness['blind'])))

    def test_reorg_removes_nullifier_and_invalidates_orphan_anchor(self):
        self.db.execute('SAVEPOINT fork');r.zs_apply(self.db,self.network,'zkn_shield_transfer',self.value,self.owner,'8'*64,3)
        self.db.execute('ROLLBACK TO fork');self.db.execute('RELEASE fork')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM zkn_shield_images').fetchone()[0],0)
        self.apply('zkn_shield_transfer',self.value)
        self.db.execute('DELETE FROM blocks WHERE hash=?',(self.anchor,))
        with self.assertRaisesRegex(ValueError,'anchor'):r.zs_validate(self.db,self.network,'zkn_shield_transfer',self.value,self.owner)

    def test_cross_network_and_unknown_versions_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'version/network'):r.zs_validate(self.db,'ziokt-main','zkn_shield_transfer',self.value,self.owner)
        value=copy.deepcopy(self.value);value['version']='future'
        with self.assertRaisesRegex(ValueError,'version'):self.apply('zkn_shield_transfer',value)

    def test_supermajority_cannot_decrypt_or_forge_holder_consent(self):
        request=self.request()
        with self.assertRaises(ValueError):w.disclosure(self.network,'9'*64,request,self.identifier,self.input,self.private,approved=False)
        for voter in ('1','2'):self.apply('privacy_review_vote',{'network_id':self.network,'request_id':'9'*64,'decision':'approve'},sender=voter*64)
        self.assertFalse(r.zs_review_status(self.db,'9'*64)['approved'])
        disclosure=w.disclosure(self.network,'9'*64,request,self.identifier,self.input,self.private,approved=True)
        with self.assertRaisesRegex(ValueError,'supermajority'):self.apply('privacy_review_disclose',disclosure)
        self.apply('privacy_review_vote',{'network_id':self.network,'request_id':'9'*64,'decision':'approve'},sender='3'*64)
        status=r.zs_review_status(self.db,'9'*64);self.assertTrue(status['approved']);self.assertFalse(status['automatic_decryption'])
        forged=copy.deepcopy(disclosure);forged['authorization']=r.zs_schnorr_sign(r.zs_random_scalar(),{k:v for k,v in forged.items() if k!='authorization'},self.network)
        with self.assertRaisesRegex(ValueError,'holder'):self.apply('privacy_review_disclose',forged)
        self.apply('privacy_review_disclose',disclosure)
        private=self.reviewer.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()).hex()
        self.assertEqual(w.open_disclosure(self.network,disclosure,private)['witness'],self.input)
        with self.assertRaises(InvalidTag):w.open_disclosure(self.network,disclosure,X25519PrivateKey.generate().private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()).hex())
        # Administrative/native identity alone has no wallet secret.
        self.assertNotIn('spend_key',json.dumps(r.zs_query(self.db,self.network,'privacy.review.get',{'network_id':self.network,'request_id':'9'*64})))

    def test_electorate_freeze_scope_replay_revocation_and_expiration(self):
        request=self.request();self.db.execute("INSERT INTO validators VALUES (?,10000,'active')",('6'*64,));self.db.commit()
        with self.assertRaisesRegex(ValueError,'electorate'):self.apply('privacy_review_vote',{'network_id':self.network,'request_id':'9'*64,'decision':'approve'},sender='6'*64)
        self.approve()
        with self.assertRaisesRegex(ValueError,'already cast'):self.apply('privacy_review_vote',{'network_id':self.network,'request_id':'9'*64,'decision':'approve'},sender='1'*64)
        proof=w.disclosure(self.network,'9'*64,request,self.identifier,self.input,self.private,approved=True)
        outside=copy.deepcopy(proof);outside['note_id']='7'*64
        with self.assertRaisesRegex(ValueError,'scope'):self.apply('privacy_review_disclose',outside)
        self.apply('privacy_review_revoke',{'network_id':self.network,'request_id':'9'*64})
        self.assertTrue(r.zs_review_status(self.db,'9'*64)['revoked'])
        with self.assertRaisesRegex(ValueError,'inactive'):self.apply('privacy_review_disclose',proof)
        self.db.execute('INSERT INTO blocks VALUES (31,?)',('5'*64,))
        self.assertTrue(r.zs_review_status(self.db,'9'*64)['expired'])


if __name__=='__main__':unittest.main()

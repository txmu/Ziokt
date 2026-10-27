"""Real member signatures and shielded ring proofs through the shared engine."""
import copy
import hashlib
import json
import unittest
from cryptography.hazmat.primitives.asymmetric import ec
from ziokt import _runtime as r
from ziokt.protocol import ProtocolError
import test_shielded_ownership as fixtures


class CooperativeAssetTests(unittest.TestCase):
    def setUp(self):
        fixtures.ShieldedTests.setUp(self)
        self.db.execute("ALTER TABLE blocks ADD COLUMN transactions TEXT DEFAULT '[]'")
        self.db.execute('INSERT INTO blocks(height,hash) VALUES(0,?)',('d'*64,))
        self.db.execute('CREATE TABLE transactions(hash TEXT PRIMARY KEY,type TEXT,data TEXT,block_height INTEGER)')
        self.keys=[ec.generate_private_key(ec.SECP256K1()) for _ in range(3)]
        self.cc=r._native_cooperative_consensus;self.coop=r._native_cooperative
        state=self.cc.state_at(self.db,self.network,1)
        command={'schema':'corium.cooperative-command.v1','chain':state['chain'],'cooperative':'workers',
                 'sequence':1,'previous_state':self.coop.state_root(state),'action':'create',
                 'arguments':{'members':[r._native_dna.public_key(k) for k in self.keys]}}
        envelope={'command':command,'endorsements':[self.coop.endorse(command,k) for k in self.keys]}
        self.db.execute('INSERT INTO transactions VALUES(?,?,?,1)',('e'*64,'cooperative_command',json.dumps(envelope)))
        self.db.execute('UPDATE blocks SET transactions=? WHERE height=1',(json.dumps(['e'*64]),))
        self.cc.apply_command(self.db,self.network,envelope,1,True)
        self.account=self.cc.account(state['chain'],'workers')
        for note in self.notes:
            self.db.execute('INSERT INTO cooperative_note_controls VALUES(?,?)',(note,'workers'))
        self.db.commit()

    def authorized(self,kind,payload,count=3,height=3):
        command=self.cc.asset_command(self.db,self.network,kind,payload,'workers',height)
        return {**copy.deepcopy(payload),'cooperative_authorization':{'command':command,
                  'endorsements':[self.cc.asset_endorse(command,k) for k in self.keys[:count]]}}

    def test_transparent_custody_requires_current_quorum_and_nonce_survives_restart(self):
        token='1'*64
        self.db.execute('INSERT INTO zkn_tokens VALUES(?,?,0)',(token,self.account))
        plain={'token_id':token,'recipient':'2'*64,'nonce':1}
        for payload in (plain,self.authorized('zkn_transfer',plain,2)):
            with self.assertRaises(ProtocolError):r.asset_validate(self.db,self.network,'zkn_transfer',payload,self.owner,3)
        payload=self.authorized('zkn_transfer',plain)
        self.db.execute('SAVEPOINT branch')
        r.asset_apply(self.db,self.network,'3'*64,'zkn_transfer',payload,self.owner,3)
        root=self.cc.asset_state_root(self.db)
        self.assertEqual(self.db.execute('SELECT owner FROM zkn_tokens WHERE token_id=?',(token,)).fetchone()[0],'2'*64)
        with self.assertRaises(ProtocolError):r.asset_validate(self.db,self.network,'zkn_transfer',payload,self.owner,3)
        self.db.execute('ROLLBACK TO branch');self.db.execute('RELEASE branch')
        r.asset_apply(self.db,self.network,'3'*64,'zkn_transfer',payload,self.owner,3)
        self.assertEqual(self.cc.asset_state_root(self.db),root)
        self.assertEqual(self.cc.next_nonce(self.db,'workers'),2)

    def test_controlled_shielded_ring_cannot_drop_quorum_or_mix_domains(self):
        with self.assertRaises(ProtocolError):r.asset_validate(self.db,self.network,'zkn_shield_transfer',self.value,self.owner,3)
        payload=self.authorized('zkn_shield_transfer',self.value)
        changed=copy.deepcopy(payload);changed['note']['ciphertext']='A'*2732
        with self.assertRaises(ProtocolError):r.asset_validate(self.db,self.network,'zkn_shield_transfer',changed,self.owner,3)
        note=next(iter(self.notes));self.db.execute('DELETE FROM cooperative_note_controls WHERE note_id=?',(note,))
        with self.assertRaises(ProtocolError):r.asset_validate(self.db,self.network,'zkn_shield_transfer',payload,self.owner,3)
        self.db.execute('INSERT INTO cooperative_note_controls VALUES(?,?)',(note,'workers'))
        r.asset_apply(self.db,self.network,'4'*64,'zkn_shield_transfer',payload,self.owner,3)
        output=r.zs_note_id(self.output)
        self.assertEqual(self.db.execute('SELECT cooperative FROM cooperative_note_controls WHERE note_id=?',(output,)).fetchone()[0],'workers')
        self.assertEqual(self.db.execute('SELECT count(*) FROM zkn_shield_images').fetchone()[0],1)

    def test_collectible_issue_and_transfer_share_the_same_authority(self):
        r.asset_tables(self.db)
        token='5'*64;self.db.execute('INSERT INTO zkn_tokens VALUES(?,?,0)',(token,self.account))
        issue={'network_id':self.network,'token_id':token,'kind':'unique','serial':'1','contents_digest':'sha256:'+'6'*64}
        r.asset_apply(self.db,self.network,'7'*64,'zkc_issue',self.authorized('zkc_issue',issue),self.owner,3)
        edition=r.zkc_edition_id(issue)
        self.assertEqual(r.asset_edition_owner(self.db,edition)[0],self.account)
        transfer={'network_id':self.network,'edition_id':edition,'recipient':'8'*64,'nonce':1}
        with self.assertRaises(ProtocolError):r.asset_validate(self.db,self.network,'zkc_transfer',transfer,self.owner,3)
        r.asset_apply(self.db,self.network,'9'*64,'zkc_transfer',self.authorized('zkc_transfer',transfer),self.owner,3)
        self.assertEqual(tuple(r.asset_edition_owner(self.db,edition)),('8'*64,1))


if __name__=='__main__':unittest.main()

"""Actual DHT persistence, native durable journal and canonical block inclusion."""
import hashlib,json,sys,sqlite3,unittest
from pathlib import Path
from ziokt.protocol_publisher import Publisher
from ziokt.protocol_state import ProtocolState
from ziokt.dna_protocol import public_key_pem
from ziokt.config import fingerprint
import test_native_naming as fixture_module
from test_native_integration import C


@unittest.skipUnless(C.exists(),'Corium source checkout required')
class PublicationTests(unittest.TestCase):
    def setUp(self):
        fixture_module.NativeNamingTests.setUp(self)
        fixture=self.fixture
        config=fixture.etc/'corix.conf'
        config.write_text(config.read_text().replace('identity.register,naming.submit,chain.mine','identity.register,naming.submit,content.publish,chain.mine'))
        gateway=fixture.root/'gateway.json'
        gateway.write_text(json.dumps({'corix':str(C/'corix_v108.sh'),'corix_digest':fingerprint(C/'corix_v108.sh'),'state_root':str(fixture.root),'network':'default'}));gateway.chmod(0o600)
        federation=fixture.root/'federation.json'
        federation.write_text(json.dumps({'schema':'ziokt.federation.v1','enabled':True,'federation_id':'test','providers':[self.client.provider]}));federation.chmod(0o600)
        self.settings={'gateway':str(gateway),'federation':str(federation)}
        self.state=ProtocolState(fixture.root/'publications',{'signing_key':str(fixture.etc/'identity.key'),'owners':{'corium':fixture.identity},'publish':True})
        self.publisher=Publisher(self.state.root,self.settings)

    def test_native_nns_registration_retry_is_one_transaction_and_requires_inclusion(self):
        doc=self.state.announce('corium','root:actual',owner='alice')
        self.state.flush(self.publisher)
        status=self.state.publication('alice',doc['publication_id'])
        self.assertEqual(status['broadcast'],'pending')
        self.assertEqual(status['chain_registration'],'submitted')
        with sqlite3.connect(self.fixture.chain) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM transactions WHERE type='nns_update'").fetchone()[0],1)
        raw={'frame':doc['frame'],'pem':doc['pem'],'sender':doc['sender'],'chain_id':doc['chain_id'],'policy_id':doc['policy_id'],'record':doc['record']}
        again=self.publisher.publish(doc['publication_id'],'zdns',raw)
        self.assertEqual(again['native_transaction'],status['native_transaction'])
        with sqlite3.connect(self.fixture.chain) as db:self.assertEqual(db.execute("SELECT count(*) FROM transactions WHERE type='nns_update'").fetchone()[0],1)
        self.fixture.run_core('blockchain_mine_block')
        included=self.publisher.inclusion(status['native_transaction'])
        self.assertEqual(included['chain_registration'],'confirmed')
        self.assertIsNotNone(included['inclusion']['block_hash'])
        self.assertFalse(included['consensus_reward_claimed'])

    def test_public_evidence_anchor_excludes_private_result_and_is_native_content(self):
        doc=self.state.commit('alice','pipeline','task','worker','a'*64,{'private_detail':'keep-local'},publish=True)
        with self.state.transaction() as db:raw=db.execute('SELECT document FROM publications WHERE id=?',(doc['publication_id'],)).fetchone()[0]
        self.assertNotIn('keep-local',raw)
        self.state.flush(self.publisher)
        status=self.state.publication('alice',doc['publication_id'])
        self.assertEqual(status['chain_registration'],'submitted')
        self.fixture.run_core('blockchain_mine_block')
        self.assertEqual(self.publisher.inclusion(status['native_transaction'])['chain_registration'],'confirmed')
        with sqlite3.connect(self.fixture.chain) as db:payload=db.execute("SELECT data FROM transactions WHERE type='ziokt_content'").fetchone()[0]
        self.assertNotIn('keep-local',payload)

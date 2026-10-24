"""Real opaque socket forwarding, independent signatures and native ZKT ledger."""
from contextlib import closing
import copy,json,hashlib,socket,sqlite3,tempfile,time,unittest
from pathlib import Path
from ziokt.relay_rewards import RelayRewards,DOMAIN
from ziokt.relay_stream import RelayHalf
from ziokt.security import sign
from ziokt._zkt_runtime import DEFAULT_REPUTATION_POLICY
from ziokt.protocol import ProtocolError


class RelayRewardTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.ledger=self.root/'native.db'
        with sqlite3.connect(self.ledger) as db:db.execute('CREATE TABLE blocks(height INTEGER,hash TEXT)');db.execute('INSERT INTO blocks VALUES(0,?)',('f'*64,))
        self.keys={'source':bytes(range(32)),'destination':bytes(range(1,33))}
        policy=copy.deepcopy(DEFAULT_REPUTATION_POLICY);policy['network_id']='test-relay';policy['application_services']['network_relay']=3
        path=self.root/'policy.json';path.write_text(json.dumps(policy));path.chmod(0o600)
        self.config={'root':str(self.root/'accounting'),'ledger':str(self.ledger),'network':'test-relay','beneficiary':'a'*64,'policy_file':str(path),
                     'peers':{name:{'public_key':sign({},key,'key')['public_key'],'native_peer_id':str(i+2)*64,'failure_domain':'domain'+str(i),'pool':'trusted' if i else 'community'} for i,(name,key) in enumerate(self.keys.items())},
                     'threshold':2,'bytes_per_unit':4096,'max_units_per_receipt':2,'max_units_per_day':2}
        self.rewards=RelayRewards(self.config,'test-relay')

    def observed(self,session='actual-random-capability'):
        a_client,a_native=socket.socketpair();b_native,b_client=socket.socketpair()
        a,b=RelayHalf(a_native),RelayHalf(b_native)
        try:
            a_client.sendall(b'a'*4096);a_client.shutdown(socket.SHUT_WR)
            b_client.sendall(b'b'*4096);b_client.shutdown(socket.SHUT_WR)
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                for source,destination in ((a,b),(b,a)):
                    value=source.read()
                    if value['state']=='frame':destination.write(value['frame']);source.acknowledge(value['frame']['sequence'])
                if a.status()['state']==b.status()['state']=='complete':break
                time.sleep(.01)
            self.assertEqual(a_client.recv(4096),b'b'*4096);self.assertEqual(b_client.recv(4096),b'a'*4096)
            return self.rewards.observe(session,a.status(),b.status())
        finally:a.close();b.close();a_client.close();b_client.close()

    def witnesses(self,document):
        return [{'peer':name,'attestation':sign(document,key,DOMAIN)} for name,key in self.keys.items()]

    def test_actual_forwarding_quorum_awards_once_and_recovers_crash(self):
        observation=self.observed();self.assertEqual(observation['state'],'awaiting_peer_witnesses')
        doc=observation['receipt'];self.assertNotIn('actual-random-capability',json.dumps(doc));self.assertEqual(doc['bytes'],8192)
        witnesses=self.witnesses(doc);result=self.rewards.settle(observation['receipt_id'],witnesses)
        self.assertEqual(result['points_awarded'],6);self.assertTrue(result['peer_quorum_verified']);self.assertFalse(result['main_chain_settled']);self.assertFalse(result['token_transfer'])
        self.assertTrue(self.rewards.settle(observation['receipt_id'],witnesses)['duplicate'])
        with self.rewards.transaction() as db:db.execute("UPDATE relay_receipts SET state='settling',result=NULL")
        restarted=RelayRewards(self.config,'test-relay');self.assertEqual(restarted.settle(observation['receipt_id'],witnesses)['points_awarded'],6)
        with closing(sqlite3.connect(self.ledger)) as db:
            self.assertEqual(db.execute('SELECT total_points FROM zkt_accounts').fetchone()[0],6)
            self.assertEqual(db.execute('SELECT count(*) FROM zkt_claims').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT * FROM blocks').fetchall(),[(0,'f'*64)])

    def test_forged_replayed_or_non_independent_witnesses_and_budget_rejected(self):
        first=self.observed();doc=first['receipt'];witnesses=self.witnesses(doc)
        wrong=copy.deepcopy(witnesses);wrong[0]['attestation']['payload']['bytes']+=1
        with self.assertRaises(ProtocolError):self.rewards.settle(first['receipt_id'],wrong)
        with self.assertRaises(ProtocolError):self.rewards.settle(first['receipt_id'],[witnesses[0],witnesses[0]])
        same_domain=copy.deepcopy(self.config);same_domain['peers']['destination']['failure_domain']='domain0'
        with self.assertRaises(ProtocolError):RelayRewards(same_domain,'test-relay').settle(first['receipt_id'],witnesses)
        self.rewards.settle(first['receipt_id'],witnesses)
        second=self.observed('another-capability')
        with self.assertRaises(ProtocolError):self.rewards.settle(second['receipt_id'],witnesses)
        with self.assertRaisesRegex(ProtocolError,'daily'):self.rewards.settle(second['receipt_id'],self.witnesses(second['receipt']))
        with self.assertRaises(ProtocolError):self.rewards.settle('c'*64,witnesses)

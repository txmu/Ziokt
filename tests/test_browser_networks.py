import hashlib
from contextlib import closing,contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from ziokt import dna_protocol as dna
from ziokt.explorer_networks import ExplorerNetworks,PROTOCOL
from ziokt.p2p_explorer import P2PExplorer
from ziokt.protocol import ProtocolError,encoded
from ziokt.protocol_state import ProtocolState
from ziokt.component_links import COMPONENTS
from ziokt.networks import configuration


@contextmanager
def database(path):
    with closing(sqlite3.connect(path)) as db:
        with db:yield db


def chain(root,network,genesis):
    path=root/'var/lib/corix/networks'/network/'blockchain/chain.db';path.parent.mkdir(parents=True)
    with database(path) as db:
        db.executescript('CREATE TABLE blocks(height INTEGER PRIMARY KEY,hash TEXT,previous_hash TEXT,timestamp INTEGER,validator TEXT,total_weight INTEGER,transactions TEXT);CREATE TABLE transactions(hash TEXT,type TEXT,timestamp INTEGER,block_height INTEGER,data TEXT);CREATE TABLE validators(public_key TEXT,public_key_hash TEXT,status TEXT);CREATE TABLE onchain_identities(public_key TEXT);CREATE TABLE block_work(hash TEXT,proof TEXT);')
        db.execute('INSERT INTO blocks VALUES(0,?,?,0,?,0,?)',(genesis,'0','genesis','[]'))
    return path


class BrowserNetworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.primary=chain(self.root/'one','alpha','a'*64);self.side=chain(self.root/'two','beta','b'*64)
        self.profile={'id':'main','name':'Independent pair','protocol':PROTOCOL,
                      'primary':{'state_root':str(self.root/'one'),'network_id':'alpha','genesis_hash':'a'*64},
                      'dna':{'state_root':str(self.root/'two'),'network_id':'beta','genesis_hash':'b'*64}}
        self.view=ExplorerNetworks(self.root/'one','alpha',[self.profile])

    def test_primary_default_side_selection_and_pinned_genesis_isolation(self):
        self.assertEqual(self.view.query('/api/explorer/summary')['network_id'],'alpha')
        self.assertEqual(self.view.query('/api/explorer/summary?chain=dna')['genesis_hash'],'b'*64)
        self.assertEqual(set(self.view.query('/api/explorer/duplex')['chains']),{'primary','dna'})
        self.assertNotIn(str(self.root),json.dumps(self.view.query('/api/explorer/networks')))
        for query in ('/api/explorer/summary?network=../one','/api/explorer/summary?chain=dna&chain=primary','/api/explorer/summary?path=/etc/passwd'):
            with self.subTest(query=query),self.assertRaises(ProtocolError):self.view.query(query)
        with database(self.side) as db:db.execute('UPDATE blocks SET hash=?',('c'*64,))
        with self.assertRaises(ProtocolError):self.view.query('/api/explorer/summary?chain=dna')

    def test_actual_dna_duplex_readback_corruption_and_readonly_files(self):
        gene=dna.duplex(b'canonical block commitments')
        with database(self.side) as db:db.execute('INSERT INTO block_work VALUES(?,?)',('b'*64,json.dumps({'dna':gene})))
        before=self.side.read_bytes();view=self.view.query('/api/explorer/dna?chain=dna')
        self.assertEqual(view['encoding'],gene);self.assertTrue(view['strand_consistency_verified']);self.assertEqual(self.side.read_bytes(),before)
        self.assertEqual(self.view.query('/api/explorer/dna')['state'],'no-dna-proof')
        gene['antisense']='A'*len(gene['antisense'])
        with database(self.side) as db:db.execute('UPDATE block_work SET proof=?',(json.dumps({'dna':gene}),))
        with self.assertRaises(ProtocolError):self.view.query('/api/explorer/dna?chain=dna')

    def test_real_signed_rna_observations_bound_to_configured_domains(self):
        key=ec.generate_private_key(ec.SECP256K1());key_path=self.root/'rna.key';key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key_path.chmod(0o600)
        owner=hashlib.sha256(dna.public_key_pem(key).encode()).hexdigest()
        state=ProtocolState(self.root/'protocol',{'signing_key':str(key_path),'owners':{'book':owner},'chain_id':'1'*64,'policy_id':'2'*64})
        record=state.announce('book','private-target.example')
        self.profile['primary'].update(protocol_db=str(state.path),chain_id='1'*64,policy_id='2'*64)
        view=ExplorerNetworks(self.root/'one','alpha',[self.profile]);result=view.query('/api/explorer/rna')
        self.assertEqual(result['flows'][0]['sequence'],1);self.assertTrue(result['flows'][0]['signature_verified_at_issue_time'])
        self.assertNotIn('private-target.example',json.dumps(result));self.assertNotIn('rna',result['flows'][0])
        self.profile['primary']['chain_id']='3'*64
        self.assertEqual(ExplorerNetworks(self.root/'one','alpha',[self.profile]).query('/api/explorer/rna')['flows'],[])

    def test_zdns_and_explorer_configuration_share_both_chain_bindings(self):
        value=configuration({'schema':'ziokt.networks.v1','default':'main','networks':[self.profile]})
        self.assertEqual(value['dns']['realms']['main']['network_id'],'alpha')
        self.assertEqual(value['dns']['realms']['main-dna']['network_id'],'beta')
        self.assertEqual(len(value['observations']),2)
        duplicate=json.loads(json.dumps(self.profile));duplicate['dna']=duplicate['primary']
        with self.assertRaises(ProtocolError):ExplorerNetworks(self.root/'one','alpha',[duplicate])

    def test_all_component_snapshot_contracts_are_permissioned_and_redacted(self):
        sources=[]
        for component in sorted(COMPONENTS):
            path=self.root/(component+'.json');path.write_bytes(encoded({'schema':'ziokt.p2p-snapshot.v1','component':component,'nodes':[{'id':'local','label':'private-host.example','address':'192.0.2.1:7234'},{'id':'peer','address':'192.0.2.2:7234'}],'edges':[{'source':'local','target':'peer','relation':'adapter'}]}));path.chmod(0o600)
            sources.append({'id':component,'component':component,'kind':'snapshot','path':str(path)})
        admin=self.root/'admin.key';admin.write_text('owner-token');admin.chmod(0o600)
        viewer=self.root/'viewer.key';viewer.write_text('viewer-token');viewer.chmod(0o600)
        service=P2PExplorer({'sources':sources,'token_file':str(admin),'viewers':[{'token_file':str(viewer),'scopes':['topology:read']}]})
        with self.assertRaises(ProtocolError):service.query('/api/p2p/topology')
        public=service.query('/api/p2p/topology','Bearer viewer-token')
        self.assertEqual(len(public['nodes']),len(COMPONENTS)*2);self.assertEqual(len(public['edges']),len(COMPONENTS))
        self.assertNotIn('192.0.2.',json.dumps(public));self.assertNotIn('private-host',json.dumps(public))
        with self.assertRaises(ProtocolError):service.query('/api/p2p/topology?addresses=1','Bearer viewer-token')
        detailed=service.query('/api/p2p/topology?addresses=1&identities=1','Bearer owner-token')
        self.assertIn('192.0.2.1',json.dumps(detailed));self.assertNotEqual(public['nodes'][0]['id'],service.query('/api/p2p/topology','Bearer owner-token')['nodes'][0]['id'])

    def test_timestamped_adapter_cannot_present_stale_or_future_connectivity(self):
        path=self.root/'live-probe.json'
        source={'id':'owned-peer','component':'corium','kind':'snapshot','path':str(path)}
        view=P2PExplorer({'public':True,'sources':[source]})
        now=int(time.time())
        for at,available in [(now,True),(now-301,False),(now+6,False),(True,False)]:
            path.write_bytes(encoded({'schema':'ziokt.p2p-snapshot.v1','component':'corium','observed_at':at,'nodes':[{'id':'peer','state':'native-rpc-responded'}],'edges':[]}));path.chmod(0o600)
            result=view.query('/api/p2p/topology')
            self.assertEqual(result['sources'][0]['state']=='available',available)
            self.assertEqual(bool(result['nodes']),available)

    def test_cbb_signature_expiry_and_scope_are_enforced(self):
        root=self.root/'one';network='alpha';dht=root/'var/lib/corix/p2p/dht.db';dht.parent.mkdir(parents=True)
        with database(dht) as db:db.execute('CREATE TABLE nodes(id TEXT,address TEXT,port INTEGER,last_seen INTEGER)')
        key=ec.generate_private_key(ec.SECP256K1());pem=dna.public_key_pem(key);author=hashlib.sha256(pem.encode()).hexdigest();now=int(time.time())
        with database(self.primary) as db:db.execute('INSERT INTO validators VALUES(?,?,?)',(pem,author,'active'))
        forum=root/'var/lib/corix/networks/alpha/forum/forum.db';forum.parent.mkdir()
        with database(forum) as db:
            db.execute('CREATE TABLE cbb_messages(msg_hash TEXT,author_id TEXT,timestamp INTEGER,message TEXT,signature TEXT,expires_at INTEGER)')
            for message,valid in [('current bulletin',True),('forged bulletin',False)]:
                raw=f'CORIUM-CBB-V1\n{network}\n{author}\n{now}\n{message}'.encode();sig=key.sign(raw,ec.ECDSA(hashes.SHA256())).hex() if valid else '00'*64
                db.execute('INSERT INTO cbb_messages VALUES(?,?,?,?,?,?)',(hashlib.sha256(raw).hexdigest(),author,now,message,sig,now+86400))
        token=self.root/'token';token.write_text('owner');token.chmod(0o600)
        view=P2PExplorer({'token_file':str(token),'sources':[{'id':'native','component':'corium','kind':'corium','state_root':str(root),'network_id':network}]})
        projected=view.query('/api/p2p/topology?cbb=1','Bearer owner');self.assertEqual(len(projected['cbb']),1);self.assertNotIn('current bulletin',json.dumps(projected))
        full=view.query('/api/p2p/topology?cbb=1&content=1','Bearer owner');self.assertEqual(full['cbb'][0]['message'],'current bulletin');self.assertTrue(full['cbb'][0]['signature_verified'])


if __name__=='__main__':unittest.main()

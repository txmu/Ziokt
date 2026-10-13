"""Actual ledger inclusion, block NFT minting, binary snapshots and ownership gifts."""
import base64
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import sys
import unittest
from contextlib import closing

from test_native_integration import C
from ziokt.client import NativeClient
from ziokt.config import fingerprint
from ziokt.protocol import ProtocolError


class NativeAssets(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0,str(C))
        from test_core import Fixture
        self.fixture=Fixture();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        for p in f.root.rglob('*'):
            if p.is_dir():p.chmod(0o700)
        (f.etc/'identity.key').chmod(0o600)
        cfg=f.etc/'corix.conf'
        cfg.write_text('[ziokt]\nenabled=TRUE\nfederation_id=test\nprovider_id=corium-local\nallow_mutations=TRUE\nallowed_operations=identity.register,content.publish,zkn.transfer,chain.mine\nallowed_resources=*\nzkn_enabled=TRUE\n');cfg.chmod(0o600)
        self.client=NativeClient('test',{'native_project':'corium','provider_id':'corium-local','root':str(C),'native_config':str(cfg),'state_root':str(f.root),'network_id':'default','entrypoint_digest':fingerprint(C/'corix_v108.sh')})

    def execute(self,op,action,resource,arguments):
        plan=self.client.call('operation.prepare',{'operation_id':op,'action':action,'resource':resource,'arguments':arguments,'expected_revision':None})
        return self.client.call('operation.commit',{'operation_id':op,'plan_digest':plan['plan_digest']})

    def test_registration_requires_inclusion_and_nft_contains_packed_text_binary_and_score(self):
        f=self.fixture;member='a'*64;commitment='sha256:'+'b'*64;policy='sha256:'+'c'*64
        registration=self.execute('register','identity.register','identity:'+member,{'document_commitment':commitment,'policy_digest':policy})
        self.assertEqual(registration['result']['phase'],'pending-native-consensus')
        query={'member_public':member,'policy_digest':policy,'issuer':f.identity}
        with self.assertRaises(ProtocolError):self.client.call('identity.fact',query)
        binary=b'\x00\x01\xffbinary snapshot'
        self.execute('publish','content.publish','content:default',{'text':'Packed community text','data_base64':base64.b64encode(binary).decode(),'content_type':'application/octet-stream'})
        mined=self.execute('mine-first','chain.mine','chain:default',{})
        self.assertTrue(mined['result']['block_created'])
        self.assertTrue(self.client.call('identity.fact',query)['registered'])
        with closing(sqlite3.connect(f.chain)) as db:
            row=db.execute("SELECT data FROM transactions WHERE type='zkn_mint' AND block_height IS NULL").fetchone()
        self.assertIsNotNone(row)
        mint=json.loads(row[0])['snapshot'];manifest=mint['manifest']
        self.assertEqual(manifest['packer'],f.identity);self.assertEqual(manifest['zkt_score'],0)
        self.assertEqual(manifest['block_hash'],mined['result']['block_hash'])
        artifact=f.root/'var/lib/corix/p2p/objects/ziokt'/manifest['contents_digest'][7:]
        contents=json.loads(artifact.read_bytes())
        packed=[json.loads(base64.b64decode(tx['data_base64'])) for tx in contents['transactions'] if tx['type']=='ziokt_content'][0]
        self.assertEqual(packed['text'],'Packed community text');self.assertEqual(base64.b64decode(packed['data_base64']),binary)
        self.execute('mine-mint','chain.mine','chain:default',{})
        nft=self.client.call('zkn.list')['tokens'][0]
        self.assertEqual(nft['token_id'],manifest['token_id']);self.assertEqual(nft['owner'],f.identity)
        recipient='d'*64
        self.execute('gift','zkn.transfer','zkn:'+nft['token_id'],{'recipient':recipient,'nonce':1})
        self.execute('mine-gift','chain.mine','chain:default',{})
        nft=next(t for t in self.client.call('zkn.list')['tokens'] if t['token_id']==manifest['token_id'])
        self.assertEqual(nft['owner'],recipient);self.assertEqual(nft['nonce'],1)
        with self.assertRaises(ProtocolError):self.execute('unauthorized','zkn.transfer','zkn:'+nft['token_id'],{'recipient':f.identity,'nonce':2})


if __name__=='__main__':unittest.main()

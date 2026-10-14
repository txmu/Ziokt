"""No compiler: private collectibles, retry, sealed packs and real native ledger."""
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from ziokt import _runtime
from ziokt.collectibles import receiver,gift,accept_gift,GiftOutbox,issue_edition,pack_editions,unpack_editions
from ziokt.protocol import ProtocolError,encoded
import test_native_assets as native_assets


def pem(key): return key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()


def snapshot(key,network='default'):
    public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
    value={'schema':'ziokt.zkn-snapshot.v2','network_id':network,'token_id':_runtime.asset_token_id(network,'a'*64),
       'block_hash':'a'*64,'height':1,'packer':hashlib.sha256(public.encode()).hexdigest(),'packed_at':1,
       'contents_digest':'sha256:'+'b'*64,'contents_size':1,'zkt_score':0,'lucky_digit':'F','relay_obligation':'free-p2p-forwarding-v1'}
    return {'manifest':value,'public_key':public,'signature':_runtime.native_ec_sign(key,b'Ziokt/ZKN/snapshot/v2\n'+encoded(value))}


class Collectibles(unittest.TestCase):
    def setUp(self):
        self.owner=ec.generate_private_key(ec.SECP256K1());self.snapshot=snapshot(self.owner)
        self.offer,self.wallet=receiver('default')
        self.tx=gift(self.snapshot,1,self.offer,pem(self.owner))
        self.tx_hash=_runtime.asset_signed_gift(self.tx,'default')[1]

    def fact(self):
        return {'phase':'on-chain','transaction_hash':self.tx_hash,'transaction':self.tx,'confirmations':2,'inclusion':{'assurance':'native-signed-inclusion'}}

    def test_fresh_receiver_sealed_receipt_and_immutable_lucky_digit(self):
        second,_=receiver('default');self.assertNotEqual(self.offer['public_key'],second['public_key'])
        receipt=accept_gift(self.wallet,self.snapshot,self.tx,self.fact())
        self.assertEqual(receipt['lucky_digit'],'F');self.assertFalse(receipt['fee_required'])
        self.assertNotIn(self.offer['mailbox'],encoded(self.tx).decode())
        other=self.snapshot.copy();other['manifest']={**other['manifest'],'lucky_digit':'0'}
        with self.assertRaises(ProtocolError): accept_gift(self.wallet,other,self.tx,self.fact())
        altered=json.loads(encoded(self.tx));altered['data']['recipient']='e'*64
        with self.assertRaises(ProtocolError): _runtime.asset_signed_gift(altered,'default')
        with self.assertRaises(ProtocolError): accept_gift(receiver('default')[1],self.snapshot,self.tx,self.fact())
        with self.assertRaises(ProtocolError): accept_gift(self.wallet,self.snapshot,self.tx,{**self.fact(),'confirmations':1})

    def test_outbox_survives_lost_ack_uses_another_route_and_reconciles_fork(self):
        with tempfile.TemporaryDirectory() as tmp:
            key=secrets.token_bytes(32);path=Path(tmp)/'outbox.sqlite';box=GiftOutbox(path,key)
            self.addCleanup(box.close);self.assertEqual(box.enqueue(self.tx),box.enqueue(self.tx))
            self.assertNotIn(self.tx['data']['token_id'].encode(),path.read_bytes())
            routes=[];calls=[];included=[False]
            def choose(tx_hash,attempt): routes.append(attempt);return attempt
            def call(method,params,route):
                calls.append((method,params,route))
                if method=='zkn.fact': return self.fact() if included[0] else {'phase':'absent'}
                if method=='operation.prepare': return {'plan_digest':'sha256:'+'c'*64}
                included[0]=True;raise OSError('ack dropped AFTER ledger submission')
            self.assertEqual(box.cycle(call,choose)[0]['phase'],'queued')
            with box.db: box.db.execute('UPDATE gifts SET next_try=0')
            self.assertEqual(box.cycle(call,choose)[0]['phase'],'confirmed')
            self.assertEqual(routes,[0,1]);self.assertEqual(sum(m=='operation.commit' for m,_,_ in calls),1)
            with box.db: box.db.execute('UPDATE gifts SET next_try=0')
            included[0]=False
            self.assertEqual(box.cycle(call,choose)[0]['phase'],'queued')
            wrong=GiftOutbox(path,secrets.token_bytes(32));self.addCleanup(wrong.close)
            with self.assertRaises(ProtocolError): wrong._open(self.tx_hash,box.db.execute('SELECT body FROM gifts').fetchone()[0])

    def test_zkc_types_encrypted_pack_tamper_and_confirmation(self):
        token=self.tx['data']['token_id'];digest='sha256:'+'d'*64
        repeated=issue_edition('default',token,'repeat','0',digest,pem(self.owner))
        unique=issue_edition('default',token,'unique','1',digest,pem(self.owner))
        self.assertNotEqual(_runtime.zkc_edition_id(repeated['data']),_runtime.zkc_edition_id(unique['data']))
        for kind,serial in [('repeat','1'),('unique','0'),('unique','01')]:
            with self.assertRaises(ProtocolError): issue_edition('default',token,kind,serial,digest,pem(self.owner))
        blob=pack_editions([repeated,unique],'default',pem(self.owner),self.offer)
        self.assertEqual(len(blob),16384);self.assertNotIn(token.encode(),blob)
        def query(method,params):
            tx=next(t for t in (repeated,unique) if _runtime.asset_signed_gift(t,'default','zkc_issue')[1]==params['transaction_hash'])
            return {'phase':'on-chain','transaction_hash':params['transaction_hash'],'transaction':tx,'confirmations':2,'inclusion':{'assurance':'native-signed-inclusion'}}
        result=unpack_editions(blob,self.wallet,publisher=repeated['public_key'],query=query)
        self.assertTrue(result['ledger_confirmed']);self.assertEqual(len(result['editions']),2)
        with self.assertRaises(ProtocolError): unpack_editions(blob[:-1]+bytes([blob[-1]^1]),self.wallet,publisher=repeated['public_key'])
        with self.assertRaises(ProtocolError): pack_editions([unique,unique],'default',pem(self.owner),self.offer)
        self.assertFalse(unpack_editions(blob,self.wallet,publisher=repeated['public_key'])['ledger_confirmed'])


class NativeCollectibles(unittest.TestCase):
    setUp=native_assets.NativeAssets.setUp
    execute=native_assets.NativeAssets.execute

    def mint(self):
        self.execute('content','content.publish','content:default',{'text':'collectible','data_base64':'','content_type':'text/plain'})
        self.execute('mine-one','chain.mine','chain:default',{})
        self.execute('mine-two','chain.mine','chain:default',{})
        return self.client.call('zkn.list')['tokens'][0]['snapshot']

    def submit(self,tx,op):
        return self.execute(op,'zkc.issue' if tx['type']=='zkc_issue' else 'zkn.gift','zkn:'+tx['data']['token_id'],{'transaction':tx})

    def test_actual_private_gift_repeated_delivery_conflict_forwarding_and_zkc_ownership(self):
        self.fixture.etc.joinpath('corix.conf').write_text('[ziokt]\nenabled=TRUE\nfederation_id=test\nprovider_id=corium-local\nallow_mutations=TRUE\nallowed_operations=content.publish,zkn.gift,zkc.issue,zkn.transfer,chain.mine\nallowed_resources=*\nzkn_enabled=TRUE\n')
        snap=self.mint();owner=self.fixture.etc.joinpath('identity.key').read_text()
        self.assertRegex(snap['manifest']['lucky_digit'],'^[0-9A-F]$')
        offer,wallet=receiver('default');tx=gift(snap,1,offer,owner);tx_hash=_runtime.asset_signed_gift(tx,'default')[1]
        self.submit(tx,'private-one');self.submit(tx,'private-retry')
        with sqlite3.connect(self.fixture.chain) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM transactions WHERE hash=?',(tx_hash,)).fetchone()[0],1)
        conflict=gift(snap,1,receiver('default')[0],owner)
        with self.assertRaises(ProtocolError): self.submit(conflict,'conflicting')
        self.assertEqual(self.client.call('zkn.fact',{'transaction_hash':tx_hash})['phase'],'pending-native-consensus')
        self.execute('mine-gift','chain.mine','chain:default',{})
        fact=self.client.call('zkn.fact',{'transaction_hash':tx_hash})
        accepted=accept_gift(wallet,snap,tx,fact,confirmations=1);self.assertTrue(accepted['confirmed'])
        self.submit(tx,'confirmed-retry')
        object_path=self.fixture.root/'var/lib/corix/p2p/objects/transactions'/tx_hash
        self.assertEqual(json.loads(object_path.read_bytes()),tx)
        with sqlite3.connect(self.fixture.dht) as db: self.assertIsNotNone(db.execute('SELECT hash FROM local_chunks WHERE hash=?',(tx_hash,)).fetchone())
        digest=snap['manifest']['contents_digest'];token=snap['manifest']['token_id']
        forbidden=issue_edition('default',token,'unique','1',digest,owner)
        with self.assertRaises(ProtocolError):self.submit(forbidden,'old-holder')
        repeated=issue_edition('default',token,'repeat','0',digest,wallet['owner_private'])
        unique=issue_edition('default',token,'unique','1',digest,wallet['owner_private'])
        self.submit(repeated,'edition-repeat');self.submit(unique,'edition-unique')
        self.execute('mine-editions','chain.mine','chain:default',{})
        self.assertEqual(len(self.client.call('zkc.list')['editions']),2)
        self.assertEqual(self.client.call('zkc.fact',{'transaction_hash':_runtime.asset_signed_gift(unique,'default','zkc_issue')[1]})['phase'],'on-chain')
        another=issue_edition('default',token,'unique','1',digest,wallet['owner_private'])
        with self.assertRaises(ProtocolError): self.submit(another,'duplicate-unique')
        more=issue_edition('default',token,'repeat','0',digest,wallet['owner_private']);self.submit(more,'repeat-unlimited')
        self.execute('mine-repeat','chain.mine','chain:default',{})
        self.assertEqual(len(self.client.call('zkc.list')['editions']),2)
        offer2,wallet2=receiver('default');blob=pack_editions([repeated,unique],'default',wallet['owner_private'],offer2)
        self.assertTrue(unpack_editions(blob,wallet2,publisher=repeated['public_key'],query=self.client.call,confirmations=1)['ledger_confirmed'])

"""Actual mTLS two-hop gifts, a lost acknowledgement and a different route."""
import hashlib
import http.client
from pathlib import Path
import secrets
import sqlite3
import threading
import unittest

from cryptography.hazmat.primitives import serialization
import test_native_assets as native_assets
from test_community_network import certificates
import test_community_peer_proxy as proxy_tests
from ziokt.collectibles import receiver,gift,GiftOutbox,GiftRPC,accept_gift
from ziokt import _runtime
from ziokt.remote import remote_server,tls_context
from ziokt.security import sign

class CollectibleNetwork(unittest.TestCase):
    setUp=native_assets.NativeAssets.setUp
    execute=native_assets.NativeAssets.execute
    start=proxy_tests.PeerProxyTests.start
    proxy=proxy_tests.PeerProxyTests.proxy

    def test_keyless_multihop_switch_after_lost_commit_ack_and_chain_deduplication(self):
        self.root=self.fixture.root
        self.fixture.etc.joinpath('corix.conf').write_text('[ziokt]\nenabled=TRUE\nfederation_id=test\nprovider_id=corium-local\nallow_mutations=TRUE\nallowed_operations=content.publish,zkn.gift,chain.mine\nallowed_resources=*\nzkn_enabled=TRUE\n')
        self.execute('content','content.publish','content:default',{'text':'network collectible','data_base64':'','content_type':'text/plain'})
        self.execute('mine-one','chain.mine','chain:default',{});self.execute('mine-two','chain.mine','chain:default',{})
        snapshot=self.client.call('zkn.list')['tokens'][0]['snapshot'];offer,wallet=receiver('default')
        tx=gift(snapshot,1,offer,self.fixture.etc.joinpath('identity.key').read_text());tx_hash=_runtime.asset_signed_gift(tx,'default')[1]
        material=self.root/'gift-tls';material.mkdir()
        ca,pairs=certificates(material,'127.0.0.1');private=secrets.token_bytes(32);public=sign({},private,'test')['public_key']
        client_fingerprint=hashlib.sha256(pairs['client'][2].public_bytes(serialization.Encoding.DER)).hexdigest()
        destination=remote_server({'enabled':True,'federation_id':'test','providers':[self.client.provider]},
            tls_context(*pairs['server'][:2],ca,server=True),self.root/'gift-replay.sqlite',
            {client_fingerprint:{'public_key':public,'methods':['zkn.fact','operation.prepare','operation.commit'],'providers':['corium-local']}},allow_mutations=True)
        self.start(destination)
        paths=[];servers=[]
        for name in ('a','b'):
            last,last_hop=self.proxy('last-'+name,destination.server_port)
            first,first_hop=self.proxy('first-'+name,last.server_address[1]);servers.append(first)
            paths.append({'host':'127.0.0.1','port':destination.server_port,'carrier':{'kind':'peer-multihop','hops':[first_hop,last_hop]}})
        observed=[];original_request=http.client.HTTPSConnection.request
        def record_request(connection,method,url,body=None,headers=None,*,encode_chunked=False):
            if url=='/zfcp' and isinstance(body,bytes):observed.append(body)
            return original_request(connection,method,url,body,headers or {},encode_chunked=encode_chunked)
        http.client.HTTPSConnection.request=record_request
        self.addCleanup(setattr,http.client.HTTPSConnection,'request',original_request)
        rpc=GiftRPC('test','corium-local',tls_context(*pairs['client'][:2],ca),private)
        box=GiftOutbox(self.root/'gift-outbox.sqlite',secrets.token_bytes(32),mix_window=(0,0));self.addCleanup(box.close);box.enqueue(tx)
        route_calls=[]
        def choose(tx_hash,attempts):route_calls.append(attempts);return paths[min(attempts,1)]
        def dropped_ack(method,params,endpoint):
            result=rpc(method,params,endpoint)
            if method=='operation.commit':raise OSError('acknowledgement lost after actual native submission')
            return result
        self.assertEqual(box.cycle(dropped_ack,choose,confirmations=1)[0]['phase'],'queued')
        # The original ingress actually stops; reconciliation must use path b.
        servers[0].shutdown();servers[0].server_close()
        with box.db:box.db.execute('UPDATE gifts SET next_try=0')
        self.assertEqual(box.cycle(rpc,choose,confirmations=1)[0]['phase'],'waiting')
        self.execute('mine-gift','chain.mine','chain:default',{})
        with box.db:box.db.execute('UPDATE gifts SET next_try=0')
        self.assertEqual(box.cycle(rpc,choose,confirmations=1)[0]['phase'],'confirmed')
        self.assertEqual(route_calls,[0,1,2])
        with sqlite3.connect(self.fixture.chain) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM transactions WHERE hash=?',(tx_hash,)).fetchone()[0],1)
        fact=rpc('zkn.fact',{'transaction_hash':tx_hash},paths[1])
        self.assertTrue(accept_gift(wallet,snapshot,tx,fact,confirmations=1)['confirmed'])

        # Observe actual sender frames while retaining every real socket/native call.
        from ziokt.protocol import strict_json,ProtocolError
        from ziokt.collectibles import delivery_digest
        from ziokt.remote import request_remote,resource_for
        from ziokt.security import grant
        capsules=[strict_json(body) for body in observed]
        self.assertTrue(capsules);self.assertTrue(all(len(body)==32768 for body in observed))
        self.assertEqual(len({frame['delivery_id'] for frame in capsules}),len(capsules))
        self.assertTrue(all(set(frame)=={'schema','delivery_id','payload','padding'} for frame in capsules))
        self.assertTrue(all(tx['data']['token_id'].encode() not in body for body in observed))
        request={'provider_id':'corium-local','method':'zkn.fact','params':{'transaction_hash':tx_hash}}
        ident=secrets.token_hex(32)
        signed=grant(private,audience='corium-local',action='zkn.fact',resource=resource_for('zkn.fact',request['params']),federation='test',request_digest=delivery_digest(request,ident))
        def direct(delivery):
            return request_remote('127.0.0.1',destination.server_port,tls_context(*pairs['client'][:2],ca),request,signed,carrier=paths[1]['carrier'],privacy_padding=True,delivery_id=delivery)
        self.assertEqual(direct(ident)['transaction_hash'],tx_hash)
        with self.assertRaises(ProtocolError) as replay:direct(ident)
        self.assertEqual(replay.exception.code,'REPLAY_REJECTED')
        with self.assertRaises(ProtocolError) as altered:direct(secrets.token_hex(32))
        self.assertEqual(altered.exception.code,'INVALID_GRANT')
        legacy=GiftRPC('test','corium-local',tls_context(*pairs['client'][:2],ca),private,delivery_version=1)
        self.assertEqual(legacy('zkn.fact',{'transaction_hash':tx_hash},paths[1])['transaction_hash'],tx_hash)

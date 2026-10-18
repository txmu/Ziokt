import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec,ed25519
from ziokt.naming import Names
from ziokt.naming_corium import CoriumNames
from ziokt.gateway_store import Store
from ziokt.security import sign
from ziokt.protocol import ProtocolError

class CoriumNamingTests(unittest.TestCase):
    def test_native_owner_bound_target_opt_in_and_optimistic_row_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=Store(root/'objects');expiry=int(time.time())+3600
            nativekey=ec.generate_private_key(ec.SECP256K1());public=nativekey.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
            owner=hashlib.sha256(public.encode()).hexdigest();key=bytes(range(32));delegate=ed25519.Ed25519PrivateKey.from_private_bytes(key).public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
            record={'network_id':'chain-one','component':'corium','path':'community','parent_revision':1,'revision':1,'expires_at':expiry,'delegate':None,
                    'descriptor':{'public_dns':[{'type':'A','value':'8.8.8.8','ttl':60}],'services':{},'private':None}}
            target=store.put(json.dumps({'ziokt_naming':{'network_id':'chain-one','owner':delegate,'revision':1,'expires_at':expiry,'published_suffixes':['corix'],'delegations':{'community':sign(record,key,'Ziokt/name-delegation/v1')}}}).encode())
            data=json.dumps({'domain_name':'community','target_hash':target},separators=(',',':'))
            raw=('{"type":"nns_register","data":'+data+',"timestamp":1}').encode();txhash=hashlib.sha256(raw).hexdigest();signature=nativekey.sign(raw,ec.ECDSA(hashes.SHA256())).hex()
            forum=root/'forum.db';chain=root/'chain.db'
            with sqlite3.connect(forum) as db:
                db.execute('CREATE TABLE nns_records(domain_name,owner_id,target_hash,last_update_height,expires_at)')
                db.execute('INSERT INTO nns_records VALUES (?,?,?,?,?)',('community',owner,target,1,expiry))
            with sqlite3.connect(chain) as db:
                db.execute('CREATE TABLE blocks(height,hash,transactions)');db.execute('INSERT INTO blocks VALUES (1,?,?)',('b'*64,json.dumps([txhash])))
                db.execute('CREATE TABLE transactions(hash,type,data,signature,public_key,timestamp,block_height)')
                db.execute('INSERT INTO transactions VALUES (?,?,?,?,?,?,?)',(txhash,'nns_register',data,signature,public,1,1))
            resolver=Names({'corium':CoriumNames(forum_db=forum,chain_db=chain,objects=root/'objects',network_id='chain-one')},network_id='chain-one')
            self.assertTrue(resolver.resolve('community.corix')['records'])
            with self.assertRaises(ProtocolError):resolver.resolve('community.cor')
            with sqlite3.connect(chain) as db:db.execute('UPDATE blocks SET transactions=?',('[]',))
            with self.assertRaises(ProtocolError):resolver.resolve('community.corix')

if __name__=='__main__':unittest.main()

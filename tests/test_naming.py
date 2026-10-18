import copy
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from ziokt.naming import Names,NameNetworks,SUFFIXES,split_name,public_records
from ziokt.security import sign
from ziokt.protocol import ProtocolError

DOMAIN='Ziokt/name-delegation/v1'
class NamingTests(unittest.TestCase):
    def setUp(self):
        self.key=bytes(range(32));self.child=bytes(range(1,33))
        self.public=lambda k:Ed25519PrivateKey.from_private_bytes(k).public_key().public_bytes(Encoding.Raw,PublicFormat.Raw).hex()
        self.description={'public_dns':[{'type':'A','value':'8.8.8.8','ttl':60}],
            'services':{'shadow6':{'object':'sha256:'+'a'*64,'access':'authenticated'}},'private':None}
        self.root={'network_id':'ziokt-main','component':'corium','path':'community','parent_revision':7,'revision':1,
            'expires_at':1900,'delegate':self.public(self.child),'descriptor':self.description}
        self.sub={**self.root,'path':'chat.community','parent_revision':1,'delegate':None,'expires_at':1800}
        self.native={'network_id':'ziokt-main','published_suffixes':['cor','c','corium','corix'],'owner':self.public(self.key),'revision':7,'expires_at':2000,
            'proof':{'native_finalized_state':'test-fixture-not-production'},
            'delegations':{'community':sign(self.root,self.key,DOMAIN)}}
        self.calls=[]
        def source(root):self.calls.append(root);return self.native
        self.resolver=Names({'corium':source},clock=lambda:1000)

    def test_suffix_routes_and_nns_has_no_tld(self):
        self.assertEqual(len(SUFFIXES),57)
        for tld in ('cor','c','corium','corix'):
            self.assertEqual(self.resolver.resolve('community.'+tld)['records'][0]['value'],'8.8.8.8')
        self.assertEqual(self.calls,['community']*4)
        for name in ('community.com','a..cor','../community.cor','x.cor/secret'):
            with self.assertRaises(ProtocolError):self.resolver.resolve(name)
        self.assertEqual(len(self.calls),4)
        with self.assertRaises(ProtocolError):self.resolver.resolve('community.s6')
        self.assertEqual(len(self.calls),4)

    def test_child_registration_requires_parent_key_and_revision(self):
        self.native['delegations']['chat.community']=sign(self.sub,self.child,DOMAIN)
        answer=self.resolver.resolve('chat.community.cor',component='shadow6',public=False)
        self.assertEqual(answer['service']['access'],'authenticated')
        self.assertFalse(answer['authenticated_access'])
        for mutation in ({'parent_revision':2},{'path':'other.community'},{'expires_at':2100},{'component':'shadow6'}):
            self.native['delegations']['chat.community']=sign({**self.sub,**mutation},self.child,DOMAIN)
            with self.assertRaises(ProtocolError):self.resolver.resolve('chat.community.cor')
        self.native['delegations']['chat.community']=sign(self.sub,self.key,DOMAIN)
        with self.assertRaises(ProtocolError):self.resolver.resolve('chat.community.cor')

    def test_public_projection_never_exports_private_identity_or_service(self):
        answer=self.resolver.resolve('community.cor')
        self.assertEqual(set(answer),{'name','records','expires_at','authenticated_access'})
        self.assertNotIn('shadow6',str(answer));self.assertNotIn(self.public(self.key),str(answer))
        for address in ('127.0.0.1','10.1.1.1','::1','fe80::1'):
            with self.assertRaises(ProtocolError):public_records([{'type':'AAAA' if ':' in address else 'A','value':address,'ttl':60}])
        with self.assertRaises(ProtocolError):public_records([{'type':'TXT','value':'secret-route=example','ttl':60}])

    def test_independent_realms_never_fall_back(self):
        networks=NameNetworks({'main':self.resolver,'isolated':Names({})},default='main')
        self.assertTrue(networks.resolve('community.cor')['records'])
        with self.assertRaises(ProtocolError):networks.resolve('community.cor',realm='isolated')
        with self.assertRaises(ProtocolError):networks.resolve('community.cor',realm='unknown')
        self.native['network_id']='other-chain'
        with self.assertRaises(ProtocolError):networks.resolve('community.cor')

    def test_opt_in_publication_is_per_suffix(self):
        self.native['published_suffixes']=['corix']
        self.assertTrue(self.resolver.resolve('community.corix')['records'])
        for suffix in ('cor','c','corium'):
            with self.assertRaises(ProtocolError):self.resolver.resolve('community.'+suffix)

    def test_expiry_and_native_revocation(self):
        self.native['revision']=8
        with self.assertRaises(ProtocolError):self.resolver.resolve('community.cor')
        self.native['revision']=7;self.native['expires_at']=999
        with self.assertRaises(ProtocolError):self.resolver.resolve('community.cor')

if __name__=='__main__':unittest.main()

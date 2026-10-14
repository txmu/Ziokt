import base64
from fractions import Fraction
from pathlib import Path
import secrets
import tempfile
import unittest
import uuid
from ziokt.ano import Signal,merge,cross,majority,conjunction,defence,evaluate,truth_table,ZDANumber,AnoNumber
from ziokt.safefs import Vault
from ziokt.community import Community,create_policy,RIGHTS
from ziokt.cli import write_exclusive,write_binary_exclusive
from ziokt.companion_bridge import CompanionBridge
from ziokt.protocol import ProtocolError
from ziokt.security import sign

class AnoTests(unittest.TestCase):
    def test_refined_truth_profile_and_unknown_never_promotes_authorization(self):
        table=truth_table();self.assertEqual(len(table['rows']),4)
        self.assertEqual(merge('正','反'),Signal.POSITIVE)
        self.assertEqual(cross('反','反'),Signal.POSITIVE)
        self.assertEqual(majority('正','反'),Signal.NEGATIVE)
        self.assertEqual(defence({'signature':True,'membership':None},['signature','membership'])['decision'],'hold')
        self.assertEqual(defence({'signature':False,'majority':True},['signature','majority'])['decision'],'deny')
        self.assertFalse(table['cryptographic_proof'])
        self.assertEqual(evaluate({'op':'and','args':[True,None]})['result'],'unknown')
        tree=True
        for _ in range(10):tree={'op':'not','args':[tree]}
        with self.assertRaises(ProtocolError):evaluate(tree)

    def test_zda_singularities_exact_rationals_and_bounded_numeric_state(self):
        self.assertEqual((ZDANumber(1)/0).state,'infinity');self.assertEqual((ZDANumber()/0).state,'bottom')
        self.assertEqual((ZDANumber.infinity()*0).state,'bottom')
        self.assertEqual((ZDANumber(1)/3).real,Fraction(1,3))
        self.assertEqual((ZDANumber(0,1)*ZDANumber(0,1)).real,-1)
        self.assertEqual((AnoNumber(1,0,'正')+AnoNumber(1,0,'反')).ano_part,Signal.POSITIVE)
        with self.assertRaises(ProtocolError):ZDANumber(float('nan'))
        with self.assertRaises(ProtocolError):ZDANumber(1<<5000)


class CompanionCrypto(unittest.TestCase):
    def test_vault_padding_scope_tamper_paths_and_signed_federation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);key=secrets.token_bytes(32);vault=Vault(root/'vault','test',key)
            obj=vault.put('private/name.txt',b'never public');blob=vault.blob(obj['digest'])
            self.assertEqual(len(blob),16384);self.assertNotIn(b'private/name.txt',blob);self.assertNotIn(b'never public',blob)
            self.assertEqual(vault.get(obj['digest']),('private/name.txt',b'never public'))
            with self.assertRaises(ProtocolError):Vault(root/'other','wrong-scope',key).open(blob)
            with self.assertRaises(ProtocolError):vault.open(blob[:-1]+bytes([blob[-1]^1]))
            for name in ('../escape','/absolute','bad\\name','a//b'):
                with self.assertRaises(ProtocolError):vault.put(name,b'x')
            private=secrets.token_bytes(32);public=sign({},private,'test')['public_key'];policy=create_policy(private,'test',{public:sorted(RIGHTS)})
            with Community(root/'community',policy,public,secrets.token_bytes(32)) as community:
                publication=vault.publish(community,private,obj['digest'])
                event=community.view('files')['events'][0]
                self.assertEqual(community.get_file(event['body']),blob);self.assertFalse(publication['plaintext_disclosed'])

    def test_bridge_ciphertext_idempotency_scope_and_purpose_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);private=secrets.token_bytes(32);public=sign({},private,'test')['public_key'];policy=create_policy(private,'test',{public:sorted(RIGHTS)})
            write_exclusive(root/'policy.json',policy)
            for name in ('signing','application','encryption'):write_binary_exclusive(root/(name+'.key'),private if name=='signing' else secrets.token_bytes(32))
            config=root/'bridge.json';write_exclusive(config,{'schema':'ziokt.companion-bridge.v1','community_root':str(root/'community'),'policy':str(root/'policy.json'),
                'owner':public,'encryption_key':str(root/'encryption.key'),'signing_key':str(root/'signing.key'),'application':'watchat','application_key':str(root/'application.key')})
            bridge=CompanionBridge(config);self.addCleanup(bridge.close)
            a,b=str(uuid.uuid4()),str(uuid.uuid4());payload={'id':str(uuid.uuid4()),'from':a,'to':b,'ciphertext':base64.b64encode(secrets.token_bytes(2048)).decode(),'attachments':[]}
            first=bridge.call('chat.append',payload);again=bridge.call('chat.append',payload)
            self.assertEqual(first['event'],again['event']);self.assertTrue(again['duplicate'])
            events=bridge.community.view('chat')['events'];self.assertNotIn(a,events[0]['body']['text']);self.assertNotIn(b,events[0]['body']['text'])
            returned=bridge.call('chat.pull',{'from':a,'to':b})['messages'][0];self.assertEqual(returned['ciphertext'],payload['ciphertext'])
            with self.assertRaises(ProtocolError):bridge.call('chat.append',{**payload,'ciphertext':base64.b64encode(secrets.token_bytes(2048)).decode()})
            with self.assertRaises(ProtocolError):bridge.call('shell.execute',{})

    def _make_bridge(self,root,private,public,policy,app='safefs-test',extra=None):
        from ziokt.cli import write_exclusive,write_binary_exclusive
        write_exclusive(root/'policy.json',policy)
        for name in ('signing','application','encryption'):write_binary_exclusive(root/(name+'.key'),private if name=='signing' else secrets.token_bytes(32))
        cfg={'schema':'ziokt.companion-bridge.v1','community_root':str(root/'community'),'policy':str(root/'policy.json'),
            'owner':public,'encryption_key':str(root/'encryption.key'),'signing_key':str(root/'signing.key'),'application':app,'application_key':str(root/'application.key')}
        if extra:cfg.update(extra)
        config=root/'bridge.json';write_exclusive(config,cfg)
        return config

    def test_safefs_publish_read_federation_via_bridge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);private=secrets.token_bytes(32);public=sign({},private,'test')['public_key'];policy=create_policy(private,'test',{public:sorted(RIGHTS)})
            import os;vault_dir=root/'vaultroot';vault_dir.mkdir(mode=0o700)
            config=self._make_bridge(root,private,public,policy,extra={'vault_root':str(vault_dir)})
            bridge=CompanionBridge(config);self.addCleanup(bridge.close)
            # Vault key is the application_key loaded at bridge init time
            appkey=open(root/'application.key','rb').read()
            vault=Vault(vault_dir,'safefs-test',appkey)
            obj=vault.put('secret/data.bin',b'classified content')
            digest=obj['digest']
            # Publish to community via bridge
            result=bridge.call('safefs.publish',{'digest':digest})
            self.assertEqual(result['digest'],digest);self.assertFalse(result['duplicate']);self.assertFalse(result['plaintext_disclosed'])
            # Idempotent: same digest publishes as duplicate
            again=bridge.call('safefs.publish',{'digest':digest})
            self.assertTrue(again['duplicate']);self.assertEqual(again['event'],result['event'])
            # Read back and verify integrity
            read=bridge.call('safefs.read',{'digest':digest})
            self.assertEqual(read['digest'],digest);self.assertFalse(read['plaintext_disclosed'])
            # Wrong vault_root or no vault_root raises
            root_b=root/'b';root_b.mkdir()
            config2=self._make_bridge(root_b,private,public,policy,extra={})
            bridge2=CompanionBridge(config2);self.addCleanup(bridge2.close)
            with self.assertRaises(ProtocolError) as cm:bridge2.call('safefs.publish',{'digest':digest})
            self.assertEqual(cm.exception.code,'POLICY_DENIED')

    def test_drain_pending_replays_failed_publishes_on_reconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);private=secrets.token_bytes(32);public=sign({},private,'test')['public_key'];policy=create_policy(private,'test',{public:sorted(RIGHTS)})
            import os;vault_dir=root/'vaultroot';vault_dir.mkdir(mode=0o700)
            config=self._make_bridge(root,private,public,policy,extra={'vault_root':str(vault_dir)})
            bridge=CompanionBridge(config);self.addCleanup(bridge.close)
            appkey=open(root/'application.key','rb').read()
            vault=Vault(vault_dir,'safefs-test',appkey)
            obj=vault.put('pending/file.bin',b'pending content')
            digest=obj['digest']
            # Simulate a transient failure by directly writing a pending entry
            bridge.close()
            from ziokt.protocol import encoded
            pending_path=bridge._pending_path
            pending_path.write_bytes(encoded({'method':'safefs.publish','params':{'digest':digest}})+b'\n')
            # Re-open bridge — drain_pending should replay the entry
            bridge2=CompanionBridge(config);self.addCleanup(bridge2.close)
            # After draining, the object should be in the community
            events=bridge2.community.view('files')['events']
            self.assertTrue(any('safefs' in (e.get('key','') or '') for e in events) or len(events)>0)
            # Pending file should be cleared after successful drain
            self.assertFalse(pending_path.exists())


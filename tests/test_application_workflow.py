"""Five routed applications, actual encrypted artifacts and real mTLS community sync."""
import base64
import hashlib
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from cryptography.hazmat.primitives import serialization

from ziokt.application_router import ApplicationRouter
from ziokt.cli import write_exclusive, write_binary_exclusive
from ziokt.community import Community, create_policy, RIGHTS
from ziokt.community_privacy import mailbox_public
from ziokt.community_network import CommunityEndpoint, sync_remote
from ziokt.protocol import ProtocolError, encoded, strict_json
from ziokt.remote import remote_server, tls_context
from ziokt.safefs import Vault
from ziokt.security import sign
from ziokt.tri import read_project
from ziokt.ufsdcpm import read_package
import test_community_network as network_fixtures


class RoutedArtifactWorkflow(unittest.TestCase):
    def test_tc16_tri_safefs_dcpm_to_independent_ufs_via_real_tls(self):
        names=('tc16','tri','safefs','dcpm','ufs')
        signing={name:secrets.token_bytes(32) for name in names}
        application={name:secrets.token_bytes(32) for name in names}
        mailbox={name:secrets.token_bytes(32) for name in names}
        public={name:sign({},key,'test')['public_key'] for name,key in signing.items()}
        rights={public[name]:['files','mail']+(['replicate'] if name=='ufs' else []) for name in names}
        rights[public['tc16']]=sorted(RIGHTS)
        policy=create_policy(signing['tc16'],'routed-workflow',rights,privacy='private')
        community_key=secrets.token_bytes(32)
        edges={'tc16':{'tri':['compute-result']},
            'tri':{'tc16':['compute-result'],'safefs':['simulation']},
            'safefs':{'tri':['simulation'],'dcpm':['file']},
            'dcpm':{'safefs':['file'],'ufs':['package']},
            'ufs':{'dcpm':['package']}}
        methods={'tc16':['tc16.run'],'tri':['tri.put','tri.get'],
            'safefs':['safefs.publish'],'dcpm':['package.build','package.verify','package.publish'],
            'ufs':['package.verify']}
        shared=['component.send','component.receive','vault.put','vault.get']
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); policy_path=root/'policy.json'; write_exclusive(policy_path,policy)
            roots={'source':root/'community-source','target':root/'community-target'}
            routes={}
            for name in names:
                directory=root/name; directory.mkdir(mode=0o700); (directory/'vault').mkdir(mode=0o700)
                for field,key in [('signing',signing[name]),('application',application[name]),('mailbox',mailbox[name]),('community',community_key)]:
                    write_binary_exclusive(directory/(field+'.key'),key)
                config={'schema':'ziokt.companion-bridge.v1','application':name,
                    'community_root':str(roots['target' if name=='ufs' else 'source']),
                    'owner':public['tc16'],'policy':str(policy_path),'signing_key':str(directory/'signing.key'),
                    'encryption_key':str(directory/'community.key'),'application_key':str(directory/'application.key'),
                    'exchange_key':str(directory/'mailbox.key'),'vault_root':str(directory/'vault'),
                    'component_peers':{peer:{'signing_public':public[peer],'mailbox_public':mailbox_public(mailbox[peer]),
                        'kinds':kinds} for peer,kinds in edges[name].items()}}
                path=directory/'bridge.json'; write_exclusive(path,config)
                routes[name]={'config':str(path),'methods':shared+methods[name]}
            source_path=root/'source-router.json'; target_path=root/'target-router.json'
            write_exclusive(source_path,{'schema':'ziokt.application-router.v1','components':{name:route for name,route in routes.items() if name!='ufs'}})
            write_exclusive(target_path,{'schema':'ziokt.application-router.v1','components':{'ufs':routes['ufs']}})
            with ApplicationRouter(source_path) as sender, ApplicationRouter(target_path) as receiver:
                execution=sender.call('tc16','tc16.run',{'source':'int main() { return 65535 + 2; }','syntax':'tcc','cycles':1000})
                self.assertTrue(execution['halted']); self.assertEqual(execution['registers'][0],1)
                result=sender.call('tc16','vault.put',{'name':'execution.json','data_base64':base64.b64encode(encoded(execution)).decode()})
                offer=sender.call('tc16','component.send',{'target':'tri','kind':'compute-result','digest':result['digest'],'operation':'cpu-result'})
                imported=sender.call('tri','component.receive',{'event':offer['event'],'source':'tc16'})
                cpu_result=strict_json(base64.b64decode(sender.call('tri','vault.get',{'digest':imported['digest']})['data_base64']))
                self.assertEqual(cpu_result,execution); self.assertFalse(imported['auto_executed'])
                project=sender.call('tri','tri.put',{'program':'HALT','state':{'workflow':'private routed artifact','tc16_result':cpu_result['registers'][0]}})
                self.assertEqual(sender.call('tri','tri.get',{'digest':project['digest']})['state']['tc16_result'],1)
                offer=sender.call('tri','component.send',{'target':'safefs','kind':'simulation','digest':project['digest'],'operation':'project-vault'})
                safe=sender.call('safefs','component.receive',{'event':offer['event'],'source':'tri'})
                self.assertFalse(safe['auto_executed'])
                sender.call('safefs','safefs.publish',{'digest':safe['digest']})
                safe_vault=Vault(root/'safefs/vault','safefs',application['safefs'])
                sealed=safe_vault.blob(safe['digest'])
                self.assertNotIn(b'private routed artifact',sealed)
                with self.assertRaises(ProtocolError):
                    Vault(root/'dcpm/vault','dcpm',application['dcpm']).open(sealed)
                offer=sender.call('safefs','component.send',{'target':'dcpm','kind':'file','digest':safe['digest'],'operation':'package-source'})
                source=sender.call('dcpm','component.receive',{'event':offer['event'],'source':'safefs'})
                package=sender.call('dcpm','package.build',{'name':'routed-simulation','version':'1',
                    'files':{'tri/project.json':source['digest']},'dependencies':[]})
                sender.call('dcpm','package.verify',{'digest':package['digest'],'authority':public['dcpm']})
                sender.call('dcpm','package.publish',{'digest':package['digest'],'authority':public['dcpm']})
                offered=sender.call('dcpm','component.send',{'target':'ufs','kind':'package','digest':package['digest'],'operation':'published-package'})
                with self.assertRaises(ProtocolError):
                    receiver.call('ufs','component.receive',{'event':offered['event'],'source':'dcpm'})
                # This stage uses the actual mTLS/grant/checkpoint implementation,
                # not a replacement transport or an in-memory Community copy.
                material=root/'tls'; material.mkdir(mode=0o700)
                ca,pairs=network_fixtures.certificates(material,'127.0.0.1')
                fingerprint=hashlib.sha256(pairs['client'][2].public_bytes(serialization.Encoding.DER)).hexdigest()
                with Community(roots['source'],policy,public['tc16'],community_key) as origin, Community(roots['target'],policy,public['tc16'],community_key) as target:
                    server=remote_server({'enabled':True,'federation_id':'routed-workflow','providers':[]},
                        tls_context(*pairs['server'][:2],ca,server=True),root/'replay.sqlite',
                        {fingerprint:{'public_key':public['ufs'],'methods':['community.status','community.checkpoint.create','community.checkpoint.get','community.checkpoint.release'],
                            'providers':['routed-workflow']}},allow_mutations=True,community=CommunityEndpoint(origin,signing['tc16']))
                    worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start()
                    try:
                        synchronized=sync_remote(target,{'host':'127.0.0.1','port':server.server_port},
                            tls_context(*pairs['client'][:2],ca),signing['ufs'],publisher=public['tc16'])
                        self.assertGreater(synchronized['records'],0)
                        delivered=receiver.call('ufs','component.receive',{'event':offered['event'],'source':'dcpm'})
                        verified=receiver.call('ufs','package.verify',{'digest':delivered['digest'],'authority':public['dcpm']})
                        self.assertEqual(verified['files_verified'],1); self.assertFalse(verified['installation_authorized'])
                        received=base64.b64decode(receiver.call('ufs','vault.get',{'digest':delivered['digest']})['data_base64'])
                        manifest,files=read_package(received,public['dcpm'])
                        self.assertEqual(manifest['name'],'routed-simulation')
                        self.assertEqual(read_project(files['tri/project.json'])['state']['tc16_result'],1)
                        before=target.db.execute('SELECT COUNT(*) FROM records').fetchone()[0]
                        again=receiver.call('ufs','component.receive',{'event':offered['event'],'source':'dcpm'})
                        self.assertTrue(again['duplicate']); self.assertEqual(again['digest'],delivered['digest'])
                        self.assertFalse(delivered['auto_executed'])
                        self.assertEqual(target.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],before)
                        self.assertEqual(target.view('compute')['events'],[])
                        with self.assertRaises(ProtocolError):
                            receiver.call('ufs','package.verify',{'digest':delivered['digest'],'authority':public['safefs']})
                        with self.assertRaises(ProtocolError):
                            receiver.call('ufs','component.receive',{'event':offered['event'],'source':'safefs'})
                        with self.assertRaises(ProtocolError): receiver.call('ufs','tc16.run',{'source':'HALT','syntax':'assembly','cycles':1})
                    finally:
                        server.shutdown(); server.server_close(); worker.join(5)


if __name__=='__main__': unittest.main()

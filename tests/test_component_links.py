"""Every directed component pair uses the same recipient-only artifact contract."""
from pathlib import Path
import secrets
import tempfile
import unittest

from ziokt.community import Community, create_policy, RIGHTS
from ziokt.community_privacy import mailbox_public
from ziokt.component_links import ComponentLinks, COMPONENTS
from ziokt.protocol import ProtocolError
from ziokt.security import sign

class ComponentPairExchange(unittest.TestCase):
    def test_all_110_pairs_survive_replication_without_executing_payloads(self):
        names=sorted(COMPONENTS)
        signing={name:secrets.token_bytes(32) for name in names}
        boxes={name:secrets.token_bytes(32) for name in names}
        public={name:sign({},key,'test')['public_key'] for name,key in signing.items()}
        owner=names[0];policy=create_policy(signing[owner],'component-lab',{key:sorted(RIGHTS) for key in public.values()});community_key=secrets.token_bytes(32)
        def peers(name):return {other:{'signing_public':public[other],'mailbox_public':mailbox_public(boxes[other]),'kinds':['file','simulation']} for other in names if other!=name}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with Community(root/'a',policy,public[owner],community_key) as a,Community(root/'b',policy,public[owner],community_key) as b:
                senders={name:ComponentLinks(a,name,signing[name],boxes[name],peers(name),root/'send'/name) for name in names}
                receivers={name:ComponentLinks(b,name,signing[name],boxes[name],peers(name),root/'receive'/name) for name in names}
                offers=[]
                for source in names:
                    for target in names:
                        if source==target:continue
                        operation=f'{source}-to-{target}';data=f'private artifact {operation}; imported code is data'.encode()
                        offer=senders[source].send(target,'file','artifacts/item.bin',data,operation)
                        offers.append((source,target,operation,data,offer))
                self.assertEqual(len(offers),110)
                checkpoint=a.checkpoint(signing[owner]);self.assertNotIn(b'private artifact',checkpoint)
                b.restore(checkpoint,public[owner])
                for source,target,operation,data,offer in offers:
                    result=receivers[target].receive(offer['event'],expected_source=source)
                    self.assertEqual(result['data'],data);self.assertFalse(result['duplicate']);self.assertFalse(result['auto_executed'])
                source,target,operation,data,offer=offers[0]
                again=senders[source].send(target,'file','artifacts/item.bin',data,operation)
                self.assertEqual(again['event'],offer['event']);self.assertTrue(again['duplicate'])
                self.assertTrue(receivers[target].receive(offer['event'],expected_source=source)['duplicate'])
                with self.assertRaises(ProtocolError):senders[source].send(target,'file','artifacts/item.bin',b'conflict',operation)
                with self.assertRaises(ProtocolError):senders[source].send(target,'profile','artifact',b'x','denied')
                wrong=next(name for name in names if name not in {source,target})
                with self.assertRaises(ProtocolError):receivers[wrong].receive(offer['event'],expected_source=source)
                with self.assertRaises(ProtocolError):receivers[target].receive(offer['event'],expected_source=wrong)

    def test_tc16_package_ufs_ano_and_tri_combined_flow(self):
        from ziokt.ano import defence,law_report
        from ziokt.tc16 import TC16_CPU, TCCCompiler, assemble
        from ziokt.tri import project_bundle,read_project
        from ziokt.ufsdcpm import IntegratedStorage,read_package
        from ziokt.safefs import Vault
        from ziokt.protocol import encoded,strict_json
        program=assemble(TCCCompiler().compile('int main() { return 65535 + 2; }'))
        cpu=TC16_CPU();cpu.load_program(program);execution=cpu.run(max_cycles=1000)
        self.assertTrue(execution['halted']);self.assertEqual(cpu.registers[0],1)
        tri=project_bundle('HALT',{'tc16_result':cpu.registers[0],'word_bits':16})
        decision=defence({'bounded_execution':execution['halted'],'sixteen_bits':cpu.registers[0]==1},('bounded_execution','sixteen_bits'))
        self.assertEqual(decision['decision'],'allow')
        private=secrets.token_bytes(32);public=sign({},private,'test')['public_key'];policy=create_policy(private,'pipeline',{public:sorted(RIGHTS)});key=secrets.token_bytes(32)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);storage=IntegratedStorage(Vault(root/'ufs','ufsdcpm',secrets.token_bytes(32)))
            with Community(root/'a',policy,public,key) as a,Community(root/'b',policy,public,key) as b:
                item=storage.publish_package('simulation','1',{'tc16/program.bin':program,'tri/project.json':tri,'ano/laws.json':encoded(law_report()),'ano/decision.json':encoded(decision)},[],private,community=a)
                _,package=storage.vault.get(item['digest']);manifest,files=read_package(package,public)
                b.restore(a.checkpoint(private),public)
                self.assertEqual(read_project(files['tri/project.json'])['state']['tc16_result'],1)
                self.assertEqual(files['tc16/program.bin'],program)
                self.assertFalse(strict_json(files['ano/laws.json'])['security_policy_proof'])
                event=b.view('files')['events'][0];sealed=b.get_file(event['body'])
                self.assertNotIn(program,sealed);self.assertEqual(storage.vault.open(sealed)[1],package)

    def test_application_bridge_uses_pinned_pair_capabilities_and_scoped_receipts(self):
        from ziokt.companion_bridge import CompanionBridge
        from ziokt.cli import write_exclusive,write_binary_exclusive
        from ziokt.safefs import Vault
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);names=('tc16','tri');signing={n:secrets.token_bytes(32) for n in names};boxes={n:secrets.token_bytes(32) for n in names};appkeys={n:secrets.token_bytes(32) for n in names}
            public={n:sign({},signing[n],'test')['public_key'] for n in names};policy=create_policy(signing['tc16'],'linked-apps',{p:sorted(RIGHTS) for p in public.values()});shared=secrets.token_bytes(32)
            bridges={}
            for name in names:
                directory=root/name;directory.mkdir(mode=0o700);(directory/'vault').mkdir(mode=0o700)
                for key,data in [('signing',signing[name]),('mailbox',boxes[name]),('application',appkeys[name]),('encryption',shared)]:write_binary_exclusive(directory/(key+'.key'),data)
                write_exclusive(directory/'policy.json',policy);peer=names[1] if name==names[0] else names[0]
                config={'schema':'ziokt.companion-bridge.v1','application':name,'community_root':str(root/'community'),'owner':public['tc16'],'policy':str(directory/'policy.json'),'signing_key':str(directory/'signing.key'),'encryption_key':str(directory/'encryption.key'),'application_key':str(directory/'application.key'),'vault_root':str(directory/'vault'),'exchange_key':str(directory/'mailbox.key'),'component_peers':{peer:{'signing_public':public[peer],'mailbox_public':mailbox_public(boxes[peer]),'kinds':['compute-result']}}}
                write_exclusive(directory/'bridge.json',config);bridges[name]=CompanionBridge(directory/'bridge.json');self.addCleanup(bridges[name].close)
            source=Vault(root/'tc16/vault','tc16',appkeys['tc16']);original=source.put('results/result.json',b'{"word_bits":16,"result":1}')
            offer=bridges['tc16'].call('component.send',{'target':'tri','kind':'compute-result','digest':original['digest'],'operation':'result-1'})
            before=len(bridges['tri'].community.view('files')['events'])
            received=bridges['tri'].call('component.receive',{'event':offer['event'],'source':'tc16'})
            dest=Vault(root/'tri/vault','tri',appkeys['tri']);self.assertEqual(dest.get(received['digest'])[1],b'{"word_bits":16,"result":1}');self.assertFalse(received['auto_executed'])
            again=bridges['tri'].call('component.receive',{'event':offer['event'],'source':'tc16'});self.assertTrue(again['duplicate']);self.assertEqual(again['digest'],received['digest'])
            self.assertEqual(received['schema'],again['schema']);self.assertEqual(received['schema'],'ziokt.component-delivery.v1')
            self.assertEqual(len(bridges['tri'].community.view('files')['events']),before)
            with self.assertRaises(ProtocolError):source.open(dest.blob(received['digest']))

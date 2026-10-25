import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from ziokt import bundle,programs
from ziokt.protocol import ProtocolError,encoded


class DistributionTests(unittest.TestCase):
    def test_three_native_targets_preserve_bytes_and_require_publisher_trust(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);artifacts=[]
            for target in sorted(bundle.TARGETS):
                name=target+'.native';(root/name).write_bytes(('signed-native-'+target).encode());artifacts.append({'target':target,'file':name})
            spec={'schema':'ziokt.package-spec.v1','name':'tests/demo','version':'1.0.0','dependencies':[],'artifacts':artifacts}
            path=root/'demo.zpkg';report=bundle.build(spec,root,b'k'*32,path);manifest=bundle.inspect(path,report['publisher'])
            self.assertEqual(len(manifest['artifacts']),3)
            for target in bundle.TARGETS:
                stage=root/target;bundle.extract(path,report['publisher'],target,stage)
                self.assertEqual((stage/(target+'.native')).read_bytes(),(root/(target+'.native')).read_bytes())
                with self.assertRaises(ProtocolError):bundle.extract(path,report['publisher'],target,stage)
            with self.assertRaises(ProtocolError):bundle.inspect(path,'a'*64)
            corrupt=root/'corrupt.zpkg'
            with zipfile.ZipFile(path) as src,zipfile.ZipFile(corrupt,'w') as dst:
                for entry in src.infolist():dst.writestr(entry,src.read(entry) if entry.filename=='manifest.json' else b'X'*entry.file_size)
            with self.assertRaises(ProtocolError):bundle.inspect(corrupt,report['publisher'])

    def test_path_escape_symlinks_and_unknown_backends_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'native').write_bytes(b'native');(root/'alias').symlink_to(root/'native')
            base={'schema':'ziokt.package-spec.v1','name':'demo','version':'1.0.0','artifacts':[{'target':'dcpm','file':'native'}]}
            for target,path in [('dcpm','../native'),('dcpm','alias'),('shell','native')]:
                spec=copy.deepcopy(base);spec['artifacts']=[{'target':target,'file':path}]
                with self.subTest(target=target,path=path),self.assertRaises(ProtocolError):bundle.build(spec,root,b'k'*32,root/'bad.zpkg')

    def test_standalone_tcc_compiles_executes_and_binds_source_and_target(self):
        value=programs.compile_program('int main(){return 6*7;}','tc16-tcc')
        manifest,payload=programs.read_program(encoded(value),'tc16-tcc')
        self.assertEqual(programs.execute_package(payload)['registers'][0],42)
        with self.assertRaises(ProtocolError):programs.read_program(encoded(value),'etp-tc16-tcc')
        changed=copy.deepcopy(value);changed['source']='int main(){return 43;}';changed['source_sha256']=hashlib.sha256(changed['source'].encode()).hexdigest()
        with self.assertRaises(ProtocolError):programs.read_program(encoded(changed),'tc16-tcc')
        changed=copy.deepcopy(value);changed['payload_sha256']='0'*64
        with self.assertRaises(ProtocolError):programs.read_program(encoded(changed),'tc16-tcc')

    def test_tri_preserves_its_signed_opcodes_labels_and_target_identity(self):
        source='start: LOADI 42\nSTORE 20\nJMP done\nLOADI -1\ndone: HALT'
        value=programs.compile_program(source,'tri',syntax='assembly');_,payload=programs.read_program(encoded(value),'tri')
        memory=json.loads(payload)['memory'];self.assertEqual(memory[:4],[20,42,-1,20]);self.assertEqual(memory[-1],0)
        for code in ('UNKNOWN 1','LOADI 1junk','a: HALT\na: HALT','LOADI 9007199254740992'):
            with self.subTest(code=code),self.assertRaises(ProtocolError):programs.compile_program(code,'tri',syntax='assembly')
        self.assertEqual(value['isa'],'tri-simulator-v1')
        with self.assertRaises(ProtocolError):programs.read_program(encoded(value),'tc16-tcc')

    def test_etp_frontend_requires_the_explicit_native_compiler(self):
        with self.assertRaises(ProtocolError):programs.compile_program('int main(){return 42;}','etp-tc16-tcc')


if __name__=='__main__':unittest.main()

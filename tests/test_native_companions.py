"""Invoke the real Shadow6 and Corium command paths against installed Ziokt APIs."""
import json
import os
import secrets
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeCompanionCalls(unittest.TestCase):
    def test_native_commands_dispatch_catalog_algebra_and_cpu(self):
        providers = [
            [sys.executable, str(ROOT.parent/'Shadow6/CLI/shadow6.py'), 'ziokt'],
            ['bash', str(ROOT.parent/'Corium/corix_v108.sh'), 'ziokt'],
        ]
        env = {**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1'}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'main.c'
            source.write_text('int main() { return 65535 + 2; }')
            key=Path(directory)/'vault.key';key.write_bytes(secrets.token_bytes(32));key.chmod(0o600)
            assembly=Path(directory)/'program.asm';assembly.write_text('HALT')
            payload=Path(directory)/'payload.bin';payload.write_bytes(b'private native companion roundtrip')
            package_dir=Path(directory)/'package';package_dir.mkdir();(package_dir/'item.txt').write_text('bounded package')
            for index,provider in enumerate(providers):
                def invoke(arguments):
                    result=subprocess.run([*provider,'companion',*map(str,arguments)],env=env,cwd=directory,capture_output=True,text=True,timeout=15)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    return json.loads(result.stdout)
                local=Path(directory)/str(index)
                flags=['--root',local,'--key',key]
                sealed=invoke(['safefs','put',*flags,'--scope','native','--input',payload,'--name','item.bin'])
                output=Path(directory)/f'restored-{index}.bin'
                invoke(['safefs','get',*flags,'--scope','native','--digest',sealed['digest'],'--output',output])
                self.assertEqual(output.read_bytes(),payload.read_bytes())
                project=invoke(['tri','put',*flags,'--input',assembly])
                invoke(['tri','get',*flags,'--digest',project['digest'],'--output',Path(directory)/f'tri-{index}.json'])
                packed=invoke(['ufsdcpm','put',*flags,'--scope','native-packages','--directory',package_dir,'--name','fixture','--version','1','--signing-key',key])
                self.assertIn('digest',packed)

                for args in (['catalog'], ['ano', 'laws'], ['tc16','run','--syntax','tcc','--input',str(source)]):
                    result = subprocess.run([*provider, 'companion', *args], env=env,
                        cwd=directory, capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    if args[0] == 'catalog':
                        self.assertEqual(len(json.loads(result.stdout)['components']),11)
                    elif args[0] == 'tc16':
                        state=json.loads(result.stdout);self.assertTrue(state['halted']);self.assertEqual(state['registers'][0],1)
                    elif args[0] == 'ano':
                        self.assertFalse(json.loads(result.stdout)['security_policy_proof'])
                bad = subprocess.run([*provider, 'companion', 'unknown-component'], env=env,
                    cwd=directory, capture_output=True, timeout=15)
                self.assertNotEqual(bad.returncode,0)

"""AirGap tests run in fresh processes; activation cannot be undone in process."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AirGapTests(unittest.TestCase):
    def run_script(self, source, *, offline=False):
        env = dict(os.environ)
        env.pop('ZIOKT_AIRGAP', None)
        if offline:
            env['ZIOKT_AIRGAP'] = '1'
        result = subprocess.run([sys.executable, '-c', source], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_blocks_network_dns_native_and_child_execution_before_side_effects(self):
        self.run_script('''
import os, socket, subprocess
from ziokt.runtime_policy import activate_airgap, status
from ziokt.protocol import ProtocolError
from ziokt.carrier import open_carrier
from ziokt.client import exchange
from ziokt.etp import EtpGateway
from ziokt.transport import NativeTransport
s = socket.socket()
activate_airgap()
os.environ.pop('ZIOKT_AIRGAP')
assert status()['mode'] == 'airgap'
operations = [lambda: socket.socket(), lambda: socket.getaddrinfo('example.invalid',443),
 lambda: s.bind(('127.0.0.1',0)), lambda: s.connect(('127.0.0.1',9)),
 lambda: subprocess.run(['should-never-execute']), lambda: os.system('exit 99'),
 lambda: open_carrier('example.invalid',443), lambda: exchange({},{}),
 lambda: EtpGateway.call(None,'etp.stats',{}), lambda: NativeTransport(None).open('anything')]
for operation in operations:
 try: operation()
 except ProtocolError as error: assert error.code == 'AIRGAP_DENIED'
 else: raise AssertionError('AirGap bypass')
s.close()
''')

    def test_cli_environment_and_flag(self):
        self.run_script('''
from ziokt.cli import main
assert main(['airgap']) == 0
''')
        self.run_script('''
from ziokt.cli import main
assert main(['--airgap','companion','ano','laws']) == 0
''')
        self.run_script('''
from ziokt.runtime_policy import status, require_network
from ziokt.protocol import ProtocolError
assert status()['mode'] == 'airgap'
try: require_network()
except ProtocolError as error: assert error.code == 'AIRGAP_DENIED'
else: raise AssertionError('environment ignored')
''', offline=True)

    def test_offline_algebra_cpu_and_all_component_pairs_remain_usable(self):
        self.run_script('''
import unittest
from ziokt.runtime_policy import status
assert status()['mode'] == 'airgap'
suite = unittest.TestSuite(unittest.defaultTestLoader.discover('tests', pattern=p)
 for p in ('test_ano_laws.py', 'test_tc16.py', 'test_component_links.py'))
result = unittest.TextTestRunner().run(suite)
assert result.wasSuccessful()
''', offline=True)

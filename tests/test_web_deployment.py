"""Generate private deployable configs and exercise the actual application bridge."""
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from ziokt.companion_bridge import CompanionBridge
class WebDeployment(unittest.TestCase):
 def test_federated_and_standalone_bootstrap_preserve_existing_state(self):
  with tempfile.TemporaryDirectory() as tmp:
   for app in ['watchat','sim-manager']:
    root=Path(tmp)/app
    command=[sys.executable,'tools/configure_web_gateway.py','--root',str(root),'--origin','https://web.example.test','--port','8182','--application',app]
    result=subprocess.run(command,capture_output=True,text=True,timeout=10);self.assertEqual(result.returncode,0,result.stderr)
    self.assertEqual(root.stat().st_mode&0o777,0o700)
    self.assertEqual((root/'service.env').stat().st_mode&0o777,0o600)
    with_bridge=CompanionBridge(root/'bridge.json')
    try:self.assertEqual(with_bridge.call('component.status',{})['application'],app)
    finally:with_bridge.close()
    old=(root/'service.env').read_bytes();self.assertNotEqual(subprocess.run(command,capture_output=True,timeout=10).returncode,0);self.assertEqual((root/'service.env').read_bytes(),old)
   command[command.index(str(root))]=str(Path(tmp)/'standalone');command.append('--standalone')
   self.assertEqual(subprocess.run(command,capture_output=True,timeout=10).returncode,0)
   self.assertIn('ZIOKT_STANDALONE="1"',(Path(tmp)/'standalone/service.env').read_text())
   self.assertFalse((Path(tmp)/'standalone/bridge.json').exists())

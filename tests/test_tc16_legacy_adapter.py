"""Controlled IPC unit cases; actual native compilation is exclusively CI evidence."""
import base64,hashlib,json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ziokt.protocol import ProtocolError
from ziokt.tc16_spec import compile_package
from ziokt.tc16_legacy import compile_native

class NativeAdapterTests(unittest.TestCase):
    def test_pinned_snapshot_and_machine_checked_reference_result(self):
        with tempfile.TemporaryDirectory() as area:
            binary=Path(area)/'fixture';binary.write_bytes(b'not-executed-native-IPC-fixture');binary.chmod(0o700)
            source='int main(){return 42;}'
            frame={'ok':True,'result':{'schema':'etp.legacy-compiled.v1','semantic_profile':'etp-legacy-pure-return-v1','source_sha256':hashlib.sha256(source.encode()).hexdigest(),'compiler':'etp-native-legacy-unified-v1','package':base64.b64encode(compile_package(source)).decode(),'debug':{'functions':{'main':4}},'legacy_result':42}}
            settings={'binary':str(binary),'sha256':'sha256:'+hashlib.sha256(binary.read_bytes()).hexdigest()}
            def response(command,**kwargs):
                self.assertNotEqual(command[0],str(binary));self.assertEqual(Path(command[0]).read_bytes(),binary.read_bytes())
                return subprocess.CompletedProcess(command,0,json.dumps(frame).encode())
            with patch('ziokt.tc16_legacy.subprocess.run',side_effect=response):
                self.assertFalse(compile_native(source,settings)['execution_authorized'])
                frame['result']['legacy_result']=43
                with self.assertRaises(ProtocolError) as mismatch:compile_native(source,settings)
                self.assertEqual(mismatch.exception.code,'ETP_LEGACY_DIVERGENCE')
                frame.clear();frame.update(ok=False,error={'code':'ETP_LEGACY_COMPILE','message':'unsupported native feature'})
                with self.assertRaises(ProtocolError) as rejected:compile_native(source,settings)
                self.assertEqual(rejected.exception.code,'ETP_LEGACY_COMPILE')
            with patch('ziokt.tc16_legacy.subprocess.run') as process:
                with self.assertRaises(ProtocolError):compile_native(source,{**settings,'sha256':'sha256:'+'0'*64})
                process.assert_not_called()
            with self.assertRaises(ProtocolError):compile_native(source,None)

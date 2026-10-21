"""Serial parsing unit tests; no QEMU or compilation is run locally."""
import importlib.util,re,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('qemu_boot',Path(__file__).resolve().parents[1]/'ci/openci/qemu_boot.py');qemu=importlib.util.module_from_spec(spec);spec.loader.exec_module(qemu)

class MarkerTests(unittest.TestCase):
    def test_serial_cr_expansion_and_input_echo(self):
        pattern=qemu.marker_pattern('BOOT_OK')
        for line in ['OPENCI_BOOT_OK\n','OPENCI_BOOT_OK\r\n','OPENCI_BOOT_OK\r\r\n']:
            self.assertIsNotNone(re.search(pattern,line))
        for line in ["printf 'OPENCI_%s\\n' BOOT_OK\r\r\n",'prefixOPENCI_BOOT_OK\n','OPENCI_BOOT_OKbad\n']:
            self.assertIsNone(re.search(pattern,line))

import unittest
from ziokt.tc16_spec import package,unpack,compile_package,execute_package,contract
from ziokt.tc16 import assemble
from ziokt.protocol import ProtocolError

class SpecTests(unittest.TestCase):
 def test_targets_never_autodetected(self):
  code=assemble('MOVI R0, 42\nHALT')
  self.assertEqual(execute_package(package(code))['registers'][0],42)
  with self.assertRaises(ProtocolError):execute_package(package(code,'tc16-etp-legacy'))
  with self.assertRaises(ProtocolError):unpack(code)
  with self.assertRaises(ProtocolError):contract({'isa_id':'tc16-unified-v1'})
 def test_compile_and_syscall_profile(self):
  result=execute_package(compile_package('int main(){ return 65535 + 2; }'))
  self.assertEqual(result['registers'][0],1);self.assertTrue(result['halted'])
  code=assemble('MOVI R0, 7\nSYS 1\nHALT')
  self.assertEqual(execute_package(package(code))['exception'],'TC16_CAPABILITY')
  self.assertEqual(execute_package(package(code,profile='stdout-u16-v1'))['output'],['7'])
 def test_header_digest(self):
  blob=bytearray(package(assemble('HALT')));blob[-1]=1
  with self.assertRaises(ProtocolError):unpack(bytes(blob))

if __name__=='__main__':unittest.main()

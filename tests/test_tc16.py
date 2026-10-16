import unittest
from ziokt.tc16 import TC16_CPU,assemble,TCCCompiler
from ziokt.protocol import ProtocolError

class TC16Tests(unittest.TestCase):
    def execute(self,source,budget=10000):
        cpu=TC16_CPU();cpu.load_program(assemble(source));result=cpu.run(max_cycles=budget);return cpu,result
    def test_true_word_arithmetic_all_registers_and_flags(self):
        cpu,result=self.execute('MOVI R15, 65535\nMOVI R14, 1\nADD R15, R14\nHALT')
        self.assertEqual(cpu.registers[15],0);self.assertTrue(cpu.flags&cpu.FLAG_C);self.assertTrue(cpu.flags&cpu.FLAG_Z)
        cpu,_=self.execute('MOVI R0, 32767\nMOVI R1, 1\nADD R0, R1\nHALT')
        self.assertEqual(cpu.registers[0],32768);self.assertTrue(cpu.flags&cpu.FLAG_O);self.assertTrue(cpu.flags&cpu.FLAG_S)
        cpu,_=self.execute('MOVI R0, 0\nMOVI R1, 1\nSUB R0, R1\nHALT')
        self.assertEqual(cpu.registers[0],65535);self.assertTrue(cpu.flags&cpu.FLAG_C)
        cpu.reset();self.assertEqual(len(cpu.registers),16)
    def test_word_memory_byte_memory_stack_calls_and_shift(self):
        cpu,result=self.execute('MOVI R0, 1024\nMOVI R1, 4660\nSTORE R0, R1\nLOAD R12, R0\nLOADB R11, R0\nPUSH R12\nPOP R13\nCALL twice\nHALT\ntwice: SHL R13, 1\nRET')
        self.assertEqual(cpu.memory[1024:1026],bytes.fromhex('3412'));self.assertEqual(cpu.registers[12],4660);self.assertEqual(cpu.registers[11],52);self.assertEqual(cpu.registers[13],9320);self.assertEqual(cpu.stack_depth,0)
    def test_bcd_modes_parity_and_syscall_capabilities(self):
        cpu,_=self.execute('MOVI R0, 0x9999\nMOVI R1, 1\nBCDADD R0, R1\nHALT');self.assertEqual(cpu.registers[0],0);self.assertTrue(cpu.flags&cpu.FLAG_C)
        cpu,_=self.execute('SETMODE 1\nMOVI R0, 0x1234\nMOVI R1, 1\nADD R0, R1\nHALT');self.assertEqual(cpu.registers[0],0x1235)
        with self.assertRaises(ProtocolError):self.execute('MOVI R0, 0xabcd\nMOVI R1, 1\nBCDADD R0, R1')
        with self.assertRaises(ProtocolError):self.execute('SYS 1')
        cpu=TC16_CPU(syscalls={7:lambda cpu:cpu.registers.__setitem__(0,1024)});cpu.load_program(assemble('SYS 7\nHALT'));cpu.run();self.assertEqual(cpu.registers[0],1024)
    def test_interrupt_and_hard_limits(self):
        cpu,result=self.execute('loop: JMP loop',10);self.assertTrue(result['budget_exhausted']);self.assertEqual(result['cycles'],10)
        with self.assertRaises(ProtocolError):self.execute('POP R0')
        with self.assertRaises(ProtocolError):self.execute('MOVI R0, 65535\nLOAD R1, R0')
        for source in ('BOGUS R0','MOVI R16, 1','MOVI R0, 65536','SHL R0, 16','JMP missing','x: NOP\nx: HALT'):
            with self.assertRaises(ProtocolError):assemble(source)
        cpu=TC16_CPU();cpu.load_program(assemble('EI\nHALT'));cpu.step();cpu.memory[100]=37
        self.assertTrue(cpu.interrupt(100));cpu.step();self.assertEqual(cpu.pc,1);self.assertTrue(cpu.flags&cpu.FLAG_I);self.assertEqual(cpu.stack_depth,0)
    def test_tcc_functions_recursion_loops_and_short_circuit(self):
        compiler=TCCCompiler()
        for source,expected in [
            ('int add(int a,int b){return a+b;} int main(){int x=1000;int y=24;return add(x,y);}',1024),
            ('int fact(int n){if(n<=1){return 1;}return n*fact(n-1);} int main(){return fact(6);}',720),
            ('int main(){word x=0;word i=0;while(i<100){i=i+1;if(i==50){continue;}x=x+i;}return x;}',5000),
            ('int main(){byte x=1025;bool y=42;return x+y;}',2),
            ('int main(){return (0 && (1/0)) + (1 || (1/0));}',1),
            ('int main(){return (3>2)+(3>=3)+(2<3)+(2<=2)+(3!=2);}',5)]:
            cpu,result=self.execute(compiler.compile(source));self.assertTrue(result['halted']);self.assertEqual(cpu.registers[0],expected);self.assertEqual(cpu.stack_depth,0)
        for source in ('int main(){return missing;}','int main(){return unknown();}','int main(){int x=1;int x=2;return x;}','int main(){break;}'):
            with self.assertRaises(ProtocolError):compiler.compile(source)

    def test_tcc_truncated_and_oversized_literals_reject_as_protocol_errors(self):
        compiler=TCCCompiler()
        for source in ('int main()', 'int main(', 'int main(){if(', 'int main(){return', 'int main(){x', 'int main(){return '+('9'*5000)+';}'):
            with self.subTest(source=source[:40]),self.assertRaises(ProtocolError):compiler.compile(source)
        cpu,result=self.execute(compiler.compile('int main(){return '+('0'*5000)+'1;}'))
        self.assertEqual(cpu.registers[0],1);self.assertTrue(result['halted'])

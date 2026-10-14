"""TC-16: 16-bit registers/data, byte-addressed memory, explicit versioned ISA.

Programs cannot access host files/network. System calls are explicit capabilities.
TC-15 source is preserved; its conflicting byte encoding is not auto-detected.
"""
import re
from .protocol import ProtocolError

MASK=0xffff
OPS={name:i for i,name in enumerate(('HALT','MOV','MOVI','LOAD','STORE','LOADB','STOREB','ADD','SUB','AND','OR','XOR','NOT','INC','DEC','CMP','SHL','SHR','SWAP','PUSH','POP','JMP','JZ','JC','JP','JO','CALL','RET','BCDADD','BCDSUB','SETFLAG','CLRFLAG','SETMODE','SYS','NOP','MUL','DIV','RETI','EI','DI','GETSP','SETSP','JNZ','PARITY'))}
PAIR={'MOV','LOAD','STORE','LOADB','STOREB','ADD','SUB','AND','OR','XOR','CMP','SWAP','BCDADD','BCDSUB','MUL','DIV'}
REG={'NOT','INC','DEC','PUSH','POP','GETSP','SETSP','PARITY'}
IMM={'JMP','JZ','JNZ','JC','JP','JO','CALL','SETFLAG','CLRFLAG','SETMODE','SYS'}
ZERO={'HALT','RET','RETI','NOP','EI','DI'}
ALIASES={'LOADI':'MOVI','LOAD16':'MOVI','LOADX':'LOAD','STOREX':'STORE','MOVX':'MOV','ADD16':'ADD','SUB16':'SUB'}


def _register(value):
    if not re.fullmatch(r'R(?:[0-9]|1[0-5])',value.upper()):raise ProtocolError('INVALID_TC16','register R0..R15 required')
    return int(value[1:])


def assemble(source):
    if not isinstance(source,str) or len(source.encode())>65536:raise ProtocolError('TC16_LIMIT','bounded assembly required')
    rows=[];labels={};pc=0
    for raw in source.splitlines():
        line=raw.split(';')[0].strip()
        if not line:continue
        if ':' in line:
            name,line=line.split(':',1);name=name.strip()
            if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}',name) or name in labels:raise ProtocolError('INVALID_TC16','unique label required')
            labels[name]=pc;line=line.strip()
            if not line:continue
        parts=line.replace(',',' ').replace('[','').replace(']','').split();op=ALIASES.get(parts[0].upper(),parts[0].upper());args=parts[1:]
        if op not in OPS:raise ProtocolError('INVALID_TC16','unknown instruction')
        count=2 if op in PAIR or op in {'MOVI','SHL','SHR'} else 1 if op in REG|IMM else 0
        if len(args)!=count:raise ProtocolError('INVALID_TC16','instruction operand count mismatch')
        size=1 if op in ZERO else 3 if op in IMM else 4 if op=='MOVI' else 3 if op in {'SHL','SHR'} else 2
        rows.append((op,args));pc+=size
        if pc>65536:raise ProtocolError('TC16_LIMIT','program exceeds memory')
    code=bytearray()
    def number(value):
        try:v=labels[value] if value in labels else int(value,0)
        except ValueError:raise ProtocolError('INVALID_TC16','known label or integer required')
        if not -32768<=v<=65535:raise ProtocolError('INVALID_TC16','16-bit operand required')
        return v&MASK
    for op,args in rows:
        code.append(OPS[op])
        if op in PAIR:code.append((_register(args[0])<<4)|_register(args[1]))
        elif op in REG:code.append(_register(args[0]))
        elif op=='MOVI':code.append(_register(args[0]));code.extend(number(args[1]).to_bytes(2,'little'))
        elif op in {'SHL','SHR'}:
            n=number(args[1])
            if n>15:raise ProtocolError('INVALID_TC16','shift count 0..15 required')
            code.extend((_register(args[0]),n))
        elif op in IMM:code.extend(number(args[0]).to_bytes(2,'little'))
    return bytes(code)


class TC16_CPU:
    FLAG_Z=1;FLAG_C=2;FLAG_S=4;FLAG_O=8;FLAG_T=16;FLAG_I=32;FLAG_H=64;FLAG_P=128
    MODE_STANDARD=0;MODE_BCD=1;MODE_DEBUG=2
    def __init__(self,memory_size=65536,debug=False,syscalls=None):
        if type(memory_size) is not int or not 256<=memory_size<=65536:raise ProtocolError('INVALID_TC16','bounded byte memory required')
        self.memory=bytearray(memory_size);self.debug=bool(debug);self.syscalls=dict(syscalls or {});self.reset()
    def reset(self):
        self.registers=[0]*16;self.pc=0;self.sp=len(self.memory);self.flags=0;self.mode=0;self.running=False;self.cycles=0;self.trace=[]
        self.stack_depth=0
    def _address(self,address,size=1):
        if type(address) is not int or not 0<=address<=len(self.memory)-size:raise ProtocolError('TC16_MEMORY','memory boundary exceeded')
        return address
    def load_program(self,program,start_address=0):
        if not isinstance(program,bytes) or not program:raise ProtocolError('INVALID_TC16','nonempty TC-16 bytes required')
        self._address(start_address,len(program));self.memory[start_address:start_address+len(program)]=program
    def fetch_byte(self):
        self._address(self.pc);v=self.memory[self.pc];self.pc+=1;return v
    def fetch_16bit_operand(self):return self.fetch_byte()|(self.fetch_byte()<<8)
    def read_word(self,address):
        self._address(address,2);return int.from_bytes(self.memory[address:address+2],'little')
    def write_word(self,address,value):
        self._address(address,2);self.memory[address:address+2]=(value&MASK).to_bytes(2,'little')
    def push(self,value):
        self._address(self.sp-2,2);self.sp-=2;self.write_word(self.sp,value);self.stack_depth+=1
    def pop(self):
        if not self.stack_depth:raise ProtocolError('TC16_STACK','stack underflow')
        value=self.read_word(self.sp);self.sp+=2;self.stack_depth-=1;return value
    def _flags(self,result,carry=False,overflow=False,half=False):
        value=result&MASK
        self.flags=(self.flags&(self.FLAG_I|self.FLAG_T))|(self.FLAG_Z if value==0 else 0)|(self.FLAG_S if value&0x8000 else 0)|(self.FLAG_P if value.bit_count()%2==0 else 0)|(self.FLAG_C if carry else 0)|(self.FLAG_O if overflow else 0)|(self.FLAG_H if half else 0)
        return value
    def _bcd(self,a,b,subtract=False):
        def decimal(v):
            digits=[(v>>(4*i))&15 for i in range(4)]
            if any(d>9 for d in digits):raise ProtocolError('TC16_BCD','invalid packed decimal')
            return sum(d*10**i for i,d in enumerate(digits))
        n=decimal(a)-decimal(b) if subtract else decimal(a)+decimal(b);v=n%10000
        packed=sum((v//10**i%10)<<(4*i) for i in range(4))
        return self._flags(packed,n<0 or n>=10000)
    def step(self):
        opcode=self.fetch_byte()
        if opcode>=len(OPS):raise ProtocolError('INVALID_TC16','unknown bytecode opcode')
        op=tuple(OPS)[opcode];dst=src=imm=0
        if op in PAIR:
            arg=self.fetch_byte();dst=arg>>4;src=arg&15
        elif op in REG or op in {'MOVI','SHL','SHR'}:
            dst=self.fetch_byte()
            if dst>15:raise ProtocolError('INVALID_TC16','invalid register encoding')
            if op=='MOVI':imm=self.fetch_16bit_operand()
            elif op in {'SHL','SHR'}:
                imm=self.fetch_byte()
                if imm>15:raise ProtocolError('INVALID_TC16','invalid shift encoding')
        elif op in IMM:imm=self.fetch_16bit_operand()
        a=self.registers[dst];b=self.registers[src]
        if op=='HALT':self.running=False
        elif op=='MOV':self.registers[dst]=b
        elif op=='MOVI':self.registers[dst]=imm
        elif op in {'LOAD','LOADB'}:self.registers[dst]=self.read_word(b) if op=='LOAD' else self.memory[self._address(b)]
        elif op in {'STORE','STOREB'}:
            if op=='STORE':self.write_word(a,b)
            else:self.memory[self._address(a)]=b&255
        elif op in {'ADD','SUB','INC','DEC','CMP'}:
            subtract=op in {'SUB','DEC','CMP'};b=1 if op in {'INC','DEC'} else b;r=a-b if subtract else a+b
            overflow=bool(((a^b) if subtract else ~(a^b))&(a^r)&0x8000)
            value=self._bcd(a,b,subtract) if self.mode==1 and op!='CMP' else self._flags(r,r<0 or r>MASK,overflow,(a&15)<(b&15) if subtract else (a&15)+(b&15)>15)
            if op!='CMP':self.registers[dst]=value
        elif op in {'AND','OR','XOR','NOT'}:self.registers[dst]=self._flags({'AND':a&b,'OR':a|b,'XOR':a^b,'NOT':~a}[op])
        elif op in {'SHL','SHR'}:
            carry=bool(a&(1<<(16-imm))) if op=='SHL' and imm else bool(a&(1<<(imm-1))) if imm else bool(self.flags&self.FLAG_C)
            self.registers[dst]=self._flags(a<<imm if op=='SHL' else a>>imm,carry)
        elif op=='SWAP':self.registers[dst],self.registers[src]=b,a
        elif op=='PUSH':self.push(a)
        elif op=='POP':self.registers[dst]=self.pop()
        elif op=='PARITY':
            self.flags=(self.flags&~self.FLAG_P)|(self.FLAG_P if a.bit_count()%2==0 else 0)
        elif op=='GETSP':self.registers[dst]=self.sp&MASK
        elif op=='SETSP':
            if a%2 or a>len(self.memory):raise ProtocolError('TC16_STACK','invalid stack pointer')
            self.sp=a;self.stack_depth=(len(self.memory)-a)//2
        elif op in {'JMP','JZ','JNZ','JC','JP','JO','CALL'}:
            take=op in {'JMP','CALL'} or (op=='JNZ' and not self.flags&1) or bool(self.flags&{'JZ':1,'JC':2,'JP':128,'JO':8}.get(op,0))
            if take:
                self._address(imm)
                if op=='CALL':self.push(self.pc)
                self.pc=imm
        elif op=='RET':self.pc=self.pop();self._address(self.pc)
        elif op=='RETI':self.flags=self.pop()&255;self.pc=self.pop();self._address(self.pc)
        elif op in {'BCDADD','BCDSUB'}:self.registers[dst]=self._bcd(a,b,op=='BCDSUB')
        elif op=='SETFLAG':self.flags|=imm&255
        elif op=='CLRFLAG':self.flags&=~(imm&255)
        elif op=='SETMODE':
            if imm>2:raise ProtocolError('INVALID_TC16','unknown CPU mode')
            self.mode=imm
        elif op=='EI':self.flags|=self.FLAG_I
        elif op=='DI':self.flags&=~self.FLAG_I
        elif op=='SYS':
            if imm not in self.syscalls:raise ProtocolError('TC16_CAPABILITY','system call not granted')
            self.syscalls[imm](self)
        elif op=='MUL':self.registers[dst]=self._flags(a*b,a*b>MASK)
        elif op=='DIV':
            if not b:raise ProtocolError('TC16_ARITHMETIC','division by zero')
            self.registers[dst]=self._flags(a//b)
        self.cycles+=1
        if self.debug or self.mode==2:
            self.trace.append({'cycle':self.cycles,'pc':self.pc,'op':op,'flags':self.flags})
            self.trace=self.trace[-128:]
    def interrupt(self,vector):
        if not self.flags&self.FLAG_I:return False
        self._address(vector);self.push(self.pc);self.push(self.flags);self.flags&=~self.FLAG_I;self.pc=vector;return True
    def run(self,start_address=0,max_cycles=10000):
        if type(max_cycles) is not int or not 1<=max_cycles<=100000:raise ProtocolError('TC16_LIMIT','bounded instruction budget required')
        self._address(start_address);self.pc=start_address;self.running=True
        for _ in range(max_cycles):
            self.step()
            if not self.running:break
        return {'schema':'ziokt.tc16-state.v1','word_bits':16,'registers':list(self.registers),'pc':self.pc,'sp':self.sp,'flags':self.flags,'mode':self.mode,'cycles':self.cycles,'halted':not self.running,'budget_exhausted':self.running,'trace':list(self.trace)}


from .tcc import TCCCompiler

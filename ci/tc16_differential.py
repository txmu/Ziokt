"""Compare Python and real Rust ETP Unified executors, including fault snapshots."""
import base64,json,subprocess,sys,random
from ziokt.tc16_spec import compile_package,execute_package

PROGRAMS=[
 'MOVI R0, 65535\nMOVI R1, 2\nADD R0, R1\nHALT',
 'MOVI R0, 7\nMOVI R1, 0\nDIV R0, R1\nHALT',
 'MOVI R0, 42\nSYS 1\nHALT',
 'MOVI R0, 0xffff\nMOVI R1, 1\nSTORE R0, R1\nHALT',
 'MOVI R0, 31\nPUSH R0\nPOP R1\nHALT',
 'POP R0\nHALT',
 'MOVI R0, 3\nMOVI R1, 2\nCMP R0, R1\nJC bad\nJMP done\nbad: MOVI R0, 9\ndone: HALT',
 'MOVI R0, 0x9999\nMOVI R1, 1\nBCDADD R0, R1\nHALT',
 'MOVI R0, 0xf\nMOVI R1, 1\nBCDADD R0, R1\nHALT',
 'MOVI R0, 0x8001\nSHL R0, 1\nSHR R0, 0\nHALT',
 'CALL fn\nHALT\nfn: MOVI R0, 4\nRET',
 'MOVI R0, 3\nSETSP R0\nHALT',
 'JMP 0',
]

def main():
 rng=random.Random(160001)
 programs=list(PROGRAMS)
 for _ in range(64):
  lines=['MOVI R0, '+str(rng.randrange(65536)),'MOVI R1, '+str(rng.randrange(65536))]
  for _ in range(32):
   op=rng.choice(['ADD','SUB','MUL','DIV','AND','OR','XOR','CMP','NOT','INC','DEC','SHL','SHR','MOVI','SWAP','PARITY','PUSH','POP'])
   reg='R'+str(rng.randrange(4))
   if op=='MOVI':line=op+' '+reg+', '+str(rng.randrange(65536))
   elif op in {'SHL','SHR'}:line=op+' '+reg+', '+str(rng.randrange(16))
   elif op in {'NOT','INC','DEC','PARITY','PUSH','POP'}:line=op+' '+reg
   else:line=op+' '+reg+', R'+str(rng.randrange(4))
   lines.append(line)
  programs.append('\n'.join(lines+['HALT']))
 runner=sys.argv[1];count=0
 with subprocess.Popen([runner],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True) as process:
  for program in programs:
   for profile in ('pure-v1','stdout-u16-v1'):
    package=compile_package(program,syntax='assembly',profile=profile)
    expected=execute_package(package,100)
    process.stdin.write(json.dumps({'package':base64.b64encode(package).decode(),'cycles':100})+'\n');process.stdin.flush()
    actual=json.loads(process.stdout.readline())
    if actual!=expected:raise AssertionError({'program':program,'expected':expected,'actual':actual})
    count+=1
  for source in ('int main(){return 65535+2;}','int main(){int x=0;while(x<5){x=x+1;}return x;}'):
   package=compile_package(source);expected=execute_package(package,10000)
   process.stdin.write(json.dumps({'package':base64.b64encode(package).decode(),'cycles':10000})+'\n');process.stdin.flush();actual=json.loads(process.stdout.readline())
   if actual!=expected:raise AssertionError({'source':source,'expected':expected,'actual':actual})
   count+=1
  process.stdin.close();process.wait(timeout=5)
 print(json.dumps({'real_executors':2,'cases':count,'status':'passed'}))

if __name__=='__main__':main()

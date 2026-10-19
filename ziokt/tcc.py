"""Bounded TCC frontend for TC-16 integer C functions and control flow.

16-bit unsigned arithmetic; int/word/ptr are 16 bits, byte/bool truncate.
No preprocessor, host calls, implicit undefined identifiers or arbitrary eval.
"""
import re
from .protocol import ProtocolError

TOKEN=re.compile(r'\s+|//[^\n]*|/\*[\s\S]*?\*/|0[xX][0-9a-fA-F]+|\d+|[A-Za-z_]\w*|==|!=|<=|>=|&&|\|\||[{}();,+\-*/%<>=!&|^]')
TYPES={'int','word','byte','bool','ptr','void'}
PRECEDENCE={'||':1,'&&':2,'|':3,'^':4,'&':5,'==':6,'!=':6,'<':7,'>':7,'<=':7,'>=':7,'+':8,'-':8,'*':9,'/':9,'%':9}

class TCCCompiler:
    def __init__(self,debug=False):self.debug=debug
    def compile_binary(self,source,target='tc16-unified-v1',profile='pure-v1'):
        from .tc16_spec import compile_package
        return compile_package(source,syntax='tcc',target=target,profile=profile)
    def assemble(self,source):
        from .tc16 import assemble
        return assemble(source)
    def compile(self,source):
        if not isinstance(source,str) or len(source.encode())>32768:raise ProtocolError('TCC_LIMIT','bounded TCC source required')
        tokens=[];position=0
        for match in TOKEN.finditer(source):
            if match.start()!=position:raise ProtocolError('INVALID_TCC','unsupported source character')
            position=match.end();value=match.group()
            if not value.isspace() and not value.startswith(('//','/*')):tokens.append(value)
        if position!=len(source) or len(tokens)>8192:raise ProtocolError('TCC_LIMIT','invalid or excessive tokens')
        self.tokens=tokens+['<eof>'];self.pos=0;self.depth=0;self.functions={}
        while self.peek()!='<eof>':
            kind=self.take()
            if kind not in TYPES: self.fail('function type required')
            name=self.name();self.expect('(');params=[]
            if self.peek()!=')':
                if self.peek()=='void' and self.tokens[self.pos+1]==')':self.take()
                else:
                    while True:
                        typ=self.take()
                        if typ not in TYPES-{'void'}:self.fail('parameter type required')
                        params.append((self.name(),typ))
                        if self.peek()!=',':break
                        self.take()
            self.expect(')');body=self.statement()
            if name in self.functions or len(params)>8 or body[0]!='block':self.fail('unique function with at most eight parameters required')
            self.functions[name]=(kind,params,body)
        if 'main' not in self.functions or self.functions['main'][1]:self.fail('main() entry required')
        self.lines=['CALL fn_main','HALT'];self.counter=0
        for name,(_,params,body) in self.functions.items():
            self.slots={};self.types={};self.end=self.label('return');self.loops=[]
            for param,typ in params:self.declare(param,typ)
            self.collect(body)
            if len(self.slots)>128:self.fail('too many local slots')
            self.emit('fn_'+name+':','PUSH R15','GETSP R15')
            for _ in self.slots:self.emit('MOVI R8, 0','PUSH R8')
            for i,(param,_) in enumerate(params):self.address(param);self.emit(f'STORE R9, R{i}')
            self.generate(body);self.emit('MOVI R0, 0',self.end+':','SETSP R15','POP R15','RET')
        if len(self.lines)>16000:self.fail('generated program budget exceeded')
        return '\n'.join(self.lines)+'\n'
    def fail(self,message):raise ProtocolError('INVALID_TCC',message)
    def peek(self):return self.tokens[self.pos] if self.pos<len(self.tokens) else '<eof>'
    def take(self):
        value=self.peek()
        if value=='<eof>':self.fail('unexpected end of source')
        self.pos+=1
        return value
    def expect(self,value):
        if self.take()!=value:self.fail('expected '+value)
    def name(self):
        value=self.take()
        if not re.fullmatch(r'[A-Za-z_]\w{0,63}',value) or value in TYPES:self.fail('identifier required')
        return value
    def statement(self):
        self.depth+=1
        if self.depth>32:self.fail('statement nesting exceeded')
        try:
            value=self.take()
            if value=='{':
                items=[]
                while self.peek()!='}':
                    if self.peek()=='<eof>':self.fail('unclosed block')
                    items.append(self.statement())
                self.take();return ('block',items)
            if value in TYPES-{'void'}:
                name=self.name();expr=('number',0)
                if self.peek()=='=':self.take();expr=self.expression()
                self.expect(';');return ('declare',name,value,expr)
            if value=='return':
                expr=('number',0) if self.peek()==';' else self.expression();self.expect(';');return ('return',expr)
            if value in {'if','while'}:
                self.expect('(');expr=self.expression();self.expect(')');body=self.statement()
                if value=='while':return ('while',expr,body)
                other=('block',[])
                if self.peek()=='else':self.take();other=self.statement()
                return ('if',expr,body,other)
            if value in {'break','continue'}:self.expect(';');return (value,)
            if value==';':return ('block',[])
            self.pos-=1
            if self.pos+1<len(self.tokens) and self.tokens[self.pos+1]=='=':
                name=self.name();self.expect('=');expr=self.expression();self.expect(';');return ('assign',name,expr)
            expr=self.expression();self.expect(';');return ('expr',expr)
        finally:self.depth-=1
    def expression(self,minimum=0,depth=0):
        if depth>32:self.fail('expression nesting exceeded')
        value=self.take()
        if value in {'-','!','+'}:left=('unary',value,self.expression(10,depth+1))
        elif value=='(':left=self.expression(0,depth+1);self.expect(')')
        elif re.fullmatch(r'0[xX][0-9a-fA-F]+|\d+',value):
            hexadecimal=value.lower().startswith('0x');digits=(value[2:] if hexadecimal else value).lstrip('0') or '0'
            if len(digits)>(4 if hexadecimal else 5):self.fail('16-bit integer required')
            n=int(digits,16 if hexadecimal else 10)
            if n>65535:self.fail('16-bit integer required')
            left=('number',n)
        elif value in {'true','false'}:left=('number',int(value=='true'))
        elif re.fullmatch(r'[A-Za-z_]\w*',value):
            left=('variable',value)
            if self.peek()=='(':
                self.take();args=[]
                if self.peek()!=')':
                    while True:
                        args.append(self.expression(0,depth+1))
                        if self.peek()!=',':break
                        self.take()
                self.expect(')');left=('call',value,args)
        else:self.fail('expression required')
        while self.peek() in PRECEDENCE and PRECEDENCE[self.peek()]>=minimum:
            op=self.take();left=('binary',op,left,self.expression(PRECEDENCE[op]+1,depth+1))
        stack=[(left,0)];count=0
        while stack:
            node,level=stack.pop();count+=1
            if level>64 or count>1024:self.fail('expression complexity exceeded')
            if node[0]=='binary':stack.extend([(node[2],level+1),(node[3],level+1)])
            elif node[0]=='unary':stack.append((node[2],level+1))
            elif node[0]=='call':stack.extend((n,level+1) for n in node[2])
        return left
    def emit(self,*lines):self.lines.extend(lines)
    def label(self,prefix):self.counter+=1;return 'tcc_'+prefix+'_'+str(self.counter)
    def declare(self,name,typ):
        if name in self.slots:self.fail('duplicate local identifier')
        self.slots[name]=len(self.slots);self.types[name]=typ
    def collect(self,node):
        kind=node[0]
        if kind=='declare':self.declare(node[1],node[2])
        elif kind=='block':
            for n in node[1]:self.collect(n)
        elif kind=='if':self.collect(node[2]);self.collect(node[3])
        elif kind=='while':self.collect(node[2])
    def address(self,name):
        if name not in self.slots:self.fail('unknown local '+name)
        self.emit('MOV R9, R15',f'MOVI R10, {2*(self.slots[name]+1)}','SUB R9, R10')
    def store(self,name):
        if self.types.get(name)=='byte':self.emit('MOVI R10, 255','AND R0, R10')
        elif self.types.get(name)=='bool':self.boolean()
        self.address(name);self.emit('STORE R9, R0')
    def boolean(self):
        done=self.label('bool');self.emit('MOVI R1, 0','CMP R0, R1',f'JZ {done}','MOVI R0, 1',done+':')
    def generate(self,node):
        kind=node[0]
        if kind=='block':
            for n in node[1]:self.generate(n)
        elif kind in {'declare','assign'}:
            self.expr(node[3] if kind=='declare' else node[2]);self.store(node[1])
        elif kind=='expr':self.expr(node[1])
        elif kind=='return':self.expr(node[1]);self.emit('JMP '+self.end)
        elif kind=='if':
            other=self.label('else');done=self.label('endif');self.expr(node[1]);self.emit('MOVI R1, 0','CMP R0, R1','JZ '+other);self.generate(node[2]);self.emit('JMP '+done,other+':');self.generate(node[3]);self.emit(done+':')
        elif kind=='while':
            start=self.label('while');done=self.label('endwhile');self.loops.append((start,done));self.emit(start+':');self.expr(node[1]);self.emit('MOVI R1, 0','CMP R0, R1','JZ '+done);self.generate(node[2]);self.emit('JMP '+start,done+':');self.loops.pop()
        elif kind in {'break','continue'}:
            if not self.loops:self.fail('loop control outside loop')
            self.emit('JMP '+self.loops[-1][kind=='break'])
    def expr(self,node):
        kind=node[0]
        if kind=='number':self.emit('MOVI R0, '+str(node[1]))
        elif kind=='variable':self.address(node[1]);self.emit('LOAD R0, R9')
        elif kind=='call':
            if node[1] not in self.functions or len(node[2])!=len(self.functions[node[1]][1]):self.fail('known function with exact arguments required')
            for arg in node[2]:self.expr(arg);self.emit('PUSH R0')
            for i in reversed(range(len(node[2]))):self.emit('POP R'+str(i))
            self.emit('CALL fn_'+node[1])
        elif kind=='unary':
            self.expr(node[2])
            if node[1]=='-':self.emit('MOVI R1, 0','SUB R1, R0','MOV R0, R1')
            elif node[1]=='!':
                done=self.label('not');self.emit('MOVI R1, 0','CMP R0, R1','MOVI R0, 1','JZ '+done,'MOVI R0, 0',done+':')
        elif kind=='binary':
            op=node[1]
            if op in {'&&','||'}:
                done=self.label('logical');self.expr(node[2]);self.boolean();self.emit('MOVI R1, 0','CMP R0, R1',('JZ ' if op=='&&' else 'JNZ ')+done);self.expr(node[3]);self.boolean();self.emit(done+':');return
            self.expr(node[2]);self.emit('PUSH R0');self.expr(node[3]);self.emit('MOV R1, R0','POP R0')
            basic={'+':'ADD','-':'SUB','*':'MUL','/':'DIV','&':'AND','|':'OR','^':'XOR'}
            if op in basic:self.emit(basic[op]+' R0, R1')
            elif op=='%':self.emit('MOV R2, R0','DIV R0, R1','MUL R0, R1','SUB R2, R0','MOV R0, R2')
            else:
                yes=self.label('true');done=self.label('compare')
                if op in {'>','<='}:self.emit('CMP R1, R0')
                else:self.emit('CMP R0, R1')
                self.emit('MOVI R0, 0')
                if op in {'==','!='}:self.emit(('JZ ' if op=='==' else 'JNZ ')+yes)
                elif op in {'<','>'}:self.emit('JC '+yes)
                else:self.emit('JZ '+yes,'JC '+done,'JMP '+yes)
                self.emit('JMP '+done,yes+':','MOVI R0, 1',done+':')

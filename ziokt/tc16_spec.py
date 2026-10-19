"""Explicit TC-16 family identities and versioned binary containers.

Legacy byte streams are never guessed or silently reinterpreted as Unified.
Unified v1 freezes the Python instruction semantics and uses a distinct package
identity. ETP legacy remains an independent ISA and must use its own executor.
"""
import base64
import hashlib
import json
import struct
from .protocol import ProtocolError,encoded,strict_json

TARGETS={
 'tc16-python-legacy':{'isa_id':'tc16-python-v1','abi_id':'tc16-python-abi-v1','binary_format':'tc16-python-raw-v1'},
 'tc16-etp-legacy':{'isa_id':'tc16-etp-v1','abi_id':'tc16-etp-abi-v1','binary_format':'tc16-etp-raw-v1'},
 'tc16-unified-v1':{'isa_id':'tc16-unified-v1','abi_id':'tc16-unified-abi-v1','binary_format':'tc16-package-v1'},
}
MAGIC=b'TC16PKG1'


def contract(value, *, optional=True):
    fields={'isa_id','abi_id','binary_format','capability_profile'}
    present=fields & set(value)
    if not present and optional:return {'legacy_unspecified':True,'binary_compatibility':'unknown'}
    if present!=fields:raise ProtocolError('TC16_TARGET_REQUIRED','all ISA/ABI/format/capability fields required together')
    match=next((name for name,info in TARGETS.items() if all(value.get(k)==v for k,v in info.items())),None)
    if match is None:raise ProtocolError('TC16_TARGET_MISMATCH','unrecognized or conflicting ISA/ABI/format')
    if value['capability_profile'] not in {'pure-v1','stdout-u16-v1'}:raise ProtocolError('TC16_CAPABILITY','unsupported profile')
    if match=='tc16-etp-legacy' and value['capability_profile']!='pure-v1':raise ProtocolError('TC16_CAPABILITY','legacy ETP profile must be explicit pure')
    return {'target':match,**{k:value[k] for k in fields}}


def package(code,target='tc16-unified-v1',profile='pure-v1',entrypoint=0):
    if target not in TARGETS:raise ProtocolError('TC16_TARGET_REQUIRED','known explicit compiler target required')
    metadata={**TARGETS[target],'capability_profile':profile,'entrypoint':entrypoint,'code_size':len(code),'sha256':hashlib.sha256(code).hexdigest()}
    contract(metadata,optional=False)
    if not isinstance(code,bytes) or not 1<=len(code)<=65536 or type(entrypoint) is not int or not 0<=entrypoint<len(code):raise ProtocolError('INVALID_TC16','bounded code and valid entrypoint required')
    header=encoded(metadata)
    return MAGIC+struct.pack('>I',len(header))+header+code


def unpack(blob,accepted=None):
    if not isinstance(blob,bytes) or not blob.startswith(MAGIC) or not 12<len(blob)<=70000:raise ProtocolError('TC16_HEADER','versioned TC16 package required')
    size=struct.unpack('>I',blob[8:12])[0]
    if not 1<=size<=4096 or size+12>=len(blob):raise ProtocolError('TC16_HEADER','header budget')
    metadata=strict_json(blob[12:12+size],4096)
    if set(metadata)!={'isa_id','abi_id','binary_format','capability_profile','entrypoint','code_size','sha256'}:raise ProtocolError('TC16_HEADER','exact metadata required')
    info=contract(metadata,optional=False);code=blob[12+size:]
    if metadata['code_size']!=len(code) or len(code)>65536 or hashlib.sha256(code).hexdigest()!=metadata['sha256']:raise ProtocolError('TC16_HEADER','code size or digest mismatch')
    if type(metadata['entrypoint']) is not int or not 0<=metadata['entrypoint']<len(code):raise ProtocolError('TC16_HEADER','entrypoint')
    if accepted is not None and metadata['isa_id'] not in accepted:raise ProtocolError('TC16_ISA_MISMATCH','executor does not accept target ISA')
    return metadata,code


def compile_package(source,*,syntax='tcc',target='tc16-unified-v1',profile='pure-v1'):
    from .tcc import TCCCompiler
    from .tc16 import assemble
    if target=='tc16-etp-legacy':raise ProtocolError('TC16_TARGET_UNAVAILABLE','ETP legacy compilation requires its native compiler; no unsafe translation')
    if target not in TARGETS:raise ProtocolError('TC16_TARGET_REQUIRED','unknown target')
    if syntax=='tcc':source=TCCCompiler().compile(source)
    elif syntax!='assembly':raise ProtocolError('INVALID_TC16','syntax')
    return package(assemble(source),target,profile)


def execute_package(blob,max_cycles=10000):
    from .tc16 import TC16_CPU
    metadata,code=unpack(blob,{'tc16-python-v1','tc16-unified-v1'})
    output=[]
    syscalls={1:lambda cpu:output.append(str(cpu.registers[0]))} if metadata['capability_profile']=='stdout-u16-v1' else {}
    cpu=TC16_CPU(syscalls=syscalls);cpu.load_program(code)
    exception=None
    try:result=cpu.run(metadata['entrypoint'],max_cycles)
    except ProtocolError as error:
        exception=error.code
        result={'registers':list(cpu.registers),'pc':cpu.pc,'sp':cpu.sp,'flags':cpu.flags,'mode':cpu.mode,'cycles':cpu.cycles,'halted':not cpu.running,'budget_exhausted':False}
    return {'isa_id':metadata['isa_id'],'abi_id':metadata['abi_id'],'registers':result['registers'],'pc':result['pc'],'sp':result['sp'],'flags':result['flags'],'mode':result['mode'],'cycles':result['cycles'],'halted':result['halted'],'budget_exhausted':result['budget_exhausted'],'exception':exception,'output':output,'memory_sha256':hashlib.sha256(cpu.memory).hexdigest()}

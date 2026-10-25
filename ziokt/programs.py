"""One program container with explicit TC-16, native ETP and Tri backends."""
import argparse
import base64
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import re

from .protocol import ProtocolError,encoded,secure_read,strict_json
from .tc16_spec import compile_package,execute_package,unpack
from .tc16_legacy import compile_native
from ._verified_guards import target_matches

TARGETS={'tc16-tcc':('tc16-unified-v1','tc16-unified-abi-v1','TC16PKG1'),
         'etp-tc16-tcc':('etp-legacy-pure-return-v1','tc16-unified-abi-v1','TC16PKG1'),
         'tri':('tri-simulator-v1','tri-memory-v1','tri-json-v1')}


def tri_assemble(source):
    isa=json.loads(files('ziokt').joinpath('tri_isa.json').read_text());ops=isa['instructions'];operands=set(isa['operands'])
    lines=source.splitlines();labels={};parsed=[];address=0
    for number,line in enumerate(lines,1):
        line=line.split('//',1)[0].strip()
        if not line:continue
        if ':' in line:
            label,line=line.split(':',1);label=label.strip();line=line.strip()
            if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}',label) or label in labels:raise ProtocolError('TRI_ASSEMBLY','unique portable label required')
            labels[label]=address
        if not line:continue
        parts=line.split();opcode=ops.get(parts[0].upper())
        if opcode is None or len(parts)!=(2 if opcode in operands else 1):raise ProtocolError('TRI_ASSEMBLY','known instruction and exact operand count required')
        parsed.append((number,opcode,parts[1] if len(parts)==2 else None));address+=2 if opcode in operands else 1
        if address>65536:raise ProtocolError('PROGRAM_LIMIT','Tri code memory budget exceeded')
    if not parsed:raise ProtocolError('TRI_ASSEMBLY','nonempty Tri program required')
    memory=[]
    for number,opcode,operand in parsed:
        memory.append(opcode)
        if operand is not None:
            if operand in labels:value=labels[operand]
            elif re.fullmatch('-?(?:0|[1-9][0-9]{0,15})',operand):value=int(operand)
            else:raise ProtocolError('TRI_ASSEMBLY','integer or declared label operand required')
            if not -(2**53-1)<=value<=2**53-1:raise ProtocolError('PROGRAM_LIMIT','portable integer operand required')
            memory.append(value)
    return {'schema':'ziokt.tri-machine.v1','isa_id':'tri-simulator-v1','entrypoint':0,
            'memory':memory,'isa_source_sha256':isa['source_sha256']}


def compile_program(source,target,*,syntax='tcc',native=None):
    if not isinstance(target,str) or target not in TARGETS:raise ProtocolError('PROGRAM_TARGET','explicit program backend required')
    if not isinstance(source,str) or not 1<=len(source.encode())<=65536:raise ProtocolError('PROGRAM_LIMIT','bounded UTF-8 source required')
    details={}
    if target=='tc16-tcc':payload=compile_package(source,syntax=syntax);language=syntax
    elif target=='etp-tc16-tcc':
        if syntax!='tcc':raise ProtocolError('PROGRAM_LANGUAGE','native ETP frontend requires its TCC source')
        result=compile_native(source,native);payload=base64.b64decode(result['package'],validate=True)
        details={'compiler':result['compiler'],'semantic_profile':result['semantic_profile'],'reference_result':result['legacy_result']};language='etp-tcc'
    else:
        if syntax!='assembly':raise ProtocolError('PROGRAM_LANGUAGE','Tri assembly source required')
        payload=encoded(tri_assemble(source));language='tri-assembly'
    isa,abi,format_id=TARGETS[target]
    result={'schema':'ziokt.program.v1','target':target,'isa':isa,'abi':abi,'format':format_id,
            'source_language':language,'source':source,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
            'payload':base64.b64encode(payload).decode(),'payload_sha256':hashlib.sha256(payload).hexdigest(),
            'entrypoint':0,'details':details}
    read_program(encoded(result),expected_target=target)
    return result


def read_program(data,expected_target=None):
    value=strict_json(data,2*1024*1024,string_limit=1500000)
    fields={'schema','target','isa','abi','format','source_language','source','source_sha256','payload','payload_sha256','entrypoint','details'}
    if not isinstance(value,dict) or set(value)!=fields or value['schema']!='ziokt.program.v1' or not isinstance(value['target'],str) or value['target'] not in TARGETS:
        raise ProtocolError('PROGRAM_FORMAT','exact portable program envelope required')
    if expected_target is not None and not target_matches(expected_target,value['target']):raise ProtocolError('PROGRAM_TARGET','executor target differs from program backend')
    if (value['isa'],value['abi'],value['format'])!=TARGETS[value['target']] or type(value['entrypoint']) is not int or value['entrypoint']!=0:
        raise ProtocolError('PROGRAM_TARGET','ISA, ABI, format and entrypoint must match the backend')
    if (not isinstance(value['source'],str) or not 1<=len(value['source'].encode())<=65536
            or hashlib.sha256(value['source'].encode()).hexdigest()!=value['source_sha256']
            or not isinstance(value['payload'],str) or len(value['payload'])>1500000 or not isinstance(value['details'],dict)):
        raise ProtocolError('PROGRAM_DIGEST','source or payload declaration differs')
    try:payload=base64.b64decode(value['payload'],validate=True)
    except (ValueError,TypeError) as error:raise ProtocolError('PROGRAM_FORMAT','canonical payload encoding required') from error
    if hashlib.sha256(payload).hexdigest()!=value['payload_sha256']:raise ProtocolError('PROGRAM_DIGEST','program payload changed')
    if value['target']=='tri':
        image=strict_json(payload,1024*1024)
        if image!=tri_assemble(value['source']):raise ProtocolError('PROGRAM_DIGEST','Tri machine code differs from the declared source')
        if value['source_language']!='tri-assembly':raise ProtocolError('PROGRAM_LANGUAGE','Tri assembly language required')
    else:
        unpack(payload,{'tc16-unified-v1'})
        if value['target']=='tc16-tcc':
            if value['source_language'] not in {'tcc','assembly'} or compile_package(value['source'],syntax=value['source_language'])!=payload:
                raise ProtocolError('PROGRAM_DIGEST','TC-16 code differs from the declared source')
        elif value['source_language']!='etp-tcc' or value['details'].get('semantic_profile')!='etp-legacy-pure-return-v1':
            raise ProtocolError('PROGRAM_LANGUAGE','native ETP semantic profile required')
    return value,payload


def main(argv=None):
    parser=argparse.ArgumentParser(prog='ziokt program');sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('compile');p.add_argument('source',type=Path);p.add_argument('--target',choices=sorted(TARGETS),required=True);p.add_argument('--syntax',choices=['tcc','assembly'],default='tcc');p.add_argument('--native-compiler',type=Path);p.add_argument('--compiler-sha256');p.add_argument('--output',type=Path,required=True)
    for name in ('inspect','run'):
        p=sub.add_parser(name);p.add_argument('program',type=Path);p.add_argument('--target',choices=sorted(TARGETS),required=True)
        if name=='run':p.add_argument('--cycles',type=int,default=10000)
    args=parser.parse_args(argv)
    if args.action=='compile':
        native={'binary':str(args.native_compiler),'sha256':args.compiler_sha256} if args.native_compiler else None
        result=compile_program(secure_read(args.source,65536,private=None).decode(),args.target,syntax=args.syntax,native=native)
        from .cli import write_binary_exclusive
        write_binary_exclusive(args.output,encoded(result));result={'target':result['target'],'path':str(args.output),'payload_sha256':result['payload_sha256']}
    else:
        value,payload=read_program(secure_read(args.program,2*1024*1024,private=None),args.target)
        if args.action=='inspect':result={k:v for k,v in value.items() if k not in {'source','payload'}}
        elif value['target']=='tri':result={'target':'tri','application':'/tri/','source':value['source'],'machine':strict_json(payload,1024*1024)}
        else:
            if not 1<=args.cycles<=50000:raise ProtocolError('PROGRAM_LIMIT','execution cycle budget must be 1..50000')
            result=execute_package(payload,args.cycles)
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())

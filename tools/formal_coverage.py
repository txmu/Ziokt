#!/usr/bin/env python3
"""Inventory every tracked source file without mistaking a model for refinement."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

SUFFIXES={'.py','.sh','.go','.rs','.c','.h','.cpp','.hpp','.js','.mjs','.cjs','.ts','.tsx','.jsx',
          '.java','.kt','.cs','.adb','.ads','.idr','.nim','.d','.zig','.hr','.carp','.gleam','.scm','.lean','.ps1'}
ADA={'Core-Ada/src/cells.ads','Core-Ada/src/cells.adb','Core-Ada/src/domain_policy.ads','Core-Ada/src/domain_policy.adb'}


def inventory(base):
    result={}
    for name in ('Ziokt','Corium','Shadow6'):
        root=base/name
        tracked=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
        mapped={}
        models=root/'formal/models.json'
        if models.exists():
            for model,entry in json.loads(models.read_text())['models'].items():
                for source in entry['source_sha256']:mapped.setdefault(source,[]).append('formal/'+model)
        rows=[]
        for relative in sorted(filter(None,tracked)):
            path=Path(relative)
            if path.suffix not in SUFFIXES:continue
            file=root/path
            if not file.is_file() or file.is_symlink():continue
            if 'original' in path.parts or 'vendor' in path.parts or 'third_party' in path.parts:
                status='upstream-reference-or-vendored; no full formal claim'
            elif path.parts[0] in {'formal','ci','tests'} or path.name.startswith(('test_','benchmark')) or path.name.endswith(('_test.go','_test.py')):
                status='verification-or-test-code'
            elif name=='Shadow6' and relative in ADA:
                status='existing-native-SPARK-contract; scope in Core-Ada/proof.gpr'
            elif name=='Shadow6' and relative.startswith('Core-Idris/src/Shadow6/Security') or name=='Shadow6' and relative=='Core-Idris/src/Shadow6/Types.idr':
                status='existing-native-Idris-type-contract; FFI/runtime outside proof'
            elif relative in mapped:
                status='abstract-model/manual-correspondence; refinement remains open'
            elif name=='Corium' and relative=='corix_v108.sh':
                status='abstract-model/manual-function-correspondence; most implementation remains open'
            else:status='not-yet-formalized'
            rows.append({'path':relative,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'status':status,'models':mapped.get(relative,[])})
        result[name]={'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
                      'source_files':len(rows),'coverage_classes':dict(Counter(row['status'] for row in rows)),'files':rows}
    return {'schema':'ziokt.joint-formal-coverage.v1','repositories':result,
            'complete_implementation_refinement':False,'note':'Native Ada/Idris contracts are preserved as existing evidence. Model correspondence hashes detect drift; no verified-source percentage is inferred. CI and physical deployment acceptance are separate.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repositories-root',type=Path,default=Path(__file__).resolve().parents[2]);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    value=inventory(args.repositories_root);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({name:{k:v for k,v in row.items() if k!='files'} for name,row in value['repositories'].items()},ensure_ascii=False,sort_keys=True))

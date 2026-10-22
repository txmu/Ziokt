#!/usr/bin/env python3
"""Deterministic, source-only security review packet; no deployed state or private keys."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def git(root,*args):return subprocess.check_output(['git',*args],cwd=root,timeout=20)


def package(output,revision='HEAD',corium=None,shadow6=None):
    source=git(ROOT,'rev-parse',revision+'^{commit}').decode().strip()
    lock=json.loads(git(ROOT,'show',source+':native-sources.lock.json'))
    repositories={'Ziokt':(ROOT,source),'Corium':(Path(corium or ROOT.parent/'Corium'),lock['corium']['revision']),'Shadow6':(Path(shadow6 or ROOT.parent/'Shadow6'),lock['shadow6']['revision'])}
    selected={
        'Ziokt':['spec','ziokt','openci','tests','requirements.txt','requirements-reader.txt','requirements-dns.txt','native-sources.lock.json','tools/sync_providers.py','tools/audit_mcp_registry.py','docs/security','docs/content-fabric/ACCEPTANCE.md','docs/content-fabric/WORK_ITEMS.md','docs/content-fabric/REMAINING.md','docs/content-fabric/MCP-SOURCE-LIVE-2026-10-22.json','docs/openci/MAINNET-MIGRATIONS.md','docs/openci/PEOPLE-HELP.md','docs/MCP_TOOL_CATALOG.json'],
        'Corium':['corix_v108.sh','shielded_ownership.py','work_weight_policy.py','work_weight_native.py','test_core.py','test_privacy_consensus.py','test_privacy_primitives.py','test_engine_proof_boundary.py','test_engine_governance_cli.py','test_work_weight_policy.py','test_work_weight_native.py','WORK-WEIGHT-POLICY.md'],
        'Shadow6':['Ziokt-Support/zfcp_runtime.py']}
    entries={};files={};total=0
    for component,(root,commit) in repositories.items():
        if not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('exact native source commit required')
        actual=git(root,'rev-parse',commit+'^{commit}').decode().strip()
        if actual!=commit:raise ValueError('source identity mismatch')
        listing=git(root,'ls-tree','-r','--name-only',commit,'--',*selected[component]).decode().splitlines()
        if not listing:raise ValueError('required audit source unavailable')
        for path in listing:
            # No deployment configuration, binaries, browser caches, generated artifacts or key material.
            if Path(path).suffix not in {'.py','.sh','.md','.json','.txt'}:continue
            if any(part in {'node_modules','__pycache__','.git','state','keys','accounts','uploads'} for part in Path(path).parts):continue
            content=git(root,'show',commit+':'+path)
            total+=len(content)
            if len(content)>8*1024*1024 or total>32*1024*1024 or len(entries)>=768:raise ValueError('bounded review packet source budget')
            name=component+'/'+path;entries[name]=content;files[name]={'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content),'source_commit':commit}
    # The actual standalone module must be included and aligned, not just its generator.
    if entries.get('Corium/shielded_ownership.py')!=entries.get('Ziokt/spec/shielded_runtime.py'):raise ValueError('native standalone crypto source drift')
    manifest={'schema':'ziokt.security-review-packet.v1','source_commit':source,'native_sources':lock,'files':files,
              'scope':['Ziokt application/security source and tests','OpenCI controller and native publication','Corium original consensus source and experimental work/shielded code','Shadow6 Ziokt provider contract only'],
              'excluded_scope':['complete independent review of all Shadow6 Cores','external deployments or physical devices','production secrets and live databases'],
              'review_model':'Codex source review and reproducible testing, per user instruction','external_independent_audit':'not_performed','external_audit_requested':False,'mainnet_activation_authorized':False,'all_requested_features_complete':False,
              'assurance':'review inputs and reproducibility, not a security approval or business acceptance'}
    entries['REVIEW-MANIFEST.json']=(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()
    entries['SHA256SUMS']=''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in sorted(entries.items())).encode()
    output.parent.mkdir(parents=True,exist_ok=True);temporary=output.with_suffix(output.suffix+'.new')
    with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,data in sorted(entries.items()):
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;archive.writestr(info,data)
    temporary.replace(output)
    return {'schema':manifest['schema'],'source_commit':source,'files':len(files),'uncompressed_bytes':total,'archive_bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'review_model':'Codex source review and reproducible testing, per user instruction','external_independent_audit':'not_performed','external_audit_requested':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--revision',default='HEAD');p.add_argument('--corium',type=Path);p.add_argument('--shadow6',type=Path);a=p.parse_args();print(json.dumps(package(a.output,a.revision,a.corium,a.shadow6)))

#!/usr/bin/env python3
"""Read-only source/catalog/live MCP comparison with explicit evidence limits."""
import argparse
import ast
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ziokt.build_info import canonical,registry_digest,semantic
from ziokt.mcp import Service,LATEST
from ziokt.protocol import secure_read,strict_json


def rpc(endpoint,method,params=None):
    params={**(params or {}),'_meta':{'io.modelcontextprotocol/protocolVersion':LATEST,'io.modelcontextprotocol/clientCapabilities':{}}}
    body={'jsonrpc':'2.0','id':1,'method':method,'params':params}
    request=urllib.request.Request(endpoint,data=canonical(body),headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream','MCP-Protocol-Version':LATEST,'Mcp-Method':method})
    with urllib.request.urlopen(request,timeout=30) as response:
        raw=response.read(8*1024*1024+1)
    if len(raw)>8*1024*1024:raise ValueError('live response budget')
    value=json.loads(raw)
    if 'error' in value:raise ValueError('live MCP rejected discovery: '+str(value['error'].get('code')))
    return value['result']


def wire(tool):return {key:value for key,value in tool.items() if key!='scope'}


def compare(source,live,baseline):
    def index(values):
        result={}
        for tool in values:
            name=tool['name']
            if name in result:raise ValueError('duplicate tool identity: '+name)
            result[name]=tool
        return result
    source=index(source);live=index(live);baseline=index(baseline);rows=[]
    for name in sorted(set(source)|set(live)|set(baseline)):
        local=source.get(name);remote=live.get(name);changes=[];details=[];representation=[]
        if local is not None and remote is None:changes.append('missing_in_live_registry')
        elif remote is not None and local is None:changes.append('live_only_tool')
        elif local is not None:
            for field in sorted(set(wire(local))|set(wire(remote))):
                if canonical(local.get(field))!=canonical(remote.get(field)):
                    if canonical(semantic(local.get(field)))==canonical(semantic(remote.get(field))):
                        representation.append(field)
                        continue
                    changes.append({'inputSchema':'schema_changed','securitySchemes':'authorization_changed','_meta':'metadata_changed','annotations':'operation_semantics_changed','description':'description_changed'}.get(field,field+'_changed'))
                    details.append({'field':field,'source':local.get(field),'live':remote.get(field)})
        old=baseline.get(name)
        baseline_state='not_in_baseline' if old is None else 'unchanged' if local is not None and canonical(semantic(wire(old)))==canonical(semantic(wire(local))) else 'changed_or_removed_since_baseline'
        rows.append({'tool':name, 'baseline_present':old is not None, 'source_present':local is not None, 'live_present':remote is not None, 'baseline_comparison':baseline_state, 'source_live_differences':changes, 'changed_fields':details, 'baseline_descriptor_sha256':hashlib.sha256(canonical(wire(old))).hexdigest() if old else None, 'representation_only_differences':representation, 'source_descriptor_sha256':hashlib.sha256(canonical(wire(local))).hexdigest() if local else None, 'live_descriptor_sha256':hashlib.sha256(canonical(wire(remote))).hexdigest() if remote else None, 'source_required_scope':local.get('scope') if local else None, 'live_security_schemes':remote.get('securitySchemes',[]) if remote else None})
    return rows


def implementation(route):
    kind=route[0] if route else ''
    files=['ziokt/mcp.py']
    if kind=='content-fabric':
        files+=['ziokt/content_api.py','ziokt/content_fabric.py']
        op=route[1]
        for prefix,module in [('library.index.','library_index'),('library.note.','library_personal'),('library.bookmark.','library_personal'),('library.collection.','library_personal'),('library.reader.','document_sandbox'),('content.rights.','content_rights'),('content.etp.','content_etp'),('library.etp.','content_etp_library')]:
            if op.startswith(prefix):files.append('ziokt/'+module+'.py')
        if op.startswith('library.reader.') or op=='library.extract':files+=['ziokt/library_formats.py','ziokt/raster_reader.py']
    elif kind=='bridge':files+=['ziokt/bridge.py']
    elif kind=='etp':files+=['ziokt/etp.py']
    elif kind=='gateway':files+=['ziokt/gateway.py']
    elif kind.startswith('native') or kind in {'plan','workflow-apply'}:files+=['ziokt/client.py','ziokt/_runtime.py']
    return [path for path in files if (ROOT/path).is_file()]


def test_references(names):
    found={name:[] for name in names}
    for path in sorted((ROOT/'tests').glob('test_*.py')):
        tree=ast.parse(path.read_text())
        for cls in [node for node in tree.body if isinstance(node,ast.ClassDef)]:
            for test in [node for node in cls.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name.startswith('test_')]:
                mentioned={node.value for node in ast.walk(test) if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value in names}
                for name in mentioned:found[name].append({'test_id':path.stem+'.'+cls.name+'.'+test.name,'file':str(path.relative_to(ROOT))})
    return found


def observed_tests(directory):
    observations={}
    if directory is None:return observations
    paths=sorted(Path(directory).rglob('*.txt'))
    if len(paths)>256:raise ValueError('evidence file count budget')
    for path in paths:
        if path.is_symlink() or path.stat().st_size>8*1024*1024:raise ValueError('evidence log budget')
        log_digest=hashlib.sha256(path.read_bytes()).hexdigest()
        provenance_path=path.parent/'RUN.json'
        provenance=json.loads(provenance_path.read_text()) if provenance_path.is_file() else {}
        provenance={key:provenance[key] for key in ('id','head_sha','conclusion','html_url','name') if key in provenance}
        for match in re.finditer(r'^test_\w+ \(([^\n()]+)\) \.\.\. (ok|FAIL|ERROR|skipped[^\n]*)\s*$',path.read_text(errors='replace'),re.M):
            observations.setdefault(match[1],[]).append({'outcome':match[2],'log':str(path.relative_to(directory)),'log_sha256':log_digest,'ci':provenance})
    return observations


def build_alignment(source,discovery,gateway):
    """Build declarations are not proof of the installed native binary revision."""
    live=discovery.get('serverInfo',{}).get('build') or {}
    peers={'mcp':live,'gateway':(gateway or {}).get('build') or {}}
    rows=[]
    for peer,build in peers.items():
        for field in ('source_commit','python_sources_sha256','native_sources'):
            a,b=source.get(field),build.get(field)
            status='missing_build_metadata' if a is None or b is None else 'match' if a==b else 'mismatch'
            rows.append({'service':peer,'field':field,'source':a,'deployed_declaration':b,'status':status})
    return {'declarations':rows, 'all_build_metadata_matches':all(row['status']=='match' for row in rows) and source.get('working_tree_dirty') is False, 'source_working_tree_dirty':source.get('working_tree_dirty'), 'configured_native_entrypoint_digest':(gateway or {}).get('native_entrypoint_digest'), 'limit':'Matching tool descriptors or declared source revisions do not prove native executable provenance or business acceptance.'}


def audit(config_path,baseline_path,endpoint,output,evidence=None,gateway_url=None):
    config=strict_json(secure_read(config_path));config['config_path']=str(config_path.resolve())
    with tempfile.TemporaryDirectory(prefix='ziokt-registry-audit-') as state:
        source_config={**config,'state':state}
        service=Service(source_config)
        try:source=list(service.tools.values());routes=dict(service.dispatch);source_build=service.build_info
        finally:service.close()
    live=[];seen=set();cursor=None
    for _ in range(32):
        result=rpc(endpoint,'tools/list',{'cursor':cursor} if cursor else {})
        live.extend(result['tools']);cursor=result.get('nextCursor')
        if len(live)>4096:raise ValueError('live registry tool budget')
        if not cursor:break
        if cursor in seen:raise ValueError('repeated live cursor')
        seen.add(cursor)
    else:raise ValueError('live registry pagination budget')
    discovery=rpc(endpoint,'server/discover')
    gateway=None
    if gateway_url:
        with urllib.request.urlopen(gateway_url,timeout=30) as response:
            data=response.read(1024*1024+1)
        if len(data)>1024*1024:raise ValueError('gateway status budget')
        gateway=json.loads(data)
    baseline=json.loads(baseline_path.read_text())['tools']
    rows=compare(source,live,baseline);references=test_references({tool['name'] for tool in source});observations=observed_tests(evidence)
    for row in rows:
        route=routes.get(row['tool'],())
        row['dispatch_route']=list(route)
        row['implementation']=[{'file':path,'sha256':hashlib.sha256((ROOT/path).read_bytes()).hexdigest()} for path in implementation(route)]
        row['test_references']=references.get(row['tool'],[])
        row['test_observations']=[{**reference,'observations':observations[reference['test_id']]} for reference in row['test_references'] if reference['test_id'] in observations]
        row['acceptance_limit']='Static test references and passing test logs are separate from per-tool successful native/remote business acceptance.'
    report={'schema':'ziokt.mcp-registry-audit.v1','observed_at':datetime.now(timezone.utc).isoformat(),'endpoint':endpoint,
            'baseline_count':len(baseline),'source_count':len(source),'live_count':len(live),'source_build':source_build,
            'source_registry_sha256':registry_digest(source),'live_registry_sha256':registry_digest(live),'live_discovery':discovery,
            'baseline_catalog_sha256':hashlib.sha256(baseline_path.read_bytes()).hexdigest(),'gateway':gateway,
            'build_alignment':build_alignment(source_build,discovery,gateway),
            'summary':dict(Counter(change for row in rows for change in row['source_live_differences'])),
            'representation_only_count':sum(bool(row['representation_only_differences']) for row in rows),
            'all_descriptors_match':not any(row['source_live_differences'] for row in rows),'tools':rows}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    markdown=output.with_suffix('.md')
    lines=['# MCP 源码与生产注册表逐项对照','',f'基线 {len(baseline)}；当前源码 {len(source)}；实时服务 {len(live)}。',
           '','各行列出实际检查到的注册、权限和构建信息。','',
           '|工具|基线|源码/生产差异|真实测试记录|','|---|---|---|---|']
    alignment=report['build_alignment']
    lines[6:6]=['构建声明完全一致：'+str(alignment['all_build_metadata_matches'])+'；逐服务构建元数据检查结果见下表。','']+[r['service']+' '+r['field']+'：'+r['status'] for r in alignment['declarations']]+['']
    for row in rows:
        difference=', '.join(row['source_live_differences'])
        if not difference:difference='仅集合顺序不同（语义一致）' if row['representation_only_differences'] else '一致'
        lines.append('|'+row['tool']+'|'+row['baseline_comparison']+'|'+difference+'|'+str(len(row['test_observations']))+' 条相关测试观察；业务未逐项评估|')
    markdown.write_text('\n'.join(lines)+'\n')
    return {key:report[key] for key in ('baseline_count','source_count','live_count','summary','all_descriptors_match','source_registry_sha256','live_registry_sha256','build_alignment')}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True);parser.add_argument('--baseline',type=Path,default=ROOT/'docs/MCP_TOOL_CATALOG.json')
    parser.add_argument('--endpoint',required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--evidence',type=Path)
    parser.add_argument('--gateway-url')
    args=parser.parse_args();print(json.dumps(audit(args.config,args.baseline,args.endpoint,args.output,args.evidence,args.gateway_url),ensure_ascii=False))

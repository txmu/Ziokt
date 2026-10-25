#!/usr/bin/env python3
"""Atomic, text-only joint source snapshots; never compiles native components."""
import argparse,hashlib,importlib.util,json,os,shutil,subprocess,tempfile,zipfile
from pathlib import Path


def package(repositories_root,output,evidence=None):
 # A source release cannot bypass the full proof and inventory gate.
 subprocess.run(['bash',str(Path(repositories_root).resolve()/'Corium/formal/check_all_formal.sh')],check=True)
 base=Path(repositories_root).resolve();output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
 excluded={'.git','.venv','.venv-ft','.tools','.runtime','.tmp','__pycache__','node_modules','target','.zig-cache','zig-out','.gradle','build','dist','obj','jniLibs','.android-toolchain','.nim_runtime','.pytest_cache','.mypy_cache'}
 provenance={'schema':'ziokt.joint-source.v1','repositories':{},'contract':'strict UTF-8; every file name ends in .txt; no native build'}
 with tempfile.TemporaryDirectory(prefix='ziokt-joint-source-') as temporary:
  stage=Path(temporary)/'tree';stage.mkdir()
  for name in ['Ziokt','Corium','Shadow6']+(['Ziokt-Releases'] if (base/'Ziokt-Releases').is_dir() else []):
   repo=base/name
   names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=repo).decode().split('\0')
   included=0
   for relative in sorted(set(filter(None,names))):
    path=Path(relative)
    if path.is_absolute() or '..' in path.parts or excluded.intersection(path.parts) or path.name in {'config.mk','.env'} or path.parts[:2] in {('Benchmark','results'),('Detector','datasets'),('Detector','models')} or path.parts[0] in {'work','release','releases'}:continue
    source=repo/path
    if source.is_symlink() or not source.is_file():continue
    dest=stage/name/path;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest);included+=1
   provenance['repositories'][name]={'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'working_tree_changes':subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).splitlines(),'staged_source_files':included}

  # Place deployment and release tools directly at root and in tools/ for immediate accessibility
  rel_dir=base/'Ziokt-Releases'
  if rel_dir.is_dir():
   tools_dir=stage/'tools';tools_dir.mkdir(parents=True,exist_ok=True)
   ziokt_tools=stage/'Ziokt/tools';ziokt_tools.mkdir(parents=True,exist_ok=True)
   for filename in ['deploy.py','install.sh','install.ps1','sources.json','deploy.py.sha256']:
    src=rel_dir/filename
    if src.is_file():
     shutil.copyfile(src,stage/filename)
     shutil.copyfile(src,tools_dir/filename)
     shutil.copyfile(src,ziokt_tools/filename)
   for filename in ['publish.py','mirror_release.py']:
    src=rel_dir/'tools'/filename
    if src.is_file():
     shutil.copyfile(src,tools_dir/filename)
     shutil.copyfile(src,ziokt_tools/filename)
   if (rel_dir/'ci/independent_node.py').is_file():
    shutil.copyfile(rel_dir/'ci/independent_node.py',tools_dir/'independent_node.py')
    shutil.copyfile(rel_dir/'ci/independent_node.py',ziokt_tools/'independent_node.py')

  (stage/'SOURCE_PROVENANCE.json').write_text(json.dumps(provenance,indent=2)+'\n')
  build_script=base/'package_source.sh'
  if build_script.is_file():
   (stage/'package_source.sh').write_text(build_script.read_text())
  if evidence is not None:
   # Explicit, operator-prepared public evidence only; never collect private config.
   evidence_path=Path(evidence)
   observed=json.loads(evidence_path.read_text())
   (stage/'RELEASE_EVIDENCE.json').write_text(json.dumps(observed,sort_keys=True,indent=2)+'\n')
   if evidence_path.name!='RELEASE_EVIDENCE.json':
    (stage/evidence_path.name).write_text(json.dumps(observed,sort_keys=True,indent=2)+'\n')
  spec=importlib.util.spec_from_file_location('prepare_text_zip',base/'Shadow6/Tools/prepare_text_zip.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  kept,removed=module.prepare(stage)
  manifest={str(file.relative_to(stage)):hashlib.sha256(file.read_bytes()).hexdigest() for file in sorted(stage.rglob('*')) if file.is_file()}
  (stage/'SOURCE_SHA256.json.txt').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n');kept+=1
  temporary_zip=Path(temporary)/'source.zip'
  with zipfile.ZipFile(temporary_zip,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
   for file in sorted(stage.rglob('*')):
    if file.is_file():archive.write(file,str(file.relative_to(stage)))
  python=base/'Shadow6/.venv/bin/python';python=str(python) if python.exists() else __import__('sys').executable
  subprocess.run([python,str(base/'Shadow6/Tools/archive_preflight.py'),'--zip',str(temporary_zip)],check=True)
  # Replace only after both archive creation and the exchange preflight pass.
  fd,installing=tempfile.mkstemp(prefix='.'+output.name+'.',dir=output.parent)
  os.close(fd)
  try:shutil.copyfile(temporary_zip,installing);os.replace(installing,output)
  finally:
   if os.path.exists(installing):os.unlink(installing)
 digest=hashlib.sha256(output.read_bytes()).hexdigest();output.with_suffix(output.suffix+'.sha256').write_text(digest+'  '+output.name+'\n')
 return {'archive':str(output),'bytes':output.stat().st_size,'sha256':digest,'text_files':kept,'excluded_non_text':removed}

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--repositories-root',type=Path,default=Path(__file__).resolve().parents[2]);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--evidence',type=Path);args=parser.parse_args();print(json.dumps(package(args.repositories_root,args.output,args.evidence)))

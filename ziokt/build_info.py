"""Public, bounded startup fingerprints. No credentials or private runtime paths."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()


def semantic(value):
    if isinstance(value,dict):
        return {key:sorted(item) if key in {'required','enum','scopes','type'} and isinstance(item,list) and all(isinstance(entry,str) for entry in item) else semantic(item) for key,item in value.items()}
    if isinstance(value,list):return [semantic(item) for item in value]
    return value


def registry_digest(tools):
    return hashlib.sha256(canonical(sorted(
        [semantic({key:value for key,value in tool.items() if key!='scope'}) for tool in tools],key=lambda tool:tool['name']))).hexdigest()


@lru_cache(maxsize=1)
def snapshot():
    root=Path(__file__).resolve().parents[1]
    if not (root/'ziokt').is_dir():
        from importlib.resources import files
        try:
            value=json.loads(files('ziokt').joinpath('_build_manifest.json').read_text())
            return {**value,'deployment_kind':'packaged-zipapp','assurance':'packaged source manifest; not a runtime or business acceptance proof'}
        except (OSError,ValueError):
            return {'schema':'ziokt.runtime-build.v1','source_commit':None,'python_sources_sha256':None,'deployment_kind':'unidentified-package','assurance':'source identity not assessed'}
    files={};total_bytes=0
    for directory in ('ziokt','openci','spec'):
        for path in sorted((root/directory).rglob('*.py')):
            if path.is_symlink() or '__pycache__' in path.parts:continue
            total_bytes+=path.stat().st_size
            if len(files)>=2048 or total_bytes>128*1024*1024 or path.stat().st_size>2*1024*1024:raise ValueError('build source budget')
            files[str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
    lock=root/'native-sources.lock.json'
    native=json.loads(lock.read_text()) if lock.is_file() else {}
    if lock.is_file():files[lock.name]=hashlib.sha256(lock.read_bytes()).hexdigest()
    declared=root/'DEPLOYED_BUILD.json'
    revision=None;dirty=None
    if declared.is_file():
        info=json.loads(declared.read_text());revision=info.get('source_commit');dirty=False
    elif (root/'.git').exists():
        try:
            revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True,timeout=3).strip()
            dirty=bool(subprocess.check_output(['git','status','--porcelain','--untracked-files=normal'],cwd=root,timeout=3).strip())
        except (OSError,subprocess.SubprocessError):pass
    return {'schema':'ziokt.runtime-build.v1','source_commit':revision,'working_tree_dirty':dirty,
            'python_sources_sha256':hashlib.sha256(canonical(files)).hexdigest(),
            'source_file_count':len(files),'native_sources':native,
            'deployment_kind':'frozen-release' if declared.is_file() else 'working-tree-or-package',
            'assurance':'startup source snapshot; not a runtime or business acceptance proof'}

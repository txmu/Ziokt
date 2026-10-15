"""Read-only component inventory. Source availability is separate from readiness."""
from pathlib import Path
from .protocol import ProtocolError,encoded,strict_json,secure_read

def inventory(root):
    root=Path(root).absolute();source=root/'companions/ecosystem.json'
    if source.is_file():manifest=strict_json(secure_read(source,65536,private=None))
    else:
        from importlib.resources import files
        manifest=strict_json(files('ziokt').joinpath('ecosystem.json').read_bytes(),65536)
    if manifest.get('schema')!='ziokt.ecosystem.v1' or len(manifest.get('components',[]))!=10:raise ProtocolError('INVALID_ECOSYSTEM','versioned ten-component manifest required')
    result=[]
    for item in manifest['components']+manifest['additional_components']:
        path=(root/'companions'/item['source']).absolute()
        if item['id'] in {'shadow6','corium'}:path=root.parent/('Shadow6' if item['id']=='shadow6' else 'Corium')
        result.append({**item,'path':str(path),'source_available':path.is_dir() and not path.is_symlink(),'runtime_verified':False})
    return {'schema':'ziokt.ecosystem-inventory.v1','components':result,'default_enabled':False,'limits':manifest['limits']}

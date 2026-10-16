"""Source-only delivery with per-file digests; makes no native verification claim."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

root = Path(__file__).resolve().parents[1]
projects = {'Ziokt': root, 'Shadow6': root.parent / 'Shadow6', 'Corium': root.parent / 'Corium'}
revisions = {}
files = {}
for name, directory in projects.items():
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=directory).strip():
        raise SystemExit('Commit source before delivery: ' + name)
    revisions[name] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=directory, text=True).strip()
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=directory).decode().split('\0')
    for relative in filter(None, tracked):
        path = directory / relative
        if (not path.is_file() or path.is_symlink() or
                any(part in {'.git', '.runtime', '.venv', 'node_modules', 'target', '__pycache__', 'uploads', 'data'} for part in Path(relative).parts) or
                path.suffix in {'.key', '.sqlite', '.db'} or path.name.startswith('.env')):
            raise SystemExit('Unsafe or generated tracked path: ' + name + '/' + relative)
        files[name + '/' + relative] = path
manifest = {'schema': 'ziokt.source-delivery.v1', 'revisions': revisions,
            'kind': 'source-only', 'native_binaries_included': False,
            'verification': 'Source-only archive; consult the pinned verification report and audit supplements.', 'files': {}}
dist = root / 'dist'
dist.mkdir(exist_ok=True)
output = dist / ('ziokt-sources-' + revisions['Ziokt'][:12] + '.zip')
with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for name, path in sorted(files.items()):
        data = path.read_bytes()
        manifest['files'][name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        member = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
        member.compress_type = zipfile.ZIP_DEFLATED
        member.external_attr = (0o100755 if path.stat().st_mode & 0o111 else 0o100644) << 16
        archive.writestr(member, data)
    archive.writestr('MANIFEST.json', json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
with zipfile.ZipFile(output) as archive:
    if archive.testzip() is not None:
        raise SystemExit('Compressed member integrity failed')
    for name, item in manifest['files'].items():
        if hashlib.sha256(archive.read(name)).hexdigest() != item['sha256']:
            raise SystemExit('Member digest failed: ' + name)
for name, directory in projects.items():
    if (subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=directory, text=True).strip() != revisions[name] or
            subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=directory).strip()):
        raise SystemExit('Source changed during archive creation: ' + name)
digest = hashlib.sha256(output.read_bytes()).hexdigest()
output.with_suffix('.zip.sha256').write_text(digest + '  ' + output.name + '\n')
print(json.dumps({'package': str(output), 'bytes': output.stat().st_size, 'sha256': digest, 'revisions': revisions}, indent=2))

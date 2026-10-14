"""Verify downloaded products and every compiled Core source before reuse."""
import hashlib,json,tarfile,subprocess
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1];lock=json.loads((root/'ci/native-reuse.lock.json').read_text());archive=Path(sys.argv[1]);native=root.parent/'Shadow6'
if hashlib.sha256(archive.read_bytes()).hexdigest()!=lock['sha256']:raise ValueError('native reuse archive digest differs')
compiled={'.go','.rs','.nim','.idr','.gleam','.erl','.ads','.adb','.zig','.d','.cpp','.cc','.c','.h','.carp','.ha','.toml','.mod','.sum'}
with tarfile.open(archive) as bundle:
 members={m.name:m for m in bundle if m.isfile()}
 names=subprocess.check_output(['git','ls-files','-z','--','Core-*'],cwd=native).decode().split('\0')
 for name in filter(None,names):
  source=native/name
  if source.suffix not in compiled:continue
  member=members.get('Shadow6/'+name)
  if not source.is_file() or member is None or bundle.extractfile(member).read()!=source.read_bytes():raise ValueError('compiled native source changed: '+name)
print('Pinned native archive and unchanged Core source bytes verified')

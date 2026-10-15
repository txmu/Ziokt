"""Deterministic source/PWA/native-baseline bundle; never contains user state."""
import argparse,hashlib,json,subprocess,zipfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--native',type=Path,required=True);parser.add_argument('--report',type=Path,required=True);parser.add_argument('--etp',type=Path);parser.add_argument('--pwas',type=Path);args=parser.parse_args()
lock=json.loads((root/'ci/native-reuse.lock.json').read_text())
if hashlib.sha256(args.native.read_bytes()).hexdigest()!=lock['sha256']:raise ValueError('joint bundle native artifact digest mismatch')
report=json.loads(args.report.read_text())
if report.get('regression',{}).get('passed') is not True:raise ValueError('successful recorded regression required before joint packaging')
revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip();dist=root/'dist';dist.mkdir(exist_ok=True);output=dist/('ziokt-ecosystem-'+revision[:12]+'.zip')
files={};revisions={}
for project,base in [('Ziokt',root),('Shadow6',root.parent/'Shadow6'),('Corium',root.parent/'Corium')]:
 revisions[project]=subprocess.check_output(['git','rev-parse','HEAD'],cwd=base,text=True).strip()
 if subprocess.check_output(['git','status','--porcelain','--untracked-files=all'],cwd=base).strip():raise ValueError('commit source changes before packaging: '+project)
 names=subprocess.check_output(['git','ls-files','-z'],cwd=base).decode().split('\0')
 for name in filter(None,names):
  file=base/name
  if file.is_symlink() or not file.is_file():raise ValueError('joint source must be a regular tracked file: '+name)
  if any(part in {'node_modules','__pycache__','.git','.runtime','.venv','data','uploads','target'} for part in Path(name).parts):raise ValueError('private/generated path unexpectedly tracked: '+name)
  if file.suffix in {'.key','.sqlite','.db'} or file.name.startswith('.env'):raise ValueError('credential/state filename unexpectedly tracked: '+name)
  files[project+'/'+name]=file
if report.get('etp',{}).get('native_gateway_compiled_and_run'):
 if args.etp is None or hashlib.sha256(args.etp.read_bytes()).hexdigest()!=report['etp'].get('gateway_sha256'):raise ValueError('CI-proven native ETP gateway required')
 files['native-etp/ziokt_gateway']=args.etp
 # Bind the binary to the verified functional source even if a later commit only records results.
 verified=report['etp']['gateway_source_revision']
 if subprocess.call(['git','diff','--quiet',verified,'HEAD','--','ziokt','spec','companions','tools','.github','ci'],cwd=root):raise ValueError('functional source changed after ETP verification')
pwas=args.pwas or root/'companions'
for app, pwa in [('sim-manager',pwas/'sim-manager/src/dist'),('tri',pwas/'tri/app/dist')]:
 if not (pwa/'manifest.webmanifest').is_file() or not (pwa/'sw.js').is_file():raise ValueError('verified built '+app+' PWA required')
 for file in sorted(pwa.rglob('*')):
  if file.is_file() and not file.is_symlink():files['apps/'+app+'/'+str(file.relative_to(pwa))]=file
files['native-baseline/'+args.native.name]=args.native;files['verification/REPORT.json']=args.report
manifest={'schema':'ziokt.joint-package.v1','revisions':revisions,'native_baseline':lock,'verification':report,'files':{}}
with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
 for name,file in sorted(files.items()):
  data=file.read_bytes();manifest['files'][name]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()};info=zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=(0o100755 if file.stat().st_mode&0o111 else 0o100644)<<16;archive.writestr(info,data)
 archive.writestr('MANIFEST.json',json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
# Independently re-read every compressed file before reporting success.
with zipfile.ZipFile(output) as archive:
 if archive.testzip() is not None:raise ValueError('compressed joint package integrity failure')
 for name,item in manifest['files'].items():
  if hashlib.sha256(archive.read(name)).hexdigest()!=item['sha256']:raise ValueError('joint member integrity failure: '+name)
for project,base in [('Ziokt',root),('Shadow6',root.parent/'Shadow6'),('Corium',root.parent/'Corium')]:
 if subprocess.check_output(['git','rev-parse','HEAD'],cwd=base,text=True).strip()!=revisions[project] or subprocess.check_output(['git','status','--porcelain','--untracked-files=all'],cwd=base).strip():raise ValueError('source changed while the joint package was being created: '+project)
sha=hashlib.sha256(output.read_bytes()).hexdigest();output.with_suffix('.zip.sha256').write_text(sha+'  '+output.name+'\n');print(json.dumps({'package':str(output),'bytes':output.stat().st_size,'sha256':sha,'source_revisions':revisions},indent=2))

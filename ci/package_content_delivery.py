"""Package only verified CI products and an explicit, accurate evidence manifest."""
import hashlib,json,os,subprocess,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];dist=root/'dist'
revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
if subprocess.check_output(['git','status','--porcelain','--untracked-files=all'],cwd=root).strip():raise SystemExit('delivery requires committed clean source')
files={}
for path in sorted(dist.glob('ziokt-sources-*.zip')):files['sources/'+path.name]=path
for path in sorted((dist/'native').rglob('*')):
 if path.is_file() and path.name in {'mailbox_replica_runner','tc16_unified_runner','ziokt_gateway'}:files['native/'+path.name]=path
for path in sorted((dist/'extensions').glob('*')):
 if path.is_file():files['extensions/'+path.name]=path
for path in sorted((dist/'evidence').rglob('*.txt')):files['evidence/'+str(path.relative_to(dist/'evidence'))]=path
files['ziokt.pyz']=dist/'ziokt.pyz'
if not any(k.startswith('sources/') for k in files) or len([k for k in files if k.startswith('native/')])!=3:raise SystemExit('missing tested source or native artifacts')
report={'schema':'ziokt.content-delivery.v1','source_revision':revision,'run_id':os.environ.get('GITHUB_RUN_ID'),'scope':'Content application, native mailbox and TC16 compatibility tests; not full ecosystem completion','unsigned_webextensions':True,'all_requested_features_complete':False,'files':{}}
output=dist/f'ziokt-content-delivery-{revision[:12]}.zip'
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
 for name,path in sorted(files.items()):
  if not path.is_file() or path.is_symlink():raise SystemExit('regular artifact required')
  data=path.read_bytes();report['files'][name]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()};info=zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=(0o100755 if name.startswith('native/') else 0o100644)<<16;archive.writestr(info,data)
 archive.writestr('DELIVERY.json',json.dumps(report,ensure_ascii=False,indent=2)+'\n')
with zipfile.ZipFile(output) as archive:
 if archive.testzip():raise SystemExit('archive integrity')
 for name,item in report['files'].items():
  if hashlib.sha256(archive.read(name)).hexdigest()!=item['sha256']:raise SystemExit('artifact digest')
digest=hashlib.sha256(output.read_bytes()).hexdigest();output.with_suffix('.zip.sha256').write_text(digest+'  '+output.name+'\n');print(json.dumps({'path':str(output),'sha256':digest,'source_revision':revision,'full_scope_complete':False}))

#!/usr/bin/env python3
"""Deterministic unsigned WebExtension packages; never publishes to add-on stores."""
import argparse,hashlib,json,shutil,zipfile,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def package(output):
 output=Path(output);output.mkdir(parents=True,exist_ok=True)
 source=ROOT/'extensions'/'ziokt';reports=[]
 for target in ('chromium','firefox','thunderbird'):
  directory=output/target
  if directory.exists():shutil.rmtree(directory)
  directory.mkdir()
  manifest=json.loads((source/f'manifest.{target}.json').read_text())
  (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
  for name in ('popup.html','popup.js','popup.css','background.js'):shutil.copyfile(source/name,directory/name)
  shutil.copytree(source/'_locales',directory/'_locales')
  # Same verified application client used by the standalone application.
  shutil.copyfile(ROOT/'ziokt'/'web'/'application-client.js',directory/'application-client.js')
  suffix='zip' if target=='chromium' else 'xpi';path=output/f'ziokt-companion-{target}.{suffix}'
  with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
   for member in sorted(directory.rglob('*')):
    if member.is_file():
     info=zipfile.ZipInfo(str(member.relative_to(directory)),date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;archive.writestr(info,member.read_bytes())
  digest=hashlib.sha256(path.read_bytes()).hexdigest();path.with_suffix(path.suffix+'.sha256').write_text(digest+'  '+path.name+'\n');reports.append({'target':target,'path':str(path),'sha256':digest,'store_signed':False})
 # Keep provenance outside the archives so identical sources retain identical bytes.
 revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 dirty=bool(subprocess.check_output(['git','status','--porcelain','--untracked-files=normal','--','extensions/ziokt','ziokt/web/application-client.js','tools/package_webextensions.py'],cwd=ROOT,text=True).strip())
 versions={target:json.loads((source/f'manifest.{target}.json').read_text())['version'] for target in ('chromium','firefox','thunderbird')}
 provenance={'schema':'ziokt.webextensions.build.v1','source_commit':revision,'source_dirty':dirty,'store_signed':False,'versions':versions,'packages':[{k:v for k,v in record.items() if k!='path'}|{'file':Path(record['path']).name} for record in reports]}
 provenance_path=output/'build-source.json'
 provenance_path.write_text(json.dumps(provenance,sort_keys=True,indent=2)+'\n')
 checksums=[record['sha256']+'  '+Path(record['path']).name for record in reports]
 checksums.append(hashlib.sha256(provenance_path.read_bytes()).hexdigest()+'  build-source.json')
 (output/'SHA256SUMS').write_text('\n'.join(checksums)+'\n')
 return reports


if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-directory',type=Path,default=ROOT/'dist'/'extensions');args=parser.parse_args();print(json.dumps(package(args.output_directory),indent=2))

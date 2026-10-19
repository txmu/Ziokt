#!/usr/bin/env python3
"""Deterministic unsigned WebExtension packages; never publishes to add-on stores."""
import argparse,hashlib,json,shutil,zipfile
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
 return reports


if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-directory',type=Path,default=ROOT/'dist'/'extensions');args=parser.parse_args();print(json.dumps(package(args.output_directory),indent=2))

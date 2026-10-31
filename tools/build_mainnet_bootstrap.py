#!/usr/bin/env python3
"""Publishable chain-pair bootstrap: canonical ledger, public anchors and source only."""
import argparse,hashlib,json,pathlib,shutil,sqlite3,tempfile,zipfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--production',type=pathlib.Path,required=True);p.add_argument('--ledgers',type=pathlib.Path,required=True);p.add_argument('--remote-certificates',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
 ledgers=json.loads(a.ledgers.read_text());manifest={'schema':'ziokt.mainnet-bootstrap.v1','business_chain':'primary','chains':{},'files':{}}
 a.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='ziokt-public-bootstrap-') as directory:
  stage=pathlib.Path(directory)
  def copy(source,relative):
   target=stage/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
  native=ROOT.parent/'Corium'
  copy(native/'corix_v108.sh','native/corix_v108.sh')
  for source in native.glob('*.py'):
   if not source.name.startswith('test_'):copy(source,'native/'+source.name)
  for name in ('join_mainnet.py','sync_native_snapshot.py','refresh_peer_addresses.py'):copy(ROOT/'tools'/name,'tools/'+name)
  copy(ROOT/'tools/deploy_dna_consumer.py','runtime/tools/deploy_dna_consumer.py')
  for source in (ROOT/'ziokt').rglob('*.py'):
   if '__pycache__' not in source.parts:copy(source,'runtime/'+str(source.relative_to(ROOT)))
  for role,subroot,net,port,remoteid in [('primary','corium','ziokt-main',7234,'7c175bafc19a6846e755cda406a5540a8bfaa74c400b7d425039e0ace5b54d61'),('dna','dna-sidechain','ziokt-dna-side-20261024',7235,'720138201b1acd8cf065b851d5d6e97394498eb2eb3a0ede81163655ed87db07')]:
   etc=a.production/subroot/'etc/corix/networks'/net
   for name in ('genesis.json','recovery.json','recovery-state.json'):
    if (etc/name).is_file():copy(etc/name,role+'/'+name)
   copy(pathlib.Path(ledgers[role]['path']),role+'/chain.db')
   copy(etc/'tls.crt',role+'/seed-local.crt');copy(a.remote_certificates/(role+'.crt'),role+'/seed-remote.crt')
   public=(etc/'identity.key.pub').read_text().rstrip('\n');identity=hashlib.sha256(public.encode()).hexdigest()
   manifest['chains'][role]={'network':net,'port':port,'genesis_sha256':hashlib.sha256((etc/'genesis.json').read_bytes()).hexdigest(),'snapshot':ledgers[role]['tip'],'seeds':[{'host':'p2p.ziokt.com','port':port,'identity':identity,'certificate':role+'/seed-local.crt'},{'host':'38.175.194.110','port':port,'identity':remoteid,'certificate':role+'/seed-remote.crt'}]}
  for source in stage.rglob('*'):
   if source.is_file():manifest['files'][str(source.relative_to(stage))]=hashlib.sha256(source.read_bytes()).hexdigest()
  (stage/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
  temporary=a.output.with_suffix('.partial')
  with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
   for source in stage.rglob('*'):
    if source.is_file():archive.write(source,str(source.relative_to(stage)))
  temporary.replace(a.output)
 digest=hashlib.sha256(a.output.read_bytes()).hexdigest();a.output.with_suffix('.zip.sha256').write_text(digest+'  '+a.output.name+'\n')
 print(json.dumps({'archive':str(a.output),'sha256':digest,'bytes':a.output.stat().st_size,'files':len(manifest['files'])+1}))
if __name__=='__main__':main()

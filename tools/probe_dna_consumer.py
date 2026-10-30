#!/usr/bin/env python3
"""Submit real signed RNA status reads to an installed local consumer."""
import argparse,hashlib,json,sqlite3,sys,time,urllib.request
from pathlib import Path
from cryptography.hazmat.primitives import serialization
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.dna_protocol import rna_sign
from ziokt.protocol import encoded,secure_read,strict_json
p=argparse.ArgumentParser();p.add_argument('--root',required=True);args=p.parse_args();root=Path(args.root);c=strict_json(secure_read(root/'consumer.json',65536));key=serialization.load_pem_private_key(secure_read(root/'producer.pem',4096),None);pem=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n');sender=hashlib.sha256(pem.encode()).hexdigest()
with sqlite3.connect(root/'state/consumer.sqlite') as db:seq=db.execute('SELECT sequence FROM sequences WHERE sender=?',(sender,)).fetchone();seq=seq[0] if seq else 0
jobs=[]
for component in c['targets']:
 seq+=1;command={'schema':'ziokt.dna-command.v1','component':component,'operation':'status.get','resource':'','arguments':{},'expected_revision':None};frame=rna_sign(key,c['chain'],c['policy'],sender,seq,int(time.time()),encoded(command))
 req=urllib.request.Request(f"http://127.0.0.1:{c['port']}/rna",data=encoded(frame),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=5) as response:jobs.append({'component':component,**json.load(response)})
for attempt in range(15):
 with sqlite3.connect(root/'state/consumer.sqlite') as db:
  for job in jobs:
   row=db.execute('SELECT state,result,error FROM jobs WHERE id=?',(job['id'],)).fetchone();job.update(state=row[0],result=json.loads(row[1]) if row[1] else None,error=row[2])
 if all(j['state'] not in {'queued','dispatching'} for j in jobs):break
 time.sleep(1)
print(json.dumps({'transport':'authenticated loopback RNA ingress','chain_inclusion':'not_assessed','jobs':jobs},sort_keys=True))
if not all(j['state']=='completed_read' for j in jobs):sys.exit(1)

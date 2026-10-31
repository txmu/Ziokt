#!/usr/bin/env python3
"""Register an owner-signed public ZDNS name with zero contribution requirement."""
import argparse,hashlib,json,os,secrets,sys,time,urllib.request
from pathlib import Path
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.protocol import encoded,secure_read
from ziokt.public_transactions import transaction_bytes,signing_bytes
from ziokt.security import sign

def private_write(path,body):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as target:target.write(body)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gateway',default='https://app.ziokt.com');p.add_argument('--network',default='ziokt-main');p.add_argument('--name',required=True);p.add_argument('--address',required=True);p.add_argument('--key-file',type=Path,required=True);p.add_argument('--receipt',type=Path);a=p.parse_args()
 if not a.gateway.startswith('https://'):raise ValueError('public HTTPS gateway required')
 if not a.key_file.exists():
  key=ec.generate_private_key(ec.SECP256K1());private_write(a.key_file,key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
 key=serialization.load_pem_private_key(secure_read(a.key_file,4096),None)
 public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
 seedpath=a.key_file.with_suffix('.naming.seed')
 if not seedpath.exists():private_write(seedpath,secrets.token_bytes(32))
 seed=secure_read(seedpath,32);expires=int(time.time())+30*86400
 from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
 delegate=Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
 descriptor={'public_dns':[{'type':'A','value':a.address,'ttl':60}],'services':{},'private':None}
 from ziokt.naming import public_records
 public_records(descriptor['public_dns'])
 payload={'network_id':a.network,'component':'corium','path':a.name,'parent_revision':1,'revision':1,'expires_at':expires,'delegate':None,'descriptor':descriptor}
 publication={'ziokt_naming':{'network_id':a.network,'owner':delegate,'revision':1,'expires_at':expires,'published_suffixes':['cor','c','corium','corix'],'delegations':{a.name:sign(payload,seed,'Ziokt/name-delegation/v1')}}}
 data={'domain_name':a.name,'target_hash':hashlib.sha256(encoded(publication)).hexdigest(),'publication':publication,'proof_of_genesis_contribution':{'burned_amount':0},'proof_of_contribution':{'burned_amount':0}}
 tx={'type':'nns_register','data':data,'timestamp':int(time.time()),'public_key':public,'signature':''}
 tx['signature']=key.sign(transaction_bytes(a.network,tx),ec.ECDSA(hashes.SHA256())).hex()
 request={'schema':'ziokt.public-transaction.v1','network':a.network,'transaction':tx,'authorization':key.sign(signing_bytes(a.network,tx),ec.ECDSA(hashes.SHA256())).hex()}
 with urllib.request.urlopen(urllib.request.Request(a.gateway.rstrip('/')+'/api/gateway/transactions',data=encoded(request),headers={'Content-Type':'application/json'}),timeout=30) as response:result=json.load(response)
 receipt={'name':a.name+'.corium','owner':hashlib.sha256(public.encode()).hexdigest(),'network':a.network,'contribution_burn':0,**result}
 if a.receipt:a.receipt.write_text(json.dumps(receipt,indent=2)+'\n')
 print(json.dumps(receipt))
if __name__=='__main__':main()

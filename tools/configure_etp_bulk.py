#!/usr/bin/env python3
"""Configure native FileShare v2 from a reviewed CI binary, with no compilation."""
import argparse,hashlib,json,secrets,sys
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.protocol import secure_read

def configure(config,binary,digest,base_port):
 config=Path(config);binary=Path(binary).resolve()
 if 'sha256:'+hashlib.sha256(secure_read(binary,128*1024*1024,private=False)).hexdigest()!=digest:raise ValueError('CI binary digest mismatch')
 value=json.loads(secure_read(config));root=config.parent/'etp-bulk';root.mkdir(mode=0o700,exist_ok=True)
 if 'etp_bulk' in value:return {'configured':True,'changed':False}
 keys=[X25519PrivateKey.generate() for _ in range(4)];addresses=['127.0.0.1:'+str(base_port+i) for i in range(4)];paths=[]
 for i,key in enumerate(keys):
  path=root/('node-'+str(i)+'.json');paths.append(str(path))
  data={'bind':addresses[i],'private_key':key.private_bytes_raw().hex(),'peers':{address:keys[j].public_key().public_bytes_raw().hex() for j,address in enumerate(addresses) if j!=i},'relay':True}
  with path.open('x') as out:json.dump(data,out)
  path.chmod(0o600)
 key=secrets.token_hex(32)
 value['etp_bulk']={'binary':str(binary),'digest':digest,'nodes':paths,'clients':[{'node':0,'hops':addresses[1:],'key':key,'scope':'gateway-bulk'}],'sources':[{'node':3,'hops':list(reversed(addresses[:3])),'key':key,'scope':'gateway-bulk'}]}
 temporary=config.with_suffix('.new');temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.chmod(0o600);temporary.replace(config)
 return {'configured':True,'changed':True,'native_nodes':4,'hops':3}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',required=True,type=Path);p.add_argument('--binary',required=True,type=Path);p.add_argument('--digest',required=True);p.add_argument('--base-port',type=int,default=9260);a=p.parse_args();print(json.dumps(configure(a.config,a.binary,a.digest,a.base_port)))

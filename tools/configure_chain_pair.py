#!/usr/bin/env python3
"""Configure an existing native chain pair; both chains must be initialized."""
import argparse,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ziokt.explorer_networks import ExplorerNetworks,PROTOCOL
from ziokt.protocol import encoded

def configure(identifier,name,primary,dna,business_chain):
    profile={'id':identifier,'name':name,'protocol':PROTOCOL,'business_chain':business_chain}
    for role,(root,network) in [('primary',primary),('dna',dna)]:
        root=Path(root).resolve()
        path=root/'var/lib/corix/networks'/network/'blockchain/chain.db'
        if not path.is_file() or path.is_symlink():raise ValueError('both native chains must be initialized before configuring the pair')
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            row=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()
            if not row:raise ValueError('both native chains require genesis blocks')
        profile[role]={'state_root':str(root),'network_id':network,'genesis_hash':row[0]}
    view=ExplorerNetworks(profile['primary']['state_root'],profile['primary']['network_id'],[profile])
    for role in ('primary','dna'):view.query('/api/explorer/summary?network='+identifier+'&chain='+role)
    return profile

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('id','name','primary-root','primary-network','dna-root','dna-network','output'):p.add_argument('--'+key,required=True)
    p.add_argument('--business-chain',choices=['primary','dna'],required=True)
    a=p.parse_args();value=configure(a.id,a.name,(a.primary_root,a.primary_network),(a.dna_root,a.dna_network),a.business_chain)
    target=Path(a.output).absolute()
    with target.open('xb') as out:out.write(encoded(value)+b'\n')
    target.chmod(0o600);print(json.dumps({'configured':True,'business_chain':a.business_chain,'roles':['primary','dna'],'output':str(target)}))

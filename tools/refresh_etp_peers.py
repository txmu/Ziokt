#!/usr/bin/env python3
"""Refresh owner-approved ETP peers from DNS while preserving their pinned keys."""
import argparse,json,os,re,socket,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ziokt.protocol import secure_read

def refresh(path):
    config=json.loads(secure_read(path,65536));assert config['schema']=='ziokt.etp-peer-addresses.v1'
    prepared=[]
    for entry in config['nodes']:
        target=Path(entry['config']);original=secure_read(target,65536);value=json.loads(original);transport=value.setdefault('peers',{});replicas=value['mailbox']['replication']['peers']
        resolved=[]
        for peer in entry['peers']:
            if not re.fullmatch('[A-Za-z0-9.-]{1,253}',peer['host']) or type(peer['port']) is not int or not 1024<=peer['port']<=65535:raise ValueError('fixed approved DNS peer required')
            for name in ('transport_key','mailbox_key'):
                if not re.fullmatch('[a-f0-9]{64}',peer[name]):raise ValueError('pinned public key required')
            addresses=sorted({row[4][0] for row in socket.getaddrinfo(peer['host'],peer['port'],socket.AF_INET,socket.SOCK_STREAM)})
            if not addresses:raise ValueError('DNS peer has no IPv4 address')
            existing=next((address.split(':')[0] for address,key in transport.items() if key==peer['transport_key'] and address.split(':')[0] in addresses),None)
            resolved.append((peer,(existing or addresses[0])+':'+str(peer['port'])))
        for peer,address in resolved:
            for mapping,key in ((transport,peer['transport_key']),(replicas,peer['mailbox_key'])):
                for old in [a for a,k in mapping.items() if k==key and a!=address]:del mapping[old]
                mapping[address]=key
        if value!=json.loads(original):prepared.append((target,value))
    # Resolve every approved peer before changing any file.
    for target,value in prepared:
        pending=target.with_name('.'+target.name+'.peer-refresh');fd=os.open(pending,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as out:json.dump(value,out);out.flush();os.fsync(out.fileno())
        os.replace(pending,target)
    return {'changed':len(prepared),'service':config['service']}

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--restart',action='store_true');a=p.parse_args();result=refresh(a.config)
    if a.restart and result['changed']:
        if not re.fullmatch('[a-zA-Z0-9_-]{1,100}',result['service']):raise ValueError('fixed service required')
        subprocess.run((['sudo','-n'] if os.geteuid()!=0 else [])+['systemctl','restart',result['service']],check=True)
    print(json.dumps(result))
if __name__=='__main__':main()

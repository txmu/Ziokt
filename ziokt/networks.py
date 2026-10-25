"""Generate matching explorer and ZDNS views from pinned dual-chain profiles."""
import argparse
import json
from pathlib import Path
import re

from .explorer_networks import ExplorerNetworks
from .protocol import ProtocolError,secure_read,strict_json


def configuration(value,*,verify_databases=True):
    if (not isinstance(value,dict) or set(value)!={'schema','default','networks'}
            or value['schema']!='ziokt.networks.v1' or not isinstance(value['default'],str)
            or not isinstance(value['networks'],list) or not 1<=len(value['networks'])<=16):
        raise ProtocolError('NETWORK_CONFIG','exact bounded dual-chain network catalog required')
    first=value['networks'][0]
    if not isinstance(first,dict) or not isinstance(first.get('primary'),dict):raise ProtocolError('NETWORK_CONFIG','primary descriptor required')
    primary=first['primary']
    registry=ExplorerNetworks(primary.get('state_root'),primary.get('network_id'),value['networks'])
    if value['default'] not in {p['id'] for p in value['networks']}:raise ProtocolError('NETWORK_CONFIG','configured default network required')
    realms={};observed=[]
    for profile in value['networks']:
        for role in ('primary','dna'):
            chain=profile[role];realm=profile['id']+('-dna' if role=='dna' else '')
            if not re.fullmatch('[A-Za-z0-9_-]{1,64}',realm) or realm in realms:raise ProtocolError('NETWORK_CONFIG','unique bounded ZDNS realm required')
            root=Path(chain['state_root']);native=chain['network_id']
            realms[realm]={'network_id':native,'sources':{'corium':{'forum_db':str(root/'var/lib/corix/networks'/native/'forum/forum.db'),
                          'chain_db':str(root/'var/lib/corix/networks'/native/'blockchain/chain.db'),
                          'objects':str(root/'var/lib/corix/p2p/objects')}}}
            if verify_databases:
                reader,_=registry.select(profile['id'],role);summary=reader.query('/api/explorer/summary')
                observed.append({'network':profile['id'],'role':role,'genesis_hash':summary['genesis_hash'],'tip_height':summary['tip_height']})
    return {'schema':'ziokt.network-config-plan.v1','default':value['default'],
            'explorer_networks':value['networks'],'dns':{'schema':'ziokt.dns.v2','listen':'127.0.0.1','port':5353,'doh_port':8188,'default_realm':value['default'],'realms':realms},
            'observations':observed,'services_modified':False}


def main(argv=None):
    parser=argparse.ArgumentParser(prog='ziokt networks');sub=parser.add_subparsers(dest='action',required=True)
    for name in ('inspect','configure'):
        p=sub.add_parser(name);p.add_argument('manifest',type=Path)
        if name=='configure':p.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args(argv);value=strict_json(secure_read(args.manifest,65536,private=None))
    result=configuration(value,verify_databases=args.action=='configure')
    if args.action=='configure':
        directory=args.directory.absolute()
        if directory.exists() or directory.is_symlink() or directory.resolve()!=directory:raise ProtocolError('NETWORK_CONFIG','new regular configuration directory required')
        directory.mkdir(mode=0o700,parents=True)
        from .cli import write_exclusive
        write_exclusive(directory/'dns.json',result['dns'])
        write_exclusive(directory/'explorer-networks.json',result['explorer_networks'])
        write_exclusive(directory/'network-plan.json',result)
        result={'directory':str(directory),'default_realm':value['default'],'observations':result['observations'],'next_step':'review and select these files in the node service configuration'}
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())

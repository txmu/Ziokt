#!/usr/bin/env python3
"""Create both independent mainnet nodes, verify history, then optionally mine."""
import argparse,hashlib,json,os,pwd,re,shlex,shutil,sqlite3,subprocess,tempfile,urllib.request,zipfile
from pathlib import Path

URL='https://app.ziokt.com/mainnet/bootstrap.zip'

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    path.write_text(json.dumps(value,indent=2)+'\n' if not isinstance(value,str) else value);path.chmod(0o600)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--business-chain',choices=['primary','dna'],default='primary')
    parser.add_argument('--bootstrap-url',default=URL);parser.add_argument('--bootstrap-file',type=Path)
    parser.add_argument('--sha256');parser.add_argument('--enable-services',action='store_true')
    args=parser.parse_args();root=args.root.resolve()
    if root.exists() and any(root.iterdir()):raise ValueError('choose a new empty node directory')
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.TemporaryDirectory(prefix='ziokt-mainnet-bootstrap-') as temp:
        archive=Path(temp)/'bootstrap.zip'
        if args.bootstrap_file:shutil.copyfile(args.bootstrap_file,archive)
        else:
            if not args.bootstrap_url.startswith('https://'):raise ValueError('HTTPS bootstrap URL required')
            with urllib.request.urlopen(args.bootstrap_url,timeout=30) as response,archive.open('wb') as target:
                total=0
                while chunk:=response.read(1024*1024):
                    total+=len(chunk)
                    if total>64*1024**2:raise ValueError('bootstrap download budget')
                    target.write(chunk)
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        if args.sha256 and digest!=args.sha256:raise ValueError('bootstrap SHA-256 differs')
        bundle=root/'bootstrap';bundle.mkdir(mode=0o700)
        with zipfile.ZipFile(archive) as source:
            if len(source.infolist())>512 or sum(i.file_size for i in source.infolist())>128*1024**2:raise ValueError('bootstrap expansion budget')
            for entry in source.infolist():
                path=Path(entry.filename)
                if path.is_absolute() or '..' in path.parts or entry.is_dir() or entry.external_attr>>16&0o170000==0o120000:raise ValueError('regular relative bootstrap files required')
                target=bundle/path;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                target.write_bytes(source.read(entry));target.chmod(0o600)
        manifest=json.loads((bundle/'manifest.json').read_text())
        if manifest['schema']!='ziokt.mainnet-bootstrap.v1' or set(manifest['chains'])!={'primary','dna'}:raise ValueError('complete mainnet chain pair required')
        for relative,expected in manifest['files'].items():
            if Path(relative).is_absolute() or '..' in Path(relative).parts or hashlib.sha256((bundle/relative).read_bytes()).hexdigest()!=expected:raise ValueError('bootstrap file digest differs')
        source=bundle/'native/corix_v108.sh';source.chmod(0o700)
        providers=[];units=[];chains={}
        for role in ('primary','dna'):
            item=manifest['chains'][role];network=item['network'];port=item['port']
            if network!=('ziokt-main' if role=='primary' else 'ziokt-dna-side-20261024') or type(port)is not int:raise ValueError('fixed mainnet network required')
            state=root/role;etc=state/'etc/corix/networks'/network;etc.mkdir(parents=True,mode=0o700)
            for name in ('genesis.json','recovery.json','recovery-state.json'):
                path=bundle/role/name
                if path.exists():shutil.copyfile(path,etc/name);(etc/name).chmod(0o600)
            conf=etc/'corix.conf'
            write(conf,f'[main]\ndep_mode = manual\nbuild_jobs = 1\nenable_fuzzy_finder = false\n[network]\nid = {network}\n[p2p]\nport = {port}\npublic_address_mode = auto\nenable_upnp = false\nauto_trust_new_nodes = false\ntls_ech_enabled = false\ntls_no_sni_client = true\n[gateway]\nport = {port+3000}\n[blockchain]\nconsensus = pos\n[ziokt]\nenabled = TRUE\nfederation_id = ziokt-mainnet\nprovider_id = {role}-node\n')
            env=dict(os.environ,CORIUM_ROOT=str(state),CORIUM_NETWORK_ID_OVERRIDE=network,CORIUM_TEST_NO_DAEMONS='1')
            env.pop('CORIUM_CONSENSUS_HOLD_FILE',None)
            subprocess.run(['bash',str(source),'init','--state-only'],env=env,check=True,timeout=180)
            for seed in item['seeds']:
                host,seedport,identity=seed['host'],seed['port'],seed['identity']
                if not re.fullmatch('[a-zA-Z0-9.-]+',host) or not re.fullmatch('[a-f0-9]{64}',identity) or type(seedport)is not int or not 1<=seedport<=65535:raise ValueError('bounded seed route')
                cache=state/'var/lib/corix/p2p/peer_certs';cache.mkdir(parents=True,exist_ok=True,mode=0o700)
                shutil.copyfile(bundle/seed['certificate'],cache/(host+'_'+str(seedport)+'.pem'))
                subprocess.run(['bash','-c','source "$1"; dht_add_node "$2" tcp "$3" "$4"','ziokt-seed',str(source),identity,host,str(seedport)],env=env,check=True,timeout=30)
            ledger=bundle/role/'chain.db'
            subprocess.run(['python3',str(bundle/'tools/sync_native_snapshot.py'),'--source',str(source),'--root',str(state),'--network',network,'--snapshot',str(ledger),'--sha256',manifest['files'][role+'/chain.db'],'--apply'],env=env,check=True)
            key=(etc/'identity.key.pub').read_text().rstrip('\n');identity=hashlib.sha256(key.encode()).hexdigest()
            chains[role]={'root':str(state),'network_id':network,'identity':identity}
            providers.append({'native_project':'corium','provider_id':role+'-node','root':str(source.parent),'native_config':str(conf),'entrypoint_digest':'sha256:'+hashlib.sha256(source.read_bytes()).hexdigest(),'network_id':network,'state_root':str(state)})
            write(state/'allow_empty_blocks','')
            for action in ('p2p','consensus'):
                runner=root/(role+'-'+action+'.sh')
                script='#!/bin/bash\numask 077\nexport CORIUM_ROOT='+shlex.quote(str(state))+' CORIUM_NETWORK_ID_OVERRIDE='+shlex.quote(network)+' CORIUM_GATEWAY_PORT='+str(port+3000)+'\nsource '+shlex.quote(str(source))+'\nload_config\n'+('dht_server_daemon; wait' if action=='p2p' else 'export CORIUM_MINER_POLL_SECONDS=${CORIUM_MINER_POLL_SECONDS:-120}; _consensus_daemon_loop')+'\n'
                write(runner,script);runner.chmod(0o700)
                name='ziokt-'+role+'-'+action+'.service'
                unit='[Unit]\nDescription=Ziokt open mainnet '+role+' '+action+'\nAfter=network-online.target\n[Service]\nType=simple\nExecStart='+shlex.quote(str(runner))+'\nRestart=on-failure\nRestartSec=5\nUMask=0077\n[Install]\nWantedBy='+('multi-user.target' if os.geteuid()==0 else 'default.target')+'\n'
                write(root/name,unit);units.append((name,root/name))
        write(root/'federation.json',{'schema':'ziokt.federation.v1','enabled':True,'federation_id':'ziokt-mainnet','providers':providers})
        write(root/'chain-pair.json',{'schema':'ziokt.chain-pair.v1','business_chain':args.business_chain,'chains':chains,'bootstrap_sha256':digest})
        for role,item in chains.items():
            consumer=root/(role+'-consumer')
            command=['python3',str(bundle/'runtime/tools/deploy_dna_consumer.py'),'--root',str(consumer),'--federation',str(root/'federation.json'),'--chain-database',str(Path(item['root'])/'var/lib/corix/networks'/item['network_id']/'blockchain/chain.db'),'--chain-role',role,'--network-id',item['network_id'],'--provider-id',role+'-node']
            subprocess.run(command,check=True)
            name='ziokt-'+role+'-consumer.service';units.append((name,consumer/name))
        refresh=['/usr/bin/python3',str(bundle/'tools/refresh_peer_addresses.py'),'--source',str(source)]
        for role,item in chains.items():refresh.extend(['--chain',item['root'],item['network_id']])
        address_unit='[Unit]\nDescription=Refresh mainnet peer addresses\nAfter=network-online.target\n[Service]\nType=oneshot\nUMask=0077\nExecStart='+shlex.join(refresh).replace('%','%%')+'\n'
        write(root/'ziokt-peer-addresses.service',address_unit)
        write(root/'ziokt-peer-addresses.timer','[Unit]\nDescription=Track mainnet public address changes\n[Timer]\nOnBootSec=30s\nOnUnitInactiveSec=60s\n[Install]\nWantedBy=timers.target\n')
        units.extend((name,root/name) for name in ('ziokt-peer-addresses.service','ziokt-peer-addresses.timer'))

        if args.enable_services:
            directory=Path('/etc/systemd/system') if os.geteuid()==0 else Path.home()/'.config/systemd/user';directory.mkdir(parents=True,exist_ok=True)
            systemctl=['systemctl']+([] if os.geteuid()==0 else ['--user'])
            for name,path in units:shutil.copyfile(path,directory/name)
            subprocess.run(systemctl+['daemon-reload'],check=True)
            subprocess.run(systemctl+['enable','--now',*[name for name,_ in units]],check=True)
        print(json.dumps({'schema':'ziokt.mainnet-joined.v1','root':str(root),'business_chain':args.business_chain,'chains':chains,'services_enabled':args.enable_services,'stake_required':False,'invitation_required':False}))

if __name__=='__main__':main()

#!/usr/bin/env python3
"""Create both independent mainnet nodes, verify history, then optionally mine."""
import argparse,hashlib,json,os,pwd,re,shlex,shutil,sqlite3,subprocess,sys,tempfile,time,urllib.request,zipfile
from pathlib import Path

URL='https://app.ziokt.com/mainnet/bootstrap.zip'

def create_genesis(etc):
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key=ec.generate_private_key(ec.SECP256K1())
    public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
    identity=hashlib.sha256(public.encode()).hexdigest()
    payload=json.dumps([{'owner_id':identity,'domains':['corium']}],separators=(',',':'))
    write(etc/'identity.key',key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode())
    write(etc/'identity.key.pub',public+'\n')
    write(etc/'genesis.json',{'timestamp':int(time.time()),'genesis_validators':[{'public_key':public,'stake':1000}],'nomen_genesis_commitment':{'reservations_payload':payload,'signature':key.sign(payload.encode(),ec.ECDSA(hashes.SHA256())).hex()}})

def export_network(root,bundle,chains,ports,host):
    """Export public bootstrap material. Identities and signing keys stay local."""
    manifest={'schema':'ziokt.chain-pair-bootstrap.v1','chains':{},'files':{}}
    with tempfile.TemporaryDirectory(prefix='ziokt-network-export-') as temporary:
        stage=Path(temporary)
        for folder in ('native','runtime','tools'):shutil.copytree(bundle/folder,stage/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for role,item in chains.items():
            state=Path(item['root']);network=item['network_id'];etc=state/'etc/corix/networks'/network
            public=stage/role;public.mkdir()
            shutil.copyfile(etc/'genesis.json',public/'genesis.json');shutil.copyfile(etc/'tls.crt',public/'seed-local.crt')
            ledger=state/'var/lib/corix/networks'/network/'blockchain/chain.db'
            with sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(public/'chain.db') as target:
                source.backup(target)
                tip=source.execute('SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
            manifest['chains'][role]={'network':network,'port':ports[role],'snapshot':list(tip),'seeds':[{'host':host,'port':ports[role],'identity':item['identity'],'certificate':role+'/seed-local.crt'}]}
        for source in stage.rglob('*'):
            if source.is_file():manifest['files'][str(source.relative_to(stage))]=hashlib.sha256(source.read_bytes()).hexdigest()
        write(stage/'manifest.json',manifest)
        output=root/'network-bootstrap.zip'
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for source in stage.rglob('*'):
                if source.is_file():archive.write(source,str(source.relative_to(stage)))
        digest=hashlib.sha256(output.read_bytes()).hexdigest()
        write(root/'network-bootstrap.zip.sha256',digest+'  '+output.name+'\n')
    return {'path':str(output),'sha256':digest}

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    path.write_text(json.dumps(value,indent=2)+'\n' if not isinstance(value,str) else value);path.chmod(0o600)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--business-chain',choices=['primary','dna'],default='primary')
    parser.add_argument('--bootstrap-url',default=URL);parser.add_argument('--bootstrap-file',type=Path)
    parser.add_argument('--sha256');parser.add_argument('--enable-services',action='store_true')
    parser.add_argument('--create',metavar='NETWORK',help='Create a sovereign pair using this public runtime bundle')
    parser.add_argument('--custom-network',action='store_true',help='Join the explicitly checksum-pinned network in the supplied bundle')
    parser.add_argument('--expected-network')
    parser.add_argument('--dna-network');parser.add_argument('--advertise-host',default='127.0.0.1')
    parser.add_argument('--p2p-port',type=int);parser.add_argument('--dna-p2p-port',type=int)
    parser.add_argument('--service-prefix',default='ziokt')
    args=parser.parse_args();root=args.root.resolve()
    if args.custom_network and not args.sha256:raise ValueError('a custom network requires its independently obtained bootstrap SHA-256')
    if args.create and (not re.fullmatch('[A-Za-z0-9_-]{1,59}',args.create) or args.create in {'ziokt-main','mainnet','ziokt-dna-side-20261024'}):raise ValueError('choose a distinct sovereign network name')
    if not re.fullmatch('[A-Za-z0-9_-]{1,80}',args.service_prefix) or not re.fullmatch('[A-Za-z0-9.-]+',args.advertise_host):raise ValueError('safe service prefix and advertised host required')
    if args.enable_services and not sys_platform_linux():raise ValueError('run native chain services on Linux or inside WSL2/a Linux VM')
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
        if manifest['schema'] not in {'ziokt.mainnet-bootstrap.v1','ziokt.chain-pair-bootstrap.v1'} or set(manifest['chains'])!={'primary','dna'}:raise ValueError('complete chain pair required')
        if not args.create and args.expected_network and manifest['chains']['primary']['network']!=args.expected_network:raise ValueError('bootstrap is for another network')
        for relative,expected in manifest['files'].items():
            if Path(relative).is_absolute() or '..' in Path(relative).parts or hashlib.sha256((bundle/relative).read_bytes()).hexdigest()!=expected:raise ValueError('bootstrap file digest differs')
        source=bundle/'native/corix_v108.sh';source.chmod(0o700)
        providers=[];units=[];chains={};ports={}
        for role in ('primary','dna'):
            item=manifest['chains'][role];network=item['network'];port=item['port']
            if not args.create and not args.custom_network and network!=('ziokt-main' if role=='primary' else 'ziokt-dna-side-20261024'):raise ValueError('use --custom-network with a pinned bundle for another network')
            if args.create:network=args.create if role=='primary' else (args.dna_network or args.create+'-dna')
            if not re.fullmatch('[A-Za-z0-9_-]{1,64}',network):raise ValueError('safe network name required')
            port=(args.p2p_port if role=='primary' else args.dna_p2p_port) or port
            if type(port)is not int or not 1024<=port<=61000:raise ValueError('bounded chain listening port required')
            ports[role]=port
            state=root/role;etc=state/'etc/corix/networks'/network;etc.mkdir(parents=True,mode=0o700)
            for name in ('genesis.json','recovery.json','recovery-state.json'):
                path=bundle/role/name
                if not args.create and path.exists():shutil.copyfile(path,etc/name);(etc/name).chmod(0o600)
            if args.create:create_genesis(etc)
            conf=etc/'corix.conf'
            write(conf,f'[main]\ndep_mode = manual\nbuild_jobs = 1\nenable_fuzzy_finder = false\n[network]\nid = {network}\n[p2p]\nport = {port}\npublic_address_mode = auto\nenable_upnp = false\nauto_trust_new_nodes = false\ntls_ech_enabled = false\ntls_no_sni_client = true\n[gateway]\nport = {port+3000}\n[blockchain]\nconsensus = pos\n[ziokt]\nenabled = TRUE\nfederation_id = ziokt-mainnet\nprovider_id = {role}-node\n')
            env=dict(os.environ,CORIUM_ROOT=str(state),CORIUM_NETWORK_ID_OVERRIDE=network,CORIUM_TEST_NO_DAEMONS='1')
            env.pop('CORIUM_CONSENSUS_HOLD_FILE',None)
            subprocess.run(['bash',str(source),'init','--state-only'],env=env,check=True,timeout=180)
            for seed in ([] if args.create else item['seeds']):
                host,seedport,identity=seed['host'],seed['port'],seed['identity']
                if not re.fullmatch('[a-zA-Z0-9.-]+',host) or not re.fullmatch('[a-f0-9]{64}',identity) or type(seedport)is not int or not 1<=seedport<=65535:raise ValueError('bounded seed route')
                cache=state/'var/lib/corix/p2p/peer_certs';cache.mkdir(parents=True,exist_ok=True,mode=0o700)
                shutil.copyfile(bundle/seed['certificate'],cache/(host+'_'+str(seedport)+'.pem'))
                subprocess.run(['bash','-c','source "$1"; dht_add_node "$2" tcp "$3" "$4"','ziokt-seed',str(source),identity,host,str(seedport)],env=env,check=True,timeout=30)
            ledger=bundle/role/'chain.db'
            if not args.create:subprocess.run(['python3',str(bundle/'tools/sync_native_snapshot.py'),'--source',str(source),'--root',str(state),'--network',network,'--snapshot',str(ledger),'--sha256',manifest['files'][role+'/chain.db'],'--apply'],env=env,check=True)
            key=(etc/'identity.key.pub').read_text().rstrip('\n');identity=hashlib.sha256(key.encode()).hexdigest()
            chains[role]={'root':str(state),'network_id':network,'identity':identity}
            providers.append({'native_project':'corium','provider_id':role+'-node','root':str(source.parent),'native_config':str(conf),'entrypoint_digest':'sha256:'+hashlib.sha256(source.read_bytes()).hexdigest(),'network_id':network,'state_root':str(state)})
            write(state/'allow_empty_blocks','')
            for action in ('p2p','consensus'):
                runner=root/(role+'-'+action+'.sh')
                script='#!/bin/bash\numask 077\nexport CORIUM_ROOT='+shlex.quote(str(state))+' CORIUM_NETWORK_ID_OVERRIDE='+shlex.quote(network)+' CORIUM_GATEWAY_PORT='+str(port+3000)+'\nexport PYTHON_CMD='+shlex.quote(sys.executable)+' PATH='+shlex.quote(str(Path(sys.executable).parent)+os.pathsep+os.environ.get('PATH',os.defpath))+'\nsource '+shlex.quote(str(source))+'\nload_config || exit\n'+('dht_server_daemon; wait' if action=='p2p' else 'export CORIUM_MINER_POLL_SECONDS=${CORIUM_MINER_POLL_SECONDS:-'+('300' if role=='primary' else '180')+'}; _consensus_daemon_loop')+'\n'
                write(runner,script);runner.chmod(0o700)
                name=args.service_prefix+'-'+role+'-'+action+'.service'
                unit='[Unit]\nDescription=Ziokt '+role+' '+action+'\nAfter=network-online.target\n[Service]\nType=simple\nExecStart='+shlex.quote(str(runner))+'\nRestart=always\nRestartSec=5\nTimeoutStopSec=30\nKillMode=control-group\nUMask=0077\n[Install]\nWantedBy='+('multi-user.target' if os.geteuid()==0 else 'default.target')+'\n'
                write(root/name,unit);units.append((name,root/name))
        write(root/'federation.json',{'schema':'ziokt.federation.v1','enabled':True,'federation_id':'ziokt-mainnet','providers':providers})
        write(root/'chain-pair.json',{'schema':'ziokt.chain-pair.v1','business_chain':args.business_chain,'chains':chains,'bootstrap_sha256':digest})
        for role,item in chains.items():
            consumer=root/(role+'-consumer')
            command=[sys.executable,str(bundle/'runtime/tools/deploy_dna_consumer.py'),'--root',str(consumer),'--federation',str(root/'federation.json'),'--chain-database',str(Path(item['root'])/'var/lib/corix/networks'/item['network_id']/'blockchain/chain.db'),'--chain-role',role,'--network-id',item['network_id'],'--provider-id',role+'-node','--port',str(ports[role]+4000)]
            subprocess.run(command,check=True)
            original='ziokt-'+role+'-consumer.service';name=args.service_prefix+'-'+role+'-consumer.service';units.append((name,consumer/original))
        refresh=['/usr/bin/python3',str(bundle/'tools/refresh_peer_addresses.py'),'--source',str(source)]
        for role,item in chains.items():refresh.extend(['--chain',item['root'],item['network_id']])
        address_unit='[Unit]\nDescription=Refresh mainnet peer addresses\nAfter=network-online.target\n[Service]\nType=oneshot\nUMask=0077\nExecStart='+shlex.join(refresh).replace('%','%%')+'\n'
        write(root/'ziokt-peer-addresses.service',address_unit)
        write(root/'ziokt-peer-addresses.timer','[Unit]\nDescription=Track mainnet public address changes\n[Timer]\nOnBootSec=30s\nOnUnitInactiveSec=60s\n[Install]\nWantedBy=timers.target\n')
        units.extend((args.service_prefix+name[len('ziokt'):],root/name) for name in ('ziokt-peer-addresses.service','ziokt-peer-addresses.timer'))
        if len({i['network_id'] for i in chains.values()})!=2 or len({p+offset for p in ports.values() for offset in (0,1000,2000,3000,4000)})!=10:raise ValueError('chain networks and listener ports must be independent')
        exported=export_network(root,bundle,chains,ports,args.advertise_host) if args.create else None
        write(root/'IBC.json',{'schema':'ziokt.ibc-connections.v1','home_networks':[c['network_id'] for c in chains.values()],'recommended_peers':['ziokt-main','ziokt-dna-side-20261024'],'trust':'Register each foreign checkpoint verifier through native governance before relaying; the bundle grants no foreign-chain authority.'})

        if args.enable_services:
            directory=Path('/etc/systemd/system') if os.geteuid()==0 else Path.home()/'.config/systemd/user';directory.mkdir(parents=True,exist_ok=True)
            systemctl=['systemctl']+([] if os.geteuid()==0 else ['--user'])
            for name,path in units:
                if (directory/name).exists():raise ValueError('existing service retained: '+name+'; select --service-prefix')
            for name,path in units:shutil.copyfile(path,directory/name)
            subprocess.run(systemctl+['daemon-reload'],check=True)
            subprocess.run(systemctl+['enable','--now',*[name for name,_ in units]],check=True)
        write(root/'managed-services.json',{'schema':'ziokt.managed-services.v1','scope':'system' if os.geteuid()==0 else 'user','services':{name:str(directory/name) if args.enable_services else str(path) for name,path in units},'enabled':args.enable_services})
        print(json.dumps({'schema':'ziokt.mainnet-joined.v1','root':str(root),'business_chain':args.business_chain,'chains':chains,'services_enabled':args.enable_services,'mode':'created' if args.create else 'joined','export':exported}))

def sys_platform_linux():
    import sys
    return sys.platform.startswith('linux')

if __name__=='__main__':main()

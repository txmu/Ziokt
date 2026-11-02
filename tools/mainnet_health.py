#!/usr/bin/env python3
"""Read-only three-node chain health snapshot for a scheduled production probe."""
import argparse,json,os,subprocess,tempfile,time,urllib.request
from pathlib import Path


def run(command, input_bytes=None):
    value=subprocess.run(command,input=input_bytes,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
    if value.returncode:raise RuntimeError('probe exited '+str(value.returncode))
    return value.stdout


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--rainyun-password-file',type=Path,required=True)
    parser.add_argument('--upcloud-ssh-key',type=Path,required=True)
    args=parser.parse_args();inventory=args.inventory.read_bytes()
    common=['-o','BatchMode=yes','-o','ConnectTimeout=8','-o','StrictHostKeyChecking=yes']
    commands={
        'a':['python3',str(args.inventory),'/home/admin/.local/share/ziokt-production'],
        'b':['sshpass','-f',str(args.rainyun_password_file),'ssh','-o','ConnectTimeout=8','-o','StrictHostKeyChecking=yes','root@38.175.194.110','python3 - /opt/ziokt-main-validator'],
        'c':['ssh','-i',str(args.upcloud_ssh_key),*common,'root@94.237.57.186','python3 - /opt/ziokt-main-validator joined']}
    report={'schema':'ziokt.mainnet-health.v1','observed_at':int(time.time()),'nodes':{},'chains':{},'observer_coverage':None,'healthy':False}
    for name,command in commands.items():
        try:
            data=json.loads(run(command,None if name=='a' else inventory))
            report['nodes'][name]={'host':data['host'],'chains':{role:{'identity':chain['identity'],'tip':chain['tip'],'recent_blocks':{str(block[0]):block[1] for block in chain['recent_blocks']}} for role,chain in data['chains'].items()}}
        except (OSError,ValueError,KeyError,subprocess.TimeoutExpired,RuntimeError) as error:
            report['nodes'][name]={'error':type(error).__name__+': '+str(error)}
    for role in ('primary','dna'):
        values=[node.get('chains',{}).get(role) for node in report['nodes'].values()]
        if any(value is None for value in values):
            report['chains'][role]={'state':'unavailable'};continue
        heights=set.intersection(*(set(value['recent_blocks']) for value in values))
        matches=[int(height) for height in heights if len({value['recent_blocks'][height] for value in values})==1]
        conflicts=[int(height) for height in heights if len({value['recent_blocks'][height] for value in values})!=1]
        report['chains'][role]={'state':'fork' if conflicts else 'same_recent_branch' if matches else 'no_common_recent_height','latest_common_height':max(matches) if matches else None,'conflicting_heights':sorted(conflicts,reverse=True)[:5],'tip_heights':[value['tip'][0] for value in values]}
    try:
        with urllib.request.urlopen('https://p2p.ziokt.com/api/p2p/topology',timeout=10) as response:report['observer_coverage']=json.load(response)['coverage']
    except (OSError,ValueError,KeyError) as error:report['observer_coverage']={'error':type(error).__name__}
    report['healthy']=all(value['state']=='same_recent_branch' for value in report['chains'].values()) and report['observer_coverage'].get('verified_observers',0)==3
    args.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.NamedTemporaryFile('w',dir=args.output.parent,prefix='.health-',delete=False) as stream:
        os.fchmod(stream.fileno(),0o600);json.dump(report,stream,separators=(',',':'));stream.write('\n');stream.flush();os.fsync(stream.fileno());name=stream.name
    os.replace(name,args.output)
    print(json.dumps({'healthy':report['healthy'],'chains':report['chains'],'observer_coverage':report['observer_coverage']}))


if __name__=='__main__':main()

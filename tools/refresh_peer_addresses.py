#!/usr/bin/env python3
"""Refresh public observations and announce authenticated source routes on both chains."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import shlex
import pwd
import signal

SCRIPT=r'''
source "$1" || exit
get_our_ip || exit
claim=$(printf '{"port":%s,"timestamp":%s}' "$P2P_PORT" "$(date +%s)")
mapfile -t peers < <(db_query_static "$DHT_DB" 'SELECT id FROM nodes ORDER BY last_seen DESC LIMIT 8;')
failed=0
for peer in "${peers[@]}"; do
    [[ "$peer" =~ ^[a-f0-9]{64}$ ]] || continue
    _dht_send_message_direct "$peer" ANNOUNCE_ADDRESS "$claim" || failed=1
done
exit "$failed"
'''

def refresh(source, root, network):
    env=dict(os.environ,CORIUM_ROOT=str(root),CORIUM_NETWORK_ID_OVERRIDE=network)
    process=subprocess.Popen(['bash','-c',SCRIPT,'ziokt-address-refresh',str(source)],env=env,
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:out,err=process.communicate(timeout=100)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGKILL);out,err=process.communicate()
    result=subprocess.CompletedProcess(process.args,process.returncode,out,err)
    return {'network':network,'ok':result.returncode==0,'result':result.stdout[-4096:],
            'error':result.stderr[-1024:] if result.returncode else ''}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--chain',nargs=2,action='append',metavar=('ROOT','NETWORK'),required=True)
    parser.add_argument('--install-systemd',action='store_true')
    args=parser.parse_args()
    if args.install_systemd:
        if os.geteuid()!=0:raise SystemExit('system unit installation requires root')
        command=['/usr/bin/python3',str(Path(__file__).resolve()),'--source',str(args.source.resolve())]
        for root,network in args.chain:command.extend(['--chain',str(Path(root).resolve()),network])
        # systemd expands percent specifiers even inside quoted argv.
        execute=shlex.join(command).replace('%','%%')
        service_user=pwd.getpwuid(args.source.stat().st_uid).pw_name
        Path('/etc/systemd/system/ziokt-peer-addresses.service').write_text(
            '[Unit]\nDescription=Refresh dual-chain public addresses and signed peer routes\nAfter=network-online.target\n'
            '[Service]\nType=oneshot\nTimeoutStartSec=220\nUMask=0077\nUser='+service_user+'\nExecStart='+execute+'\n')
        Path('/etc/systemd/system/ziokt-peer-addresses.timer').write_text(
            '[Unit]\nDescription=Track public address changes automatically\n[Timer]\nOnBootSec=30s\nOnUnitInactiveSec=60s\nPersistent=true\n[Install]\nWantedBy=timers.target\n')
        subprocess.run(['systemctl','daemon-reload'],check=True)
        subprocess.run(['systemctl','enable','--now','ziokt-peer-addresses.timer'],check=True)
    results=[refresh(args.source,Path(root),network) for root,network in args.chain]
    print(json.dumps({'schema':'ziokt.peer-address-refresh.v1','chains':results}))
    return int(any(not row['ok'] for row in results))

if __name__=='__main__':raise SystemExit(main())

#!/usr/bin/env python3
"""Sync and export multi-observer signed topology observations."""
import sys, os, time, subprocess
from pathlib import Path

# Add Ziokt path
sys.path.insert(0, '/home/admin/Ziokt')

from ziokt.topology_observations import ObservationStore
from ziokt.protocol import encoded

now = int(time.time())
obs_dir = Path('/home/admin/.local/share/ziokt-production/web-state/observations')
obs_dir.mkdir(parents=True, exist_ok=True)

# 1. Export Node A
key_path = Path('/home/admin/.local/share/ziokt-production/config/observer.key')
key_bytes = key_path.read_bytes()
store = ObservationStore(obs_dir / 'node-a-outgoing.db')

source = {'id': 'observer-node-a', 'component': 'corium', 'network_id': 'ziokt-main'}
from observer_live import build_snapshot
snapshot = build_snapshot('/home/admin/.local/share/ziokt-production', '/home/admin/.local/share/ziokt-production/corium', '/home/admin/.local/share/ziokt-production/bin/corix_v108.sh')

env = store.export(source, snapshot, key_bytes, '0'*64)
out_a = obs_dir / 'node-a.json'
tmp_a = out_a.with_name('node-a.json.tmp')
tmp_a.write_bytes(encoded(env))
tmp_a.replace(out_a)
print('Exported Node A, seq:', env['payload']['sequence'])

# 2. Sync Node B
try:
    cmd_b = ['scp', '-i', '/home/admin/.ssh/id_ed25519', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=5',
             'root@38.175.194.110:/opt/ziokt-main-validator/state/observations/node-b.json', str(obs_dir / 'node-b.json.tmp')]
    res_b = subprocess.run(cmd_b, capture_output=True, timeout=10)
    if res_b.returncode == 0:
        (obs_dir / 'node-b.json.tmp').replace(obs_dir / 'node-b.json')
        print('Synced Node B')
    else:
        print('Node B sync failed:', res_b.stderr.decode().strip())
except Exception as e:
    print('Node B sync error:', e)

# 3. Sync Node C
try:
    cmd_c = ['scp', '-i', '/home/admin/.ssh/ziokt_test3_ed25519', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=5',
             'root@94.237.57.186:/opt/ziokt-main-validator/state/observations/node-c.json', str(obs_dir / 'node-c.json.tmp')]
    res_c = subprocess.run(cmd_c, capture_output=True, timeout=10)
    if res_c.returncode == 0:
        (obs_dir / 'node-c.json.tmp').replace(obs_dir / 'node-c.json')
        print('Synced Node C')
    else:
        print('Node C sync failed:', res_c.stderr.decode().strip())
except Exception as e:
    print('Node C sync error:', e)

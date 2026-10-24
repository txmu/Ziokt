#!/usr/bin/env python3
"""Sign public node evidence without private paths or consensus mutations."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.chain_observation import create
from ziokt.protocol import secure_read,strict_json
p=argparse.ArgumentParser();p.add_argument('--gateway-config',type=Path,required=True);p.add_argument('--key',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
if a.output.exists() or a.output.is_symlink():raise ValueError('new public observation path required')
value=create(strict_json(secure_read(a.gateway_config)),a.key)
with a.output.open('x') as output:output.write(json.dumps(value,indent=2)+'\n')
a.output.chmod(0o644)
print(json.dumps({'observation':str(a.output),'network':value['payload']['network'],'checkpoints':[b['height'] for b in value['payload']['checkpoints']],'consensus_changed':False}))

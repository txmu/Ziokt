#!/usr/bin/env python3
"""Compare independently authenticated remote checkpoints under an explicit trust policy.

Matching trusted sources is a trust assumption, not proof of historical validity.
This command does not install a checkpoint or modify a node database.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ziokt.checkpoint_store import CheckpointStore, MAX_TOTAL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', type=Path, required=True, help='JSON containing expected chain domains and trusted signer identities')
    parser.add_argument('--source', action='append', required=True, help='HTTPS checkpoint bundle URL; repeat for independent nodes')
    parser.add_argument('--quorum', type=int, default=2)
    args = parser.parse_args()
    if args.quorum < 2 or len(set(args.source)) < args.quorum:
        parser.error('at least quorum distinct HTTPS sources are required')
    policy = json.loads(args.policy.read_text())
    expected, signers = policy['expected'], {key: set(value) for key, value in policy['signers'].items()}
    if set(expected) != {'primary', 'dna'} or set(signers) != set(expected):
        raise ValueError('policy must pin both chain domains and trusted signer sets')
    os.umask(0o077)
    groups = {}
    with tempfile.TemporaryDirectory(prefix='ziokt-peer-checkpoints-') as tmp:
        for index, url in enumerate(args.source):
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('sources must be credential-free HTTPS URLs')
            destination = Path(tmp) / (str(index) + '.zip')
            with urllib.request.urlopen(url, timeout=30) as response, destination.open('xb') as out:
                if urllib.parse.urlsplit(response.geturl()).scheme != 'https':
                    raise ValueError('HTTPS downgrade rejected')
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_TOTAL + 2 * 1024 * 1024:
                        raise ValueError('checkpoint bundle too large')
                    out.write(chunk)
            store = CheckpointStore(Path(tmp) / ('store-' + str(index)), expected, signers)
            value = store.import_bundle(destination, allow_bootstrap=True)
            manifest = value.manifest
            if manifest['scope'] != 'explicit-signer-bootstrap':
                raise ValueError('remote source must publish an explicit bootstrap checkpoint')
            identities = tuple(manifest['signatures'][role]['identity'] for role in ('primary', 'dna'))
            groups.setdefault(manifest['pair_commitment'], []).append((identities, manifest))
        for commitment, entries in groups.items():
            chosen = []
            for identities, manifest in entries:
                if all(identities[0] != old[0][0] and identities[1] != old[0][1] for old in chosen):
                    chosen.append((identities, manifest))
            if len(chosen) >= args.quorum:
                chains = chosen[0][1]['chains']
                print(json.dumps({'pair_commitment': commitment, 'independent_signers': len(chosen), 'chains': {role: {key: chains[role][key] for key in ('network_id', 'height', 'block_hash', 'state_root')} for role in chains}, 'verification_level': 'explicitly trusted sources; historical validity not independently proven', 'installed': False}, indent=2))
                return
        raise ValueError('no matching checkpoint from the required number of distinct trusted signers')


if __name__ == '__main__':
    main()

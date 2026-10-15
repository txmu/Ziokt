"""Real native process -> Python adapter -> three forwarding hops -> Corium records.
No public endpoints, root privileges or local native compilation.
"""
import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path
import secrets
import socket
import shutil
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from ziokt.etp import EtpGateway, EtpRecordSocket
from ziokt.protocol import ProtocolError


def main(binary):
    binary = Path(binary).resolve()
    offline = subprocess.run([str(binary), '/nonexistent-airgap-config'],
        env={**os.environ, 'ZIOKT_AIRGAP': '1'}, capture_output=True, timeout=5)
    assert offline.returncode != 0 and b'AIRGAP_DENIED' in offline.stderr

    keys = [X25519PrivateKey.generate() for _ in range(4)]
    # Hold all port reservations until distinct addresses have been chosen.
    reservations = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in keys]
    for sock in reservations:
        sock.bind(('127.0.0.1', 0))
    addresses = [f'127.0.0.1:{sock.getsockname()[1]}' for sock in reservations]
    for sock in reservations:
        sock.close()
    public = [key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex() for key in keys]
    workers = []
    with tempfile.TemporaryDirectory() as temporary:
        # Cargo links its example artifact to a second filename. Use a private, single-link
        # executable, as required by the production adapter's file-integrity checks.
        installed = Path(temporary) / 'ziokt_gateway'
        shutil.copyfile(binary, installed)
        installed.chmod(0o700)
        binary = installed
        digest = 'sha256:' + hashlib.sha256(binary.read_bytes()).hexdigest()
        try:
            for i, key in enumerate(keys):
                config = Path(temporary) / f'node-{i}.json'
                config.write_text(json.dumps({'bind': addresses[i], 'private_key': key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()).hex(), 'peers': {address: public[j] for j, address in enumerate(addresses) if j != i}, 'relay': True}))
                config.chmod(0o600)
                worker = EtpGateway(binary, digest, config)
                workers.append(worker)
                assert worker.call('etp.stats', {})['schema'] == 'ziokt.etp-stats.v1'
            transport_key = secrets.token_bytes(32)
            client = EtpRecordSocket(workers[0], addresses[1:], transport_key, 'native-smoke')
            server = EtpRecordSocket(workers[3], list(reversed(addresses[:3])), transport_key, 'native-smoke', server=True)
            # Multiple records must remain distinct. End-to-end AEAD includes binary suffixes.
            for payload in (b'private Corium frame', bytes(range(256)) * 16):
                assert client.send(payload) == len(payload)
                assert server.recv(4096) == payload
            assert server.send(b'authenticated return') == 20
            assert client.recv(4096) == b'authenticated return'
            # Exercise the maximum native record and full UDP fragmentation/reassembly.
            payload = secrets.token_bytes(65536)
            packet = {'hops': addresses[1:], 'ciphertext': base64.b64encode(payload).decode()}
            assert workers[0].call('etp.onion.send', packet)['accepted']
            received = workers[3].call('etp.receive', {})['ciphertext']
            assert b''.join(base64.b64decode(chunk) for chunk in received) == payload
            # An invalid route cannot be acknowledged as successfully transmitted.
            try:
                workers[0].call('etp.onion.send', {**packet, 'hops': [addresses[1], '127.0.0.1:1']})
                raise AssertionError('unapproved route accepted')
            except ProtocolError:
                pass
            for worker in workers[1:]:
                assert worker.call('etp.shutdown', {})['stopped']
            print('ETP real native gateway: three-hop AEAD bidirectional records, 64 KiB fragmentation and route rejection passed')
        finally:
            for worker in workers:
                worker.close()

if __name__ == '__main__':
    main(sys.argv[1])

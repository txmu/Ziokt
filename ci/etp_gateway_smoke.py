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


def forum_smoke(binary, digest, root, required):
    """Real native Forum instances, including same-address restart, never a fixture."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    keys = [X25519PrivateKey.generate() for _ in range(2)]
    sockets = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in keys]
    for sock in sockets:sock.bind(('127.0.0.1', 0))
    addresses = [f'127.0.0.1:{sock.getsockname()[1]}' for sock in sockets]
    for sock in sockets:sock.close()
    public = [key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex() for key in keys]
    configs=[];workers=[]
    file_bytes=b'Native FileShare Library source\n'*2400
    file_source=root/'native-library.txt';file_source.write_bytes(file_bytes);file_source.chmod(0o600)
    from ziokt.application_router import ApplicationRouter
    class RoutedNativeForum:
        def __init__(self, path):self.router=ApplicationRouter(path)
        def call(self, method, params):return self.router.call('etp',method,params)
        def close(self):self.router.close()
    def await_post(worker, identifier):
        # Native periodic anti-entropy is 60 seconds. A lost initial restart
        # offer must be allowed one genuine retry cycle, not synthetic success.
        deadline=time.monotonic()+75
        while time.monotonic()<deadline:
            value=worker.call('etp.forum.get',{'id':identifier})['post']
            if value is not None:return value
            time.sleep(.05)
        raise AssertionError('real Forum peer did not converge within native anti-entropy cycle: '+identifier)
    try:
        for index,key in enumerate(keys):
            config=root/f'forum-node-{index}.json'
            config.write_text(json.dumps({'bind':addresses[index],'private_key':key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()).hex(),'peers':{addresses[1-index]:public[1-index]},'forum':{'database':str(root/f'forum-{index}.sled'),'identities':{'author':secrets.token_hex(32)},'subscriptions':['native-forum']},'fileshare':{'storage':str(root/f'fileshare-{index}'),'exports':{'library-source':str(file_source)} if index==0 else {}}}))
            config.chmod(0o600);configs.append(config)
            if index == 0:
                route=root/'forum-application-router.json'
                route.write_text(json.dumps({'schema':'ziokt.application-router.v1','components':{'etp':{'binary':str(binary),'digest':digest,'config':str(config),'methods':['etp.stats','etp.forum.identity','etp.forum.subscribe','etp.forum.publish','etp.forum.get','etp.forum.scan','etp.fileshare.list','etp.fileshare.manifest','etp.fileshare.chunk','etp.fileshare.request','etp.fileshare.status']}}}));route.chmod(0o600)
                worker=RoutedNativeForum(route)
            else:worker=EtpGateway(binary,digest,config)
            workers.append(worker)
            assert worker.call('etp.stats',{})['schema']=='ziokt.etp-stats.v1'
        if not required:
            for worker in workers:
                try:worker.call('etp.forum.identity',{'name':'author'})
                except ProtocolError as error:assert error.code=='METHOD_UNSUPPORTED'
                else:raise AssertionError('minimal binary advertised unsupported Forum')
            for worker in workers:
                try:worker.call('etp.fileshare.list',{})
                except ProtocolError as error:assert error.code=='METHOD_UNSUPPORTED'
                else:raise AssertionError('minimal binary advertised unsupported FileShare')
            assert not (root/'fileshare-0').exists()
            assert not (root/'forum-0.sled').exists()
            print('ETP minimal native gateway: Forum explicitly METHOD_UNSUPPORTED, no database created')
            return
        identity=workers[0].call('etp.forum.identity',{'name':'author'})
        assert set(identity)=={'schema','name','author_id'}
        content='native signed Forum '+'x'*32000
        publication=workers[0].call('etp.forum.publish',{'topic':'native-forum','content':content,'author':'author','parent_id':None})
        assert publication['stored'] and publication['state']=='stored_locally' and publication['delivery_confirmed'] is False and publication['dht_enqueued'] is False
        post=await_post(workers[1],publication['id'])
        body=b''.join(base64.b64decode(part,validate=True) for part in post['content_base64'])
        assert body.decode()==content and post['author_id']==identity['author_id']
        proof=base64.b64decode(post['signature_base64'],validate=True)
        canonical=(b'ETP/FORUM/POST/v2\0'+bytes.fromhex(post['topic_hash'])+post['timestamp'].to_bytes(8,'big',signed=True)+b'\1'+bytes.fromhex(post['author_id'])+b'\0'+len(body).to_bytes(8,'big')+body)
        Ed25519PublicKey.from_public_bytes(proof[:32]).verify(proof[32:],canonical)
        # A dynamically added subscription must survive a real process restart
        # with the same config (which intentionally does not list this topic).
        assert workers[1].call('etp.forum.subscribe',{'topic':'retained-subscription'})['subscribed']
        workers[1].close()
        queued=workers[0].call('etp.forum.publish',{'topic':'retained-subscription','content':'published while peer stopped','author':None,'parent_id':None})
        assert queued['stored'] and queued['delivery_confirmed'] is False
        restarted=EtpGateway(binary,digest,configs[1]);workers[1]=restarted
        assert restarted.call('etp.stats',{})['schema']=='ziokt.etp-stats.v1'
        assert await_post(restarted,publication['id'])['author_id']==identity['author_id']
        recovered=await_post(restarted,queued['id']);assert recovered['author_id'] is None and recovered['signature_base64']==''
        response=restarted.call('etp.forum.publish',{'topic':'native-forum','content':'native return','author':'author','parent_id':publication['id']})
        returned=await_post(workers[0],response['id']);assert returned['parent_status']=='available'
        for invalid in ({'topic':'native-forum','content':'missing explicit author'},{'topic':'native-forum','content':'forbidden seed','author':'author','private_key':'00'*32}):
            try:restarted.call('etp.forum.publish',invalid)
            except ProtocolError:pass
            else:raise AssertionError('invalid Forum publication accepted')
        from etp_fileshare_smoke import run as fileshare_run
        fileshare_run(workers,addresses,file_bytes)
        from etp_fileshare_smoke import library_run
        library_run(root,workers,addresses,file_bytes,await_post)
        from etp_content_bridge_smoke import run as bridge_run
        bridge_run(root,workers,await_post)
        print('ETP integrated native Forum: signed fragmented post, actual Ed25519 proof, persisted subscription, same-address restart and bidirectional reply passed')
    finally:
        for worker in workers:worker.close()

def main(binary, forum_required):
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
                health=worker.call('etp.health',{'challenge':secrets.token_hex(16)})
                assert health['checks']['native_engine_stats']=='passed'
                assert health['checks']=={'pinned_native_process_rpc':'passed','native_engine_stats':'passed'}
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
            # FileShare v2 uses the same real native three-hop transport; no
            # v1 manifest ceiling, and no download temporary file.
            import io,threading
            from ziokt.etp_bulk import BulkPeer,serve_objects
            from ziokt.gateway_store import Store
            source=Store(Path(temporary)/'bulk-source');data=secrets.token_bytes(2*1024*1024+19)
            object_hash=source.put(data)
            sender=EtpRecordSocket(workers[0],addresses[1:],transport_key,'bulk-smoke',max_record=60000)
            receiver=EtpRecordSocket(workers[3],list(reversed(addresses[:3])),transport_key,'bulk-smoke',server=True,max_record=60000)
            stop=threading.Event();thread=threading.Thread(target=serve_objects,args=(receiver,source,stop),daemon=True);thread.start()
            try:
                remote=Store(Path(temporary)/'bulk-download',fetchers=[BulkPeer(sender).fetch])
                assert remote.get(object_hash)==data
                assert list((Path(temporary)/'bulk-download').iterdir())==[]
            finally:stop.set();thread.join(timeout=12)
            print('ETP FileShare v2: actual three-hop 2 MiB verified object, segment window and zero download disk writes passed')
            for worker in workers[1:]:
                assert worker.call('etp.shutdown', {})['stopped']
            print('ETP real native gateway: three-hop AEAD bidirectional records, 64 KiB fragmentation and route rejection passed')
        finally:
            for worker in workers:
                worker.close()
        forum_smoke(binary, digest, Path(temporary), forum_required)

if __name__ == '__main__':
    assert len(sys.argv)==3 and sys.argv[2] in ('--forum-required','--forum-unavailable'), 'explicit native Forum feature expectation required'
    main(sys.argv[1],sys.argv[2]=='--forum-required')

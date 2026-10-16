"""Real externally routed onion service gate, mandatory in anonymous-carrier CI.

Temporary unprivileged Tor process; no system Tor, firewall or route changes.
"""
import os
from pathlib import Path
import queue
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import hashlib
import re
from collections import deque

from test_community_network import certificates
from ziokt.community import Community, RIGHTS, create_policy
from ziokt.community_network import CommunityEndpoint, sync_remote
from ziokt.protocol import ProtocolError
from ziokt.remote import remote_server, tls_context
from ziokt.security import sign
from cryptography.hazmat.primitives import serialization


def tor_health(root,control_port,lines):
    """Bounded local control query; never log cookies, onion names or relay paths."""
    summary={'bootstrap_progress':None,'warning_lines_in_tail':sum('[warn]' in line.lower() for line in lines)}
    for line in lines:
        match=re.search(r'Bootstrapped (\d+)%',line)
        if match:summary['bootstrap_progress']=int(match[1])
    try:
        with (root/'control.cookie').open('rb') as source:cookie=source.read(33)
        if len(cookie)!=32:raise ValueError('invalid local cookie')
        with socket.create_connection(('127.0.0.1',control_port),timeout=2) as connection:
            connection.settimeout(2)
            with connection.makefile('rwb') as stream:
                def command(text):
                    stream.write(text.encode('ascii')+b'\r\n');stream.flush();result=[];total=0;data_block=False
                    for _ in range(256):
                        line=stream.readline(8193);total+=len(line)
                        if not line or len(line)>8192 or total>32768:raise OSError('bounded control reply')
                        line=line.decode('ascii','replace').rstrip('\r\n');result.append(line)
                        if data_block:
                            if line=='.':data_block=False
                            continue
                        if len(line)>=4 and line[:3].isdigit() and line[3]=='+':data_block=True;continue
                        if len(line)>=4 and line[:3].isdigit() and line[3]==' ':
                            if not line.startswith('250 '):raise OSError('control command rejected')
                            return result
                    raise OSError('control reply limit')
                command('AUTHENTICATE '+cookie.hex())
                for field in ['status/circuit-established','network-liveness']:
                    try:
                        response=command('GETINFO '+field)
                        value=next((line.split('=',1)[1] for line in response if line.startswith('250-'+field+'=')),None)
                        summary[field]=value if value in {'0','1','up','down'} else 'unknown'
                    except OSError:summary[field]='unavailable'
                response=command('GETINFO circuit-status')
                counts={}
                for line in response:
                    match=re.match(r'\d+ (BUILT|LAUNCHED|EXTENDED|FAILED|CLOSED)(?: |$)',line)
                    if match:counts[match[1]]=counts.get(match[1],0)+1
                summary['circuit_states']=counts
    except (OSError,ValueError):summary['control_query']='unavailable'
    return summary


class TorLiveTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('ZIOKT_TOR_LIVE') == '1', 'real Tor network is a separate mandatory CI gate')
    def test_actual_onion_mutual_tls_and_community_cold_sync(self):
        self.assertIsNotNone(shutil.which('tor'), 'real Tor executable required')
        with tempfile.TemporaryDirectory(prefix='ziokt-onion-') as directory:
            root = Path(directory); hidden = root/'hidden'; hidden.mkdir(mode=0o700)
            intermediary = root/'intermediary'; intermediary.mkdir(mode=0o700)
            with socket.socket() as available:
                available.bind(('127.0.0.1', 0)); service_port = available.getsockname()[1]
            with socket.socket() as available:
                available.bind(('127.0.0.1', 0)); socks_port = available.getsockname()[1]
            with socket.socket() as available:
                available.bind(('127.0.0.1',0));control_port=available.getsockname()[1]
            torrc = root/'torrc'
            torrc.write_text('\n'.join((f'DataDirectory {root/"tor"}', f'SocksPort 127.0.0.1:{socks_port} IsolateSOCKSAuth ExtendedErrors',
                f'ControlPort 127.0.0.1:{control_port}', 'CookieAuthentication 1', f'CookieAuthFile {root/"control.cookie"}',
                f'HiddenServiceDir {hidden}', f'HiddenServicePort 443 127.0.0.1:{service_port}',
                f'HiddenServiceDir {intermediary}', f'HiddenServicePort 1080 127.0.0.1:{socks_port}', 'Log notice stdout', 'ClientOnly 0'))+'\n')
            process = subprocess.Popen(['tor', '-f', str(torrc)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            messages = queue.Queue(maxsize=256);tail=deque(maxlen=32)
            def read_logs():
                for line in process.stdout:
                    tail.append(line)
                    try:messages.put_nowait(line)
                    except queue.Full:
                        try:messages.get_nowait()
                        except queue.Empty:pass
                        try:messages.put_nowait(line)
                        except queue.Full:pass
            reader = threading.Thread(target=read_logs, daemon=True); reader.start()
            source = target = server = thread = None
            try:
                deadline = time.monotonic()+180
                bootstrapped = False
                while time.monotonic() < deadline:
                    if process.poll() is not None: self.fail('temporary Tor process exited before bootstrap')
                    try: line = messages.get(timeout=1)
                    except queue.Empty: continue
                    if 'Bootstrapped 100%' in line: bootstrapped = True; break
                if not bootstrapped:self.fail('actual Tor network did not bootstrap within 180 seconds; health='+str(tor_health(root,control_port,list(tail))))
                host = (hidden/'hostname').read_text().strip()
                private, key = secrets.token_bytes(32), secrets.token_bytes(32)
                public = sign({}, private, 'test')['public_key']
                policy = create_policy(private, 'village', {public: sorted(RIGHTS)})
                source = Community(root/'source', policy, public, key)
                target = Community(root/'target', policy, public, key)
                ca, pairs = certificates(root, host)
                trusted = {hashlib.sha256(pairs['client'][2].public_bytes(serialization.Encoding.DER)).hexdigest(): {
                    'public_key': public, 'methods': ['community.status', 'community.checkpoint.create', 'community.checkpoint.get', 'community.checkpoint.release', 'community.event.put', 'community.blob.put'], 'providers': ['village']}}
                server = remote_server({'enabled': True, 'federation_id': 'village', 'providers': []},
                    tls_context(*pairs['server'][:2], ca, server=True), root/'replay.sqlite', trusted,
                    port=service_port, allow_mutations=True, community=CommunityEndpoint(source, private))
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                source.publish(private, 'wiki', 'home', {'title': 'Onion wiki', 'text': 'real anonymous carrier'})
                manifest = source.put_file(b'encrypted community archive')
                source.publish(private, 'files', 'archive', {'name': 'archive', **manifest})
                endpoint = {'host': host, 'port': 443, 'carrier': {'kind': 'tor-socks5', 'proxy_host': '127.0.0.1', 'proxy_port': socks_port}}
                # Fresh service descriptor publication can need a short delay.
                success = False; last_error = None; attempts=0; deadline = time.monotonic()+180
                while time.monotonic() < deadline:
                    attempts+=1
                    try:
                        sync_remote(target, endpoint, tls_context(*pairs['client'][:2], ca), private, publisher=public)
                        success = True; break
                    except OSError as exc:
                        last_error=type(exc).__name__;print('real Tor attempt',attempts,'failed:',last_error,flush=True);time.sleep(2)
                    except ProtocolError as exc:
                        if exc.code != 'CARRIER_UNAVAILABLE': raise
                        last_error=exc.code+': '+str(exc)
                        print('real Tor attempt',attempts,'failed:',last_error,flush=True);time.sleep(2)
                if not success:self.fail(f'genuine onion endpoint did not complete mTLS sync; attempts={attempts}; last carrier error={last_error}; health={tor_health(root,control_port,list(tail))}')
                self.assertEqual(target.get_file(manifest), b'encrypted community archive')
                self.assertEqual(target.view('wiki'), source.view('wiki'))
                # Traverse another actual onion service exposing Tor SOCKS,
                # then verify the final community certificate end to end.
                intermediate_host = (intermediary/'hostname').read_text().strip()
                source.publish(private, 'wiki', 'multihop', {'title': 'Onion chain', 'text': 'real nested onion SOCKS and mTLS'})
                endpoint['carrier']['hops'] = [{'host': intermediate_host, 'port': 1080}]
                success = False; last_error = None; attempts=0; deadline = time.monotonic()+180
                while time.monotonic() < deadline:
                    attempts+=1
                    try:
                        sync_remote(target, endpoint, tls_context(*pairs['client'][:2], ca), private, publisher=public)
                        success = True; break
                    except OSError as exc:
                        last_error=type(exc).__name__;print('real Tor attempt',attempts,'failed:',last_error,flush=True);time.sleep(2)
                    except ProtocolError as exc:
                        if exc.code != 'CARRIER_UNAVAILABLE': raise
                        last_error=exc.code+': '+str(exc)
                        print('real Tor attempt',attempts,'failed:',last_error,flush=True);time.sleep(2)
                if not success:self.fail(f'actual intermediate onion SOCKS path did not complete mTLS sync; attempts={attempts}; last carrier error={last_error}; health={tor_health(root,control_port,list(tail))}')
                self.assertEqual(target.view('wiki'), source.view('wiki'))
            finally:
                if server: server.shutdown(); server.server_close()
                if thread: thread.join(5)
                if source: source.close()
                if target: target.close()
                process.terminate()
                try: process.wait(10)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
                reader.join(5); process.stdout.close()


if __name__ == '__main__': unittest.main()

"""Real TLS sockets, opaque range sync and a SOCKS5 proxy with no onion DNS."""
import datetime
import base64
from contextlib import contextmanager
import hashlib
import ipaddress
from pathlib import Path
import secrets
import socket
import socketserver
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from ziokt.carrier import connect_onion, onion_address
from ziokt.community import Community, RIGHTS, create_policy, content_id
from ziokt.community_network import CommunityEndpoint, sync_remote
from ziokt.community_privacy import seal_mail, open_mail, mailbox_public, invitation, accept_invitation
from ziokt.protocol import ProtocolError, make_private
from ziokt.remote import remote_server, tls_context
from ziokt.security import sign

ONION = 'pg6mmjiyjmcrsslvykfwnntlaru7p5svn6y2ymmju6nubxndf4pscryd.onion'


def test_onion(seed):
    public = hashlib.sha256(seed.encode()).digest()
    checksum = hashlib.sha3_256(b'.onion checksum'+public+b'\x03').digest()[:2]
    return base64.b32encode(public+checksum+b'\x03').decode().lower()+'.onion'


@contextmanager
def onion_proxy(destination, upstream_port, observed, *, reject=False):
    """A real forwarding SOCKS socket with exactly one approved next hop."""
    class Proxy(socketserver.BaseRequestHandler):
        def handle(self):
            stream = self.request
            stream.settimeout(5)
            upstream = None
            def read(size):
                data = bytearray()
                while len(data) < size:
                    part = stream.recv(size-len(data))
                    if not part: raise OSError('EOF')
                    data.extend(part)
                return bytes(data)
            try:
                if read(3) != b'\x05\x01\x02': raise OSError('method')
                if reject:
                    observed.append(('rejected', destination))
                    stream.sendall(b'\x05\x00')
                    return
                stream.sendall(b'\x05\x02')
                if read(1) != b'\x01': raise OSError('auth')
                username = read(read(1)[0]); password = read(read(1)[0])
                stream.sendall(b'\x01\x00')
                if read(4) != b'\x05\x01\x00\x03': raise OSError('remote DNS required')
                host = read(read(1)[0]).decode(); port = struct.unpack('!H', read(2))[0]
                if host != destination or port != 443: raise OSError('unapproved destination')
                observed.append((host, username, password))
                upstream = socket.create_connection(('127.0.0.1', upstream_port), timeout=5)
                stream.sendall(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00')
                def copy(a, b):
                    try:
                        while part := a.recv(16384): b.sendall(part)
                    except OSError: pass
                    try: b.shutdown(socket.SHUT_WR)
                    except OSError: pass
                worker = threading.Thread(target=copy, args=(stream, upstream), daemon=True)
                worker.start(); copy(upstream, stream); worker.join(5)
            except OSError: pass
            finally:
                if upstream is not None: upstream.close()
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
    proxy = Server(('127.0.0.1', 0), Proxy)
    thread = threading.Thread(target=proxy.serve_forever, daemon=True); thread.start()
    try: yield proxy.server_address[1]
    finally: proxy.shutdown(); proxy.server_close(); thread.join(5)


def certificates(root, host=ONION):
    now = datetime.datetime.now(datetime.timezone.utc)
    private = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Test CA '+root.name)])
    ca = x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(private.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=0), True).sign(private, hashes.SHA256())
    ca_path = root/'ca.pem'; ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    pairs = {}
    for name, usage in [('server', ExtendedKeyUsageOID.SERVER_AUTH), ('client', ExtendedKeyUsageOID.CLIENT_AUTH)]:
        key = ec.generate_private_key(ec.SECP256R1())
        try: target_name = x509.IPAddress(ipaddress.ip_address(host))
        except ValueError: target_name = x509.DNSName(host)
        cert = x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=False, path_length=None), True).add_extension(x509.ExtendedKeyUsage([usage]), False).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1')), target_name]), False).sign(private, hashes.SHA256())
        cp, kp = root/(name+'.pem'), root/(name+'.key')
        cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        kp.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())); make_private(kp)
        pairs[name] = (cp, kp, cert)
    return ca_path, pairs


class CommunityNetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name)
        self.private, self.key = secrets.token_bytes(32), secrets.token_bytes(32)
        self.public = sign({}, self.private, 'test')['public_key']
        self.policy = create_policy(self.private, 'village', {self.public: sorted(RIGHTS)}, privacy='private')
        self.source = Community(self.root/'source', self.policy, self.public, self.key); self.addCleanup(self.source.close)
        self.target = Community(self.root/'target', self.policy, self.public, self.key); self.addCleanup(self.target.close)
        ca, pairs = certificates(self.root)
        self.context = tls_context(*pairs['client'][:2], ca)
        trusted = {hashlib.sha256(pairs['client'][2].public_bytes(serialization.Encoding.DER)).hexdigest(): {
            'public_key': self.public, 'methods': ['community.status', 'community.checkpoint.create', 'community.checkpoint.get', 'community.checkpoint.release', 'community.event.put', 'community.blob.put'], 'providers': ['village']}}
        self.trusted = trusted
        self.backend = CommunityEndpoint(self.source, self.private)
        self.server = remote_server({'enabled': True, 'federation_id': 'village', 'providers': []},
            tls_context(*pairs['server'][:2], ca, server=True), self.root/'replay.sqlite', trusted,
            allow_mutations=True, community=self.backend)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.stop)
        manifest = self.source.put_file(b'real network content'*800)
        self.source.publish(self.private, 'files', 'archive', {'name': 'archive', **manifest})
        self.source.publish(self.private, 'wiki', 'home', {'title': 'Wiki', 'text': 'over real TLS'})
        self.manifest = manifest

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(5)

    def test_real_mutual_tls_range_sync(self):
        result = sync_remote(self.target, {'host': '127.0.0.1', 'port': self.server.server_port}, self.context, self.private, publisher=self.public)
        self.assertFalse(result['runtime_ready'])
        self.assertEqual(self.target.get_file(self.manifest), b'real network content'*800)
        self.assertEqual(self.source.view('wiki'), self.target.view('wiki'))
        self.assertEqual(len(list((self.source.root/'exchange').iterdir())), 0)
        repeated = sync_remote(self.target, {'host': '127.0.0.1', 'port': self.server.server_port}, self.context, self.private, publisher=self.public)
        self.assertTrue(repeated['unchanged'])
        self.assertEqual(len(list((self.source.root/'exchange').iterdir())), 0)

    def test_repeated_network_edits_use_deltas_and_release_export_leases(self):
        endpoint = {'host': '127.0.0.1', 'port': self.server.server_port}
        initial = sync_remote(self.target, endpoint, self.context, self.private, publisher=self.public)
        for index in range(6):
            self.source.publish(self.private, 'wiki', 'home', {'title': 'Wiki', 'text': 'revision '+str(index)})
            result = sync_remote(self.target, endpoint, self.context, self.private, publisher=self.public)
            self.assertEqual(result['records'], 1)
            self.assertEqual(result['objects'], 0)
            self.assertLess(result['download_bytes'], initial['download_bytes'])
            self.assertEqual(len(list((self.source.root/'exchange').iterdir())), 0)
        self.assertEqual(self.target.view('wiki'), self.source.view('wiki'))
        self.assertEqual(self.target.get_file(self.manifest), b'real network content'*800)

    def test_pinned_tls_peer_can_pause_beyond_unauthenticated_read_budget(self):
        import http.client,json,time
        from ziokt.protocol import encoded
        from ziokt.remote import padded_json,resource_for
        from ziokt.security import grant
        request={'provider_id':'village','method':'community.status','params':{}}
        token=grant(self.private,audience='village',action=request['method'],resource=resource_for(request['method'],{}),federation='village',request_digest=content_id(encoded(request)))
        body=padded_json({'request':request,'grant':token},65536)
        raw=socket.create_connection(('127.0.0.1',self.server.server_port),timeout=10)
        with self.context.wrap_socket(raw,server_hostname=ONION) as stream:
            header=('POST /zfcp HTTP/1.1\r\nHost: '+ONION+'\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body))+'\r\nConnection: close\r\n\r\n').encode()
            stream.sendall(header+body[:100]);time.sleep(5.2);stream.sendall(body[100:])
            response=http.client.HTTPResponse(stream);response.begin();value=json.loads(response.read());response.close()
            self.assertTrue(value['ok']);self.assertIn('padding',value)

    def test_padded_timeout_keeps_typed_retryable_error(self):
        import ziokt.remote as remote
        from ziokt.protocol import encoded
        from ziokt.security import grant
        original=remote.strict_json
        def timeout_on_request(data,*args,**kwargs):
            if b'"grant":' in data:raise TimeoutError('simulated slow carrier')
            return original(data,*args,**kwargs)
        request={'provider_id':'village','method':'community.status','params':{}}
        token=lambda:grant(self.private,audience='village',action=request['method'],resource=remote.resource_for(request['method'],{}),federation='village',request_digest=content_id(encoded(request)))
        with patch('ziokt.remote.strict_json',side_effect=timeout_on_request):
            with self.assertRaises(ProtocolError) as error:remote.request_remote('127.0.0.1',self.server.server_port,self.context,request,token,privacy_padding=True)
        self.assertEqual(error.exception.code,'CARRIER_UNAVAILABLE')

    def test_member_submits_own_files_and_posts_without_archive_authority(self):
        from ziokt.community_network import push_remote, SyncWorker
        writer = secrets.token_bytes(32); writer_public = sign({}, writer, 'test')['public_key']
        policy = create_policy(self.private, 'village', {self.public: sorted(RIGHTS), writer_public: ['forum', 'wiki', 'files', 'replicate', 'identity']}, epoch=1, privacy='private')
        self.source.close(); self.target.close()
        self.source = Community(self.root/'source', policy, self.public, self.key); self.addCleanup(self.source.close)
        self.target = Community(self.root/'target', policy, self.public, self.key); self.addCleanup(self.target.close)
        self.backend.community = self.source
        for principal in self.trusted.values(): principal['public_key'] = writer_public
        endpoint = {'host': '127.0.0.1', 'port': self.server.server_port}
        self.target.publish(writer, 'forum', 'member-post', {'title': 'Member post', 'text': 'network submission', 'reply_to': ''})
        materials = self.target.put_file(b'member-owned file')
        self.target.publish(writer, 'files', 'member-file', {'name': 'member-file', **materials})
        with self.assertRaises(ProtocolError): self.target.checkpoint(writer)
        worker = SyncWorker(self.target, writer, [{'endpoint': endpoint, 'context': self.context, 'publisher': self.public}])
        result = worker.cycle()
        self.assertTrue(result[0]['healthy'], result)
        self.assertEqual(self.source.get_file(materials), b'member-owned file')
        self.assertEqual(self.source.view('forum')['events'][0]['author'], writer_public)
        self.assertEqual(push_remote(self.target, endpoint, self.context, writer)['submitted'], 0)

    def test_socks5_actual_stream_remote_dns_and_isolation(self):
        observed = []
        upstream_port = self.server.server_port
        class Proxy(socketserver.BaseRequestHandler):
            def handle(proxy):
                stream = proxy.request; stream.settimeout(5)
                def read(n):
                    result = b''
                    while len(result) < n:
                        part = stream.recv(n-len(result))
                        if not part: raise OSError('EOF')
                        result += part
                    return result
                if read(3) != b'\x05\x01\x02': raise OSError('method')
                stream.sendall(b'\x05\x02')
                if read(1) != b'\x01': raise OSError('auth')
                user = read(read(1)[0]); password = read(read(1)[0]); observed.append((user, password))
                stream.sendall(b'\x01\x00')
                if read(4) != b'\x05\x01\x00\x03': raise OSError('remote DNS')
                host = read(read(1)[0]).decode(); port = struct.unpack('!H', read(2))[0]
                observed.append((host, port))
                upstream = socket.create_connection(('127.0.0.1', upstream_port), timeout=5)
                stream.sendall(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00')
                def copy(a, b):
                    try:
                        while part := a.recv(16384): b.sendall(part)
                    except OSError: pass
                    try: b.shutdown(socket.SHUT_WR)
                    except OSError: pass
                worker = threading.Thread(target=copy, args=(stream, upstream)); worker.start()
                copy(upstream, stream); worker.join(5); upstream.close()
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True
        proxy = Server(('127.0.0.1', 0), Proxy)
        thread = threading.Thread(target=proxy.serve_forever, daemon=True); thread.start()
        try:
            endpoint = {'host': ONION, 'port': 443, 'carrier': {'kind': 'tor-socks5', 'proxy_host': '127.0.0.1', 'proxy_port': proxy.server_address[1]}}
            original = socket.getaddrinfo
            def dns(host, *args, **kwargs):
                self.assertNotIn('.onion', str(host)); return original(host, *args, **kwargs)
            with patch('socket.getaddrinfo', side_effect=dns):
                sync_remote(self.target, endpoint, self.context, self.private, publisher=self.public)
            self.assertEqual(self.target.get_file(self.manifest), b'real network content'*800)
            auth = [item for item in observed if item[0] == b'<torS0X>0']
            self.assertGreater(len(auth), 1); self.assertEqual(len({item[1] for item in auth}), len(auth))
            self.assertTrue(all(item == (ONION, 443) for item in observed if isinstance(item[0], str)))
        finally:
            proxy.shutdown(); proxy.server_close(); thread.join(5)

    def test_onion_checksum_invalid_proxy_and_no_direct_fallback(self):
        self.assertEqual(onion_address(ONION), ONION)
        for host in ['example.com', 'a'*56+'.onion', ONION.upper()]:
            with self.assertRaises(ProtocolError): onion_address(host)
        with self.assertRaises(ProtocolError): connect_onion(ONION, 443, {'kind': 'tor-socks5', 'proxy_host': '8.8.8.8', 'proxy_port': 9050})
        restricted = create_policy(self.private, 'village', {self.public: sorted(RIGHTS)}, epoch=1)
        self.target.close(); self.target.close = lambda: None
        with Community(self.root/'target', restricted, self.public, self.key) as target:
            with self.assertRaises(ProtocolError): sync_remote(target, {'host': '127.0.0.1', 'port': self.server.server_port}, self.context, self.private, publisher=self.public)
            target.publish(self.private, 'wiki', 'offline', {'title': 'Offline', 'text': 'still available'})
            self.assertEqual(len(target.view('wiki')['events']), 1)

    def test_multihop_selected_candidate_uses_real_tls_without_local_onion_dns(self):
        first, second = test_onion('first'), test_onion('second')
        observed = []
        with onion_proxy(ONION, self.server.server_port, observed) as final_proxy:
            with onion_proxy(second, final_proxy, observed) as middle_proxy:
                with onion_proxy(first, middle_proxy, observed) as entry_proxy:
                    observations = {'end_to_end_authentication': True, 'encrypted_content': True,
                                    'private_discovery': True, 'anonymous_carrier': True, 'direct_fallback': False}
                    selected = {'approved': True, 'observed': observations, 'host': ONION, 'port': 443,
                                'carrier': {'kind': 'tor-socks5', 'proxy_host': '127.0.0.1', 'proxy_port': entry_proxy,
                                            'hops': [{'host': first, 'port': 443}, {'host': second, 'port': 443}]}}
                    endpoint = {'host': 'unselected.example', 'port': 1,
                                'connection_policy': {'mode': 'approved-paths', 'allow_direct_fallback': False},
                                'candidates': [selected]}
                    original_dns = socket.getaddrinfo
                    def dns(host, *args, **kwargs):
                        self.assertEqual(host, '127.0.0.1')
                        return original_dns(host, *args, **kwargs)
                    with patch('socket.getaddrinfo', side_effect=dns):
                        sync_remote(self.target, endpoint, self.context, self.private, publisher=self.public)
                    self.assertEqual(self.target.get_file(self.manifest), b'real network content'*800)
        self.assertGreater(len(observed), 3)
        self.assertEqual({item[0] for item in observed}, {first, second, ONION})
        self.assertEqual(len({item[2] for item in observed}), len(observed))

    def test_multihop_authentication_downgrade_stops_before_final_peer(self):
        intermediate = test_onion('rejecting-hop'); observed = []
        with onion_proxy(ONION, self.server.server_port, observed, reject=True) as middle:
            with onion_proxy(intermediate, middle, observed) as entry:
                carrier = {'kind': 'tor-socks5', 'proxy_host': '127.0.0.1', 'proxy_port': entry,
                           'hops': [{'host': intermediate, 'port': 443}]}
                with self.assertRaises(ProtocolError) as error:
                    connect_onion(ONION, 443, carrier, timeout=5)
                self.assertEqual(error.exception.code, 'CARRIER_UNAVAILABLE')
        self.assertEqual(len(observed), 2)
        self.assertEqual(observed[-1], ('rejected', ONION))

    def test_multihop_invalid_or_repeated_hops_are_rejected_before_network(self):
        from ziokt.routes import resolve_endpoint
        carrier = {'kind': 'tor-socks5', 'proxy_host': '127.0.0.1', 'proxy_port': 9050}
        for hops in [[{'host': ONION, 'port': 443}], [{'host': 'example.com', 'port': 443}],
                     [{'host': test_onion('same'), 'port': 443}]*2,
                     [{'host': test_onion(str(i)), 'port': 443} for i in range(4)],
                     [{'host': test_onion('valid'), 'port': True}]]:
            with patch('socket.create_connection') as dial:
                with self.assertRaises(ProtocolError): connect_onion(ONION, 443, {**carrier, 'hops': hops})
                dial.assert_not_called()
        claimed = {'approved': True, 'host': '127.0.0.1', 'port': 443,
                   'observed': {'end_to_end_authentication': True, 'encrypted_content': True,
                                'private_discovery': True, 'anonymous_carrier': True, 'direct_fallback': False}}
        endpoint = {'connection_policy': {'mode': 'approved-paths', 'allow_direct_fallback': False}, 'candidates': [claimed]}
        with self.assertRaises(ProtocolError): resolve_endpoint('restricted', endpoint)

    def test_browser_sync_action_uses_the_fixed_real_tls_peer(self):
        import http.client
        import json
        from ziokt.community_ui import portal_server
        portal, token = portal_server(self.target, self.private,
            peer={'host': '127.0.0.1', 'port': self.server.server_port}, peer_context=self.context, publisher=self.public)
        worker = threading.Thread(target=portal.serve_forever, daemon=True); worker.start()
        connection = http.client.HTTPConnection('127.0.0.1', portal.server_port, timeout=10)
        try:
            connection.request('POST', '/api/sync', '{}', {'Authorization': 'Bearer '+token, 'Content-Type': 'application/json'})
            response = connection.getresponse()
            self.assertEqual(response.status, 200, response.read())
            self.assertEqual(self.target.get_file(self.manifest), b'real network content'*800)
        finally:
            connection.close(); portal.shutdown(); portal.server_close(); worker.join(5)

    def test_recipient_mail_and_private_invitation(self):
        mailbox = secrets.token_bytes(32)
        body = seal_mail(self.public, mailbox_public(mailbox), 'secret subject', 'recipient only')
        self.assertEqual(open_mail(mailbox, self.public, body)['text'], 'recipient only')
        with self.assertRaises(ProtocolError): open_mail(secrets.token_bytes(32), self.public, body)
        self.source.publish(self.private, 'mail', 'message', body)
        token = invitation(self.source, self.private, self.key, ONION, 443)
        self.assertEqual(len(token), 4096); self.assertNotIn(ONION.encode(), token)
        result = accept_invitation(self.target, token, self.key, self.public)
        self.assertEqual(result['host'], ONION); self.assertFalse(result['membership_granted'])
        with self.assertRaises(ProtocolError): accept_invitation(self.target, token[:-1]+b'\x00', self.key, self.public)


if __name__ == '__main__': unittest.main()

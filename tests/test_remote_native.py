"""Real mutual TLS, scoped signatures and production native Provider execution."""
import datetime
import hashlib
import ipaddress
from pathlib import Path
import ssl
import threading
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from test_native_integration import NativeFixture
from ziokt.protocol import ProtocolError, encoded, make_private
from ziokt.remote import remote_server, request_remote, resource_for, tls_context
from ziokt.security import grant


class RemoteTests(NativeFixture):
    def certificates(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Ziokt test CA")])
        ca = x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=0), True).sign(key, hashes.SHA256())
        ca_path = self.base/"ca.pem"; ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        pairs = {}
        for name, usage in (("server", ExtendedKeyUsageOID.SERVER_AUTH), ("client", ExtendedKeyUsageOID.CLIENT_AUTH)):
            private = ec.generate_private_key(ec.SECP256R1())
            cert = x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])).issuer_name(subject).public_key(private.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=False, path_length=None), True).add_extension(x509.ExtendedKeyUsage([usage]), False).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False).sign(key, hashes.SHA256())
            cert_path, key_path = self.base/(name+".pem"), self.base/(name+".key")
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())); make_private(key_path)
            pairs[name] = (cert_path, key_path, cert)
        return ca_path, pairs

    def test_mutual_tls_native_call_and_persistent_grant_replay_rejection(self):
        ca, pairs = self.certificates()
        signer = ed25519.Ed25519PrivateKey.generate()
        private = signer.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        public = signer.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        client_hash = hashlib.sha256(pairs["client"][2].public_bytes(serialization.Encoding.DER)).hexdigest()
        trusted = {client_hash: {"public_key": public, "methods": ["status.get"], "providers": ["shadow6-local"]}}
        server_context = tls_context(*pairs["server"][:2], ca, server=True)
        client_context = tls_context(*pairs["client"][:2], ca)
        server = remote_server(self.federation, server_context, self.base/"remote-replay.sqlite", trusted)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            request = {"provider_id": "shadow6-local", "method": "status.get", "params": {}}
            token = grant(private, audience="shadow6-local", action="status.get", resource="provider:read",
                          federation="test", request_digest="sha256:"+hashlib.sha256(encoded(request)).hexdigest())
            result = request_remote("127.0.0.1", server.server_port, client_context, request, token)
            self.assertTrue(result["enabled"])
            self.assertEqual(result["native_project"], "shadow6")
            with self.assertRaises(ProtocolError) as replay:
                request_remote("127.0.0.1", server.server_port, client_context, request, token)
            self.assertEqual(replay.exception.code, "REPLAY_REJECTED")
            wrong = {**request, "method": "operation.commit"}
            with self.assertRaises(ProtocolError):
                request_remote("127.0.0.1", server.server_port, client_context, wrong, token)
        finally:
            server.shutdown(); server.server_close(); thread.join(5)

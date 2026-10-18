"""Lightweight TLS certificate helper for ZDNS (DoT/DoH)."""
import datetime
import ipaddress
from pathlib import Path
import tempfile
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


def make_ephemeral_cert(*, hostname='dns.ziokt.com', ip='127.0.0.1'):
    """Generate a self-signed ephemeral TLS certificate for local/test DoT."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
    ])
    sans = [
        x509.DNSName(hostname),
        x509.DNSName('localhost'),
    ]
    try:
        sans.append(x509.IPAddress(ipaddress.ip_address(ip)))
    except ValueError:
        pass
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName(sans),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    td = tempfile.TemporaryDirectory(prefix='ziokt-dot-tls-')
    cert_path = Path(td.name) / 'cert.pem'
    key_path = Path(td.name) / 'key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    return str(cert_path), str(key_path), td


def get_cert_and_key(tls_cert=None, tls_key=None, host='127.0.0.1'):
    prod_c = Path('/home/admin/.local/share/ziokt-production/caddy-data/caddy/certificates/acme-v02.api.letsencrypt.org-directory/dns.ziokt.com/dns.ziokt.com.crt')
    prod_k = Path('/home/admin/.local/share/ziokt-production/caddy-data/caddy/certificates/acme-v02.api.letsencrypt.org-directory/dns.ziokt.com/dns.ziokt.com.key')
    if tls_cert and tls_key and Path(tls_cert).exists() and Path(tls_key).exists():
        return str(tls_cert), str(tls_key), None
    if prod_c.exists() and prod_k.exists():
        return str(prod_c), str(prod_k), None
    return make_ephemeral_cert(ip=host)

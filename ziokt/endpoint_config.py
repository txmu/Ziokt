"""Configurable origins and local management listeners; no public host allowlist."""
import ipaddress
from urllib.parse import urlsplit

def https_origin(value):
    if type(value) is not str or not 1<=len(value)<=2048:raise ValueError('bounded HTTPS origin required')
    parsed=urlsplit(value)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:raise ValueError('exact public HTTPS origin required')
    parsed.port
    return value

def local_listener(value):
    try:
        address=ipaddress.ip_address(value)
        if not address.is_loopback:raise ValueError()
    except (ValueError,TypeError):raise ValueError('management listener must be a literal loopback IPv4/IPv6 address; publish through authenticated TLS') from None
    return str(address)

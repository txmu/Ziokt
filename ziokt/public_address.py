"""Bounded, cached server egress observation, never a service reachability claim."""
from http.client import HTTPException
import ipaddress
import threading
import time
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class PublicAddress:
    # Fixed observation services; no request-controlled destinations or proxies.
    SOURCES = ('https://api.ipify.org', 'https://checkip.amazonaws.com')

    def __init__(self, ttl=300, retry_after=30, sources=None):
        self.sources=tuple(self.SOURCES if sources is None else sources)
        if len(self.sources)>4:raise ValueError('public observation source budget')
        for source in self.sources:
            parsed=urlsplit(source)
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('configured HTTPS observation URL required')
        self.ttl = ttl
        self.retry_after = retry_after
        self.lock = threading.Lock()
        self.value = None
        self.expires = 0

    def observe(self):
        with self.lock:
            now = time.monotonic()
            if now < self.expires:
                return dict(self.value)
            opener = build_opener(ProxyHandler({}), HTTPSHandler(), NoRedirect())
            for source in self.sources:
                try:
                    with opener.open(source, timeout=2) as response:
                        raw = response.read(65)
                    if len(raw) > 64:
                        raise ValueError('address response too long')
                    address = ipaddress.ip_address(raw.decode('ascii').strip())
                    if not address.is_global:
                        raise ValueError('non-public address')
                    self.value = {'ok': True, 'schema': 'ziokt.public-address.v1',
                                  'address': str(address), 'source': source,
                                  'observed_at': int(time.time()),
                                  'meaning': 'server-egress-only', 'service_reachability_verified': False}
                    self.expires = time.monotonic() + self.ttl
                    return dict(self.value)
                except (OSError, ValueError, UnicodeError, HTTPException):
                    continue
            self.value = {'ok': False, 'schema': 'ziokt.public-address.v1',
                          'error': {'code': 'PUBLIC_ADDRESS_UNAVAILABLE',
                                    'message': 'Server public address could not be observed', 'retryable': True}}
            self.expires = time.monotonic() + self.retry_after
            return dict(self.value)


PUBLIC_ADDRESS = PublicAddress()

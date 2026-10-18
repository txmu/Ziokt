"""Component-scoped names. DNS answers never confer identity or service authority.

Root ownership is supplied by a node's verified native registry, never by the
resolver's cache or a self-signed DNS claim. Corium NNS keys remain suffix-free.
"""
import ipaddress
import re
import time
from urllib.parse import urlsplit
from .protocol import ProtocolError, encoded
from .security import verify

GROUPS = {
    'corium': 'cor c corium corix', 'shadow6': 's6 s shadow shadow6',
    'etp': 'etp e', 'safefs': 'safefs fs f', 'sim': 'sim m',
    'tri': 'tri t 3c', 'ufs': 'ufs u', 'dcpm': 'dcpm dr d',
    'watchat': 'wat w chat', 'zda': 'zda ano a num',
    'ziokt': 'ziokt ziokn ziok zioktruk zio zi zioktriuk zioktruik z',
}
SUFFIXES = {s: component for component, suffixes in GROUPS.items() for s in suffixes.split()}
SUFFIXES.update({chr(c): 'ziokt' for c in range(97, 123) if chr(c) not in SUFFIXES})
LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z')
KEY = re.compile(r'[0-9a-f]{64}\Z')
DOMAIN = 'Ziokt/name-delegation/v1'


def fail(message):
    raise ProtocolError('NAME_REJECTED', message)


def split_name(name):
    if not isinstance(name, str) or len(name) > 254 or not name.isascii():
        fail('bounded ASCII name required; encode international names as IDNA')
    labels = name.lower().removesuffix('.').split('.')
    if not 2 <= len(labels) <= 10 or any(not LABEL.fullmatch(x) for x in labels):
        fail('canonical labels required')
    component = SUFFIXES.get(labels[-1])
    if component is None:
        raise ProtocolError('REFUSED', 'suffix is outside Ziokt; no public DNS lookup performed')
    # Native root key is label only; child labels are delegated separately.
    return '.'.join(labels), component, labels[-2], list(reversed(labels[:-2]))


def public_records(value):
    if not isinstance(value, list) or len(value) > 32:
        fail('bounded explicitly public record list required')
    result = []
    for record in value:
        if not isinstance(record, dict) or set(record) != {'type', 'value', 'ttl'}:
            fail('exact public record schema required')
        kind, data, ttl = record['type'], record['value'], record['ttl']
        if type(ttl) is not int or not 0 <= ttl <= 3600:
            fail('bounded TTL required')
        if kind in ('A', 'AAAA'):
            try:
                address = ipaddress.ip_address(data)
            except (ValueError, TypeError):
                fail('invalid address')
            if address.version != (4 if kind == 'A' else 6) or not address.is_global:
                fail('public DNS requires global address; private endpoints belong in encrypted descriptors')
            data = str(address)
        elif kind == 'TXT':
            # Arbitrary identities, routes and endpoint dumps are deliberately not TXT records.
            if not isinstance(data, str) or not re.fullmatch(r'ziokt-descriptor=sha256:[0-9a-f]{64}', data):
                fail('only opaque public descriptor digest is supported in TXT')
        elif kind == 'HTTPS':
            if (not isinstance(data, dict) or set(data) != {'priority', 'target', 'alpn', 'port', 'ech'} or
                    type(data['priority']) is not int or not 1 <= data['priority'] <= 65535 or
                    type(data['port']) is not int or not 1 <= data['port'] <= 65535 or
                    data['alpn'] not in (['h2'], ['h2', 'http/1.1'], ['h3', 'h2'])):
                fail('bounded HTTPS service binding required')
            target = data['target']
            if target != '.':
                split_name(target)
            import base64
            try:
                ech = base64.b64decode(data['ech'], validate=True)
            except (ValueError, TypeError):
                fail('invalid ECHConfigList encoding')
            if ech and (len(ech) > 2048 or len(ech) < 6 or int.from_bytes(ech[:2], 'big') != len(ech)-2):
                fail('invalid ECHConfigList length')
            # Published ECH bytes do not assert TLS termination actually supports ECH.
        else:
            fail('unsupported public DNS type')
        result.append({'type': kind, 'value': data, 'ttl': ttl})
    return result


def descriptor(value):
    if not isinstance(value, dict) or set(value) != {'public_dns', 'services', 'private'}:
        fail('exact descriptor required')
    public_records(value['public_dns'])
    services = value['services']
    if not isinstance(services, dict) or len(services) > len(GROUPS) or set(services)-set(GROUPS):
        fail('component-scoped service map required')
    for component, entry in services.items():
        # Public discovery is an opaque content reference. Access to that content
        # and its decryption are independently authorized by the component.
        if not isinstance(entry, dict) or set(entry) != {'object', 'access'}:
            fail('service references cannot contain raw addresses or identities')
        if not isinstance(entry['object'], str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', entry['object']):
            fail('content-addressed service description required')
        if entry['access'] not in ('public', 'authenticated'):
            fail('explicit access classification required')
    if value['private'] is not None:
        import base64
        private = value['private']
        if not isinstance(private, dict) or set(private) != {'scheme', 'ciphertext'} or private['scheme'] != 'ziokt.sealed.v1':
            fail('private descriptions must be sealed, not plaintext metadata')
        try:
            raw = base64.b64decode(private['ciphertext'], validate=True)
        except (TypeError, ValueError):
            fail('invalid encrypted description')
        if len(raw) != 4096:
            fail('private service description must use a padded 4096-byte envelope')
    return value


class Names:
    """Node-backed verifier. Each adapter is pinned to exactly one component.

    adapter(root) -> {owner, revision, expires_at, proof, delegations}.
    The adapter MUST verify native ownership/finality and proof before returning.
    A root self-signature alone is never an ownership proof. Changes/registration
    go through the native registry; resolver never writes native state.
    """
    def __init__(self, sources, *, network_id="ziokt-main", clock=time.time):
        if not isinstance(sources, dict) or set(sources)-set(GROUPS):
            fail('known component sources required')
        if any(not callable(source) for source in sources.values()):
            fail('verified node adapters required')
        if not isinstance(network_id, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", network_id):
            fail("explicit bounded network identity required")
        self.sources, self.clock, self.network_id = dict(sources), clock, network_id

    def resolve(self, name, *, component=None, public=True):
        canonical, authority, root, children = split_name(name)
        source = self.sources.get(authority)
        if source is None:
            raise ProtocolError('SOURCE_UNAVAILABLE', 'no node configured for this suffix authority')
        native = source(root)
        if not isinstance(native, dict) or set(native) != {'owner', 'revision', 'expires_at', 'proof', 'delegations', 'published_suffixes', 'network_id'}:
            fail('verified native registration required')
        if native['network_id'] != self.network_id:
            fail('native registration belongs to another network')
        suffixes = native['published_suffixes']
        if (not isinstance(suffixes, list) or not 1 <= len(suffixes) <= 32 or
                any(not isinstance(s, str) for s in suffixes) or len(set(suffixes)) != len(suffixes) or any(SUFFIXES.get(s) != authority for s in suffixes)):
            fail('explicit component-owned publication suffixes required')
        if canonical.rsplit('.', 1)[1] not in suffixes:
            raise ProtocolError('NAME_NOT_FOUND', 'owner did not publish this suffix')
        owner = native['owner']
        if not isinstance(owner, str) or not KEY.fullmatch(owner) or not native['proof']:
            fail('verified native owner required')
        if (type(native['revision']) is not int or native['revision'] < 1 or
                type(native['expires_at']) is not int or native['expires_at'] <= self.clock()):
            fail('registration is expired or invalid')
        published = native['delegations']
        if not isinstance(published, dict) or len(published) > 128 or len(encoded(published)) > 65536:
            fail('bounded signed delegation map required')
        chain = []
        lookup = root
        for label in [None] + children:
            if label is not None:lookup = label + '.' + lookup
            envelope = published.get(lookup)
            if envelope is None:
                raise ProtocolError('NAME_NOT_FOUND', 'requested child is not registered')
            chain.append(envelope)
        path = root
        expiry = native['expires_at']
        current_revision = native['revision']
        payload = None
        for index, envelope in enumerate(chain):
            payload = verify(envelope, owner, DOMAIN)
            if not isinstance(payload, dict) or set(payload) != {'network_id', 'component', 'path', 'parent_revision', 'revision', 'expires_at', 'delegate', 'descriptor'}:
                fail('exact delegation schema required')
            if payload['network_id'] != self.network_id or payload['component'] != authority or payload['path'] != path or payload['parent_revision'] != current_revision:
                fail('delegation belongs to another authority, name or parent revision')
            if (type(payload['revision']) is not int or payload['revision'] < 1 or
                    type(payload['expires_at']) is not int or not self.clock() < payload['expires_at'] <= expiry):
                fail('expired or invalid delegation')
            descriptor(payload['descriptor'])
            delegate = payload['delegate']
            if delegate is not None and (not isinstance(delegate, str) or not KEY.fullmatch(delegate)):
                fail('invalid child delegation key')
            expiry, current_revision = payload['expires_at'], payload['revision']
            if index < len(children):
                if delegate is None:
                    fail('parent did not authorize child registration')
                owner = delegate
                path = children[index] + '.' + path
        # Public DNS exposes no identities, membership, routes, or encrypted data.
        if public:
            return {'name': canonical, 'records': public_records(payload['descriptor']['public_dns']),
                    'expires_at': expiry, 'authenticated_access': False}
        if component not in GROUPS:
            fail('explicit target component required')
        return {'name': canonical, 'source_component': authority,
                'service': payload['descriptor']['services'].get(component),
                'private': payload['descriptor']['private'], 'expires_at': expiry,
                'ownership_proof': native['proof'], 'delegations': chain,
                'authenticated_access': False}


class NameNetworks:
    """Independent naming views. Missing views never fall back to another chain."""
    def __init__(self, realms, *, default):
        if (not isinstance(realms, dict) or not 1 <= len(realms) <= 32 or default not in realms or
                any(not isinstance(k, str) or not LABEL.fullmatch(k) or not isinstance(v, Names) for k,v in realms.items())):
            fail('bounded explicit naming realms required')
        self.realms, self.default = dict(realms), default

    def view(self, realm=None):
        selected = self.default if realm is None else realm
        if selected not in self.realms:
            raise ProtocolError('REFUSED', 'unknown naming realm; cross-network fallback forbidden')
        return self.realms[selected]

    def resolve(self, name, *, realm=None, component=None, public=True):
        return self.view(realm).resolve(name, component=component, public=public)

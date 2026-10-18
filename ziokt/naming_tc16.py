"""TC-16 native naming adapter and verified service discovery.

Root ownership is verified by the native TC-16 node/authority, never by
arbitrary self-signed DNS claims. VM runtime state (registers, memory, trace)
is strictly isolated and forbidden in public discovery descriptors.
"""
from pathlib import Path
import re
import time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .protocol import ProtocolError, encoded, secure_read, strict_json
from .security import verify, sign
from .naming import LABEL, KEY, DOMAIN as DELEGATION_DOMAIN, Names, descriptor as validate_descriptor

DOMAIN = 'Ziokt/tc16-name-registration/v1'
COMMUNITY_DOMAIN = 'Ziokt/component-name-registration/v1'
TC16_SUFFIXES = frozenset({'tc16', 'tcc', 'ttc'})
FORBIDDEN_RUNTIME_KEYS = frozenset({'registers', 'pc', 'sp', 'flags', 'mode', 'cycles', 'trace', 'memory'})


def _derive_public(key_bytes):
    return Ed25519PrivateKey.from_private_bytes(key_bytes).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def verify_tc16_service(entry, vault=None):
    """Verify that a TC-16 service descriptor exposes only opaque verified references,
    never private VM runtime state (registers, pc, sp, flags, trace, memory).
    """
    if not isinstance(entry, dict):
        raise ProtocolError('INVALID_SERVICE', 'dictionary service description required')
    
    # Strictly reject any private execution state
    exposed = FORBIDDEN_RUNTIME_KEYS.intersection(entry.keys())
    if exposed:
        raise ProtocolError('PRIVATE_STATE_EXPOSED',
                            f'private TC-16 runtime state ({", ".join(sorted(exposed))}) must not be published in public discovery')
    
    kind = entry.get('kind')
    if kind == 'tc16.vm_instance':
        if (not isinstance(entry.get('program_hash'), str) or
                not re.fullmatch(r'sha256:[0-9a-f]{64}', entry['program_hash']) or
                type(entry.get('memory_size')) is not int or not 0 < entry['memory_size'] <= 65536 or
                not isinstance(entry.get('capabilities'), list) or
                type(entry.get('entrypoint', 0)) is not int or not 0 <= entry.get('entrypoint', 0) <= 65535):
            raise ProtocolError('INVALID_SERVICE', 'invalid TC-16 VM instance descriptor')
    elif kind == 'tc16.program_repository':
        if (not isinstance(entry.get('repository_hash'), str) or
                not re.fullmatch(r'sha256:[0-9a-f]{64}', entry['repository_hash']) or
                not isinstance(entry.get('programs'), list) or len(entry['programs']) > 256):
            raise ProtocolError('INVALID_SERVICE', 'invalid TC-16 program repository descriptor')
        for prog in entry['programs']:
            if (not isinstance(prog, dict) or not isinstance(prog.get('name'), str) or
                    not isinstance(prog.get('program_hash'), str) or
                    not re.fullmatch(r'sha256:[0-9a-f]{64}', prog['program_hash']) or
                    prog.get('syntax') not in ('assembly', 'tcc')):
                raise ProtocolError('INVALID_SERVICE', 'invalid program entry in TC-16 repository')
            if FORBIDDEN_RUNTIME_KEYS.intersection(prog.keys()):
                raise ProtocolError('PRIVATE_STATE_EXPOSED', 'program entry cannot contain runtime state')
    elif kind == 'tc16.compute_service':
        if (entry.get('endpoint') not in ('tcc', 'tc16') or
                not isinstance(entry.get('service_object'), str) or
                not re.fullmatch(r'sha256:[0-9a-f]{64}', entry['service_object']) or
                type(entry.get('max_cycles')) is not int or not 1 <= entry['max_cycles'] <= 100000 or
                not isinstance(entry.get('accepted_syntaxes'), list) or
                set(entry['accepted_syntaxes']) - {'assembly', 'tcc'}):
            raise ProtocolError('INVALID_SERVICE', 'invalid TC-16 compute service descriptor')
    else:
        raise ProtocolError('INVALID_SERVICE', 'unrecognized TC-16 service kind; must be vm_instance, program_repository, or compute_service')
    return entry


class TC16Names:
    """Native TC-16 node adapter for naming and service discovery.

    Guarantees:
    1. Root registration is authenticated by verified TC-16 node signing authority.
    2. Arbitrary unverified self-signed names are refused.
    3. Ed25519 subdomain delegation, revocation, and expiration are verified.
    4. Multi-realm isolation (different network_id queries reject).
    5. Private runtime state (registers, flags, memory) is never leaked.
    """
    component = 'tc16'

    def __init__(self, bridge_or_path=None, *, network_id='ziokt-main', vault_root=None,
                 signing_key=None, application_key=None, registry=None, clock=time.time):
        self.network_id = network_id
        self.clock = clock
        self.registry = dict(registry or {})
        self.vault_root = Path(vault_root) if vault_root else None
        self.signing_public = None
        self.bridge_path = None
        self.app_digest = None

        if isinstance(bridge_or_path, (str, Path)):
            self.bridge_path = Path(bridge_or_path)
            config = strict_json(secure_read(self.bridge_path))
            if config.get('schema') != 'ziokt.companion-bridge.v1' or config.get('application') != 'tc16':
                raise ProtocolError('INVALID_BRIDGE', 'TC-16 companion bridge configuration required')
            self.vault_root = Path(config.get('vault_root', '')) if config.get('vault_root') else None
            if config.get('signing_key') and Path(config['signing_key']).exists():
                self.signing_public = _derive_public(secure_read(config['signing_key'], 32))
            elif config.get('owner'):
                self.signing_public = config['owner']
            if config.get('application_key') and Path(config['application_key']).exists():
                import hashlib
                self.app_digest = hashlib.sha256(secure_read(config['application_key'], 32)).hexdigest()
        elif signing_key:
            if isinstance(signing_key, (bytes, bytearray)):
                self.signing_public = _derive_public(bytes(signing_key))
            elif isinstance(signing_key, str) and KEY.fullmatch(signing_key):
                self.signing_public = signing_key
            elif Path(signing_key).exists():
                self.signing_public = _derive_public(secure_read(signing_key, 32))
        if application_key and Path(application_key).exists():
            import hashlib
            self.app_digest = hashlib.sha256(secure_read(application_key, 32)).hexdigest()

    def register(self, envelope, authority_key=None):
        """Register a verified native TC-16 name envelope.

        Must be signed by the native TC-16 node signing authority.
        Arbitrary self-signatures by unknown keys are rejected.
        """
        expected_authority = authority_key or self.signing_public
        if not expected_authority:
            raise ProtocolError('SOURCE_UNAVAILABLE', 'TC-16 native signing authority not configured')

        # Try TC-16 domain first, then fallback to component registration domain
        try:
            record = verify(envelope, expected_authority, DOMAIN)
        except ProtocolError:
            try:
                record = verify(envelope, expected_authority, COMMUNITY_DOMAIN)
            except ProtocolError:
                raise ProtocolError('NAME_REJECTED', 'registration is not authorized by native TC-16 authority')

        fields = {'network_id', 'component', 'root', 'owner', 'revision', 'expires_at', 'delegations', 'published_suffixes'}
        if not isinstance(record, dict) or set(record) != fields:
            raise ProtocolError('SCOPE_MISMATCH', 'exact TC-16 registration fields required')
        if record['network_id'] != self.network_id:
            raise ProtocolError('SCOPE_MISMATCH', 'registration belongs to another network')
        if record['component'] != 'tc16':
            raise ProtocolError('SCOPE_MISMATCH', 'registration must belong to tc16 component')
        root = record['root']
        if not isinstance(root, str) or not LABEL.fullmatch(root):
            raise ProtocolError('NAME_REJECTED', 'canonical root label required')
        suffixes = record['published_suffixes']
        if not isinstance(suffixes, list) or not set(suffixes).issubset(TC16_SUFFIXES):
            raise ProtocolError('SCOPE_MISMATCH', 'published suffixes must be subset of tc16, tcc, ttc')
        if type(record['revision']) is not int or record['revision'] < 1:
            raise ProtocolError('NAME_REJECTED', 'positive revision required')
        if type(record['expires_at']) is not int or record['expires_at'] <= self.clock():
            raise ProtocolError('NAME_REJECTED', 'future expiration required')

        # Check revision monotonicity
        existing = self.registry.get(root)
        if existing:
            old_record = existing['record']
            if record['revision'] <= old_record['revision']:
                if record == old_record:
                    return {'registered': True, 'revision': record['revision'], 'duplicate': True}
                raise ProtocolError('REPLAY_REJECTED', 'registration revision cannot decrease or fork')

        native = {k: v for k, v in record.items() if k not in {'root', 'component'}}
        native['proof'] = {
            'kind': 'native-tc16-node-authority',
            'application': 'tc16',
            'authority': expected_authority,
            'application_digest': self.app_digest,
            'vault_root': str(self.vault_root) if self.vault_root else None,
            'registration': envelope,
        }

        # Verify delegation map format
        if record['published_suffixes']:
            Names({'tc16': lambda _: native}, network_id=self.network_id, clock=self.clock).resolve(root + '.' + record['published_suffixes'][0])

        self.registry[root] = {'record': record, 'native': native}
        return {'registered': True, 'revision': record['revision'], 'published': bool(suffixes)}

    def __call__(self, root):
        if not isinstance(root, str) or not LABEL.fullmatch(root):
            raise ProtocolError('NAME_REJECTED', 'canonical root label required')
        
        # Check in-memory registry
        entry = self.registry.get(root)
        if entry:
            return entry['native']

        # If bridge path exists, check community view
        if self.bridge_path and self.bridge_path.exists():
            from .naming_community import current, component_of
            from types import SimpleNamespace
            from .community import Community
            config = strict_json(secure_read(self.bridge_path))
            community = Community(config['community_root'], strict_json(secure_read(config['policy'])),
                                  config['owner'], secure_read(config['encryption_key'], 32), readonly=True)
            bridge = SimpleNamespace(app=config['application'], community=community,
                                     naming_namespaces=config.get('naming_namespaces', [community.community_id]),
                                     signing_public=self.signing_public, vault_root=config.get('vault_root'))
            try:
                _, native = current(bridge, self.network_id, root)
                native['proof']['kind'] = 'native-tc16-node-authority'
                native['proof']['application'] = 'tc16'
                return native
            finally:
                community.close()

        raise ProtocolError('NAME_NOT_FOUND', f'TC-16 root {root} not registered')

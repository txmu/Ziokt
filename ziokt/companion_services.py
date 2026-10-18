"""Verified companion service discovery objects.

Each companion publishes native content-addressed service descriptors
into descriptor.services[component]. Public DNS answers remain opaque
digests, while authenticated component discovery reveals and validates
the companion's native resource ownership.
"""
import re
from .protocol import ProtocolError
from .naming_tc16 import verify_tc16_service, FORBIDDEN_RUNTIME_KEYS

HEX64 = re.compile(r'[0-9a-f]{64}\Z')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')


def verify_tri_service(entry):
    if not isinstance(entry, dict) or entry.get('schema') != 'ziokt.tri-project.v1':
        raise ProtocolError('INVALID_SERVICE', 'exact Tri project descriptor required')
    if entry.get('engine') != 'ternary-computer-simulator' or not isinstance(entry.get('program'), str):
        raise ProtocolError('INVALID_SERVICE', 'valid Tri program and engine required')
    if not isinstance(entry.get('state'), dict):
        raise ProtocolError('INVALID_SERVICE', 'valid Tri state map required')
    return entry


def verify_zda_service(entry):
    if not isinstance(entry, dict):
        raise ProtocolError('INVALID_SERVICE', 'dictionary ZDA service descriptor required')
    schema = entry.get('schema')
    if schema == 'ziokt.ano-laws.v1':
        if not isinstance(entry.get('laws'), dict):
            raise ProtocolError('INVALID_SERVICE', 'ZDA laws map required')
    elif schema == 'ziokt.ano-calculate.v1':
        if entry.get('kind') not in ('numeric', 'symbolic') or not isinstance(entry.get('operation'), str):
            raise ProtocolError('INVALID_SERVICE', 'valid ZDA calculation contract required')
    elif schema == 'ziokt.ano-defence.v1':
        if not isinstance(entry.get('decision'), str):
            raise ProtocolError('INVALID_SERVICE', 'valid ZDA defence contract required')
    else:
        raise ProtocolError('INVALID_SERVICE', 'unrecognized ZDA service schema')
    return entry


def verify_ufs_service(entry):
    if not isinstance(entry, dict) or entry.get('schema') != 'ziokt.object-reference.v1':
        raise ProtocolError('INVALID_SERVICE', 'exact UFS object reference descriptor required')
    if (not isinstance(entry.get('object'), str) or not DIGEST.fullmatch(entry['object']) or
            type(entry.get('size')) is not int or entry['size'] < 0 or
            type(entry.get('ttl')) is not int or entry['ttl'] < 0):
        raise ProtocolError('INVALID_SERVICE', 'valid content-addressed object reference required')
    return entry


def verify_dcpm_service(entry):
    if not isinstance(entry, dict):
        raise ProtocolError('INVALID_SERVICE', 'dictionary dCPM service descriptor required')
    schema = entry.get('package_schema') or entry.get('schema')
    if schema in ('ziokt.dcpm-package.v2', 'ziokt.package-verification.v1'):
        if (not isinstance(entry.get('name'), str) or not isinstance(entry.get('version'), str) or
                not isinstance(entry.get('publisher'), str) or not HEX64.fullmatch(entry['publisher'])):
            raise ProtocolError('INVALID_SERVICE', 'valid dCPM package descriptor and publisher authority required')
    else:
        raise ProtocolError('INVALID_SERVICE', 'unrecognized dCPM package schema')
    return entry


def verify_shadow6_service(entry):
    if not isinstance(entry, dict):
        raise ProtocolError('INVALID_SERVICE', 'dictionary Shadow6 service descriptor required')
    schema = entry.get('schema')
    if schema == 'ziokt.node-profile.v1':
        if not isinstance(entry.get('profile'), str) or not entry['profile']:
            raise ProtocolError('INVALID_SERVICE', 'valid Shadow6 node profile required')
    elif schema == 'ziokt.extension-event.v1':
        if (entry.get('kind') != 'zkn-gift' or not isinstance(entry.get('content_digest'), str) or
                not DIGEST.fullmatch(entry['content_digest']) or entry.get('private') is not True):
            raise ProtocolError('INVALID_SERVICE', 'valid Shadow6 extension event contract required')
    else:
        raise ProtocolError('INVALID_SERVICE', 'unrecognized Shadow6 service schema')
    return entry


VERIFIERS = {
    'tc16': verify_tc16_service,
    'tri': verify_tri_service,
    'zda': verify_zda_service,
    'ufs': verify_ufs_service,
    'dcpm': verify_dcpm_service,
    'shadow6': verify_shadow6_service,
}


def verify_companion_service(component, service_dict):
    """Verify that a companion's native service descriptor matches its native schema."""
    verifier = VERIFIERS.get(component)
    if verifier is None:
        if not isinstance(service_dict, dict):
            raise ProtocolError('INVALID_SERVICE', 'dictionary service descriptor required')
        return service_dict
    return verifier(service_dict)

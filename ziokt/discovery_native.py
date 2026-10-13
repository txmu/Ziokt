"""Bounded signed discovery envelopes carried by locked Corium native paths."""
import base64
import hashlib
import re
import time

from .protocol import ProtocolError, strict_json


def fetch_records(client, peer_id, digest, *, cancellation=None, timeout=30):
    """Corium authenticates transport identity; the directory verifies members."""
    if (not isinstance(peer_id, str) or not re.fullmatch('[a-f0-9]{64}', peer_id) or
            not isinstance(digest, str) or not re.fullmatch('sha256:[a-f0-9]{64}', digest)):
        raise ProtocolError('INVALID_DISCOVERY', 'pinned Corium peer and object required')
    deadline, data, total = time.monotonic()+timeout, bytearray(), None
    for _ in range(3):
        if cancellation is not None and cancellation.is_set():
            raise ProtocolError('CANCELLED', 'native discovery cancelled')
        if time.monotonic() >= deadline: raise ProtocolError('DEADLINE_EXCEEDED', 'native discovery deadline')
        result = client.call('content.get', {'peer_id':peer_id, 'digest':digest, 'offset':len(data), 'length':6144},
                             timeout=max(.001,deadline-time.monotonic()), cancellation=cancellation)
        if (not isinstance(result, dict) or set(result) != {'status','digest','offset','total_size','data_base64'} or
                result['status'] != 'success' or result['digest'] != digest or type(result['offset']) is not int or result['offset'] != len(data) or
                type(result['total_size']) is not int or not 1 <= result['total_size'] <= 16384 or
                total is not None and total != result['total_size']):
            raise ProtocolError('INVALID_DISCOVERY', 'native discovery range correlation rejected')
        total = result['total_size']
        try: part = base64.b64decode(result['data_base64'], validate=True)
        except (ValueError, TypeError): raise ProtocolError('INVALID_DISCOVERY', 'native discovery encoding rejected')
        if not 1 <= len(part) <= min(6144,total-len(data)):
            raise ProtocolError('INVALID_DISCOVERY', 'native discovery range made no bounded progress')
        data.extend(part)
        if len(data) == total: break
    if len(data) != total or 'sha256:'+hashlib.sha256(data).hexdigest() != digest:
        raise ProtocolError('ARTIFACT_DIGEST_MISMATCH', 'native discovery object integrity rejected')
    envelope = strict_json(bytes(data),16384)
    if not isinstance(envelope,list) or not 1 <= len(envelope) <= 8:
        raise ProtocolError('INVALID_DISCOVERY', 'bounded signed native discovery records required')
    return envelope


def native_sources(config):
    from .config import load
    from .client import NativeClient
    if not isinstance(config,dict) or set(config) != {'federation_config','provider_id','sources'}:
        raise ProtocolError('INVALID_DISCOVERY', 'exact local Corium discovery binding required')
    federation = load(config['federation_config'])
    if not federation['enabled']: raise ProtocolError('DISCOVERY_DISABLED', 'native federation disabled')
    provider = next((p for p in federation['providers'] if p['provider_id'] == config['provider_id'] and p['native_project'] == 'corium'),None)
    if provider is None: raise ProtocolError('INVALID_DISCOVERY', 'Corium discovery provider missing')
    sources = config['sources']
    if not isinstance(sources,list) or not 1 <= len(sources) <= 2:
        raise ProtocolError('INVALID_DISCOVERY', 'at most two pinned native discovery sources')
    for source in sources:
        if (not isinstance(source,dict) or set(source) != {'peer_id','digest'} or
                not isinstance(source['peer_id'],str) or not re.fullmatch('[a-f0-9]{64}',source['peer_id']) or
                not isinstance(source['digest'],str) or not re.fullmatch('sha256:[a-f0-9]{64}',source['digest'])):
            raise ProtocolError('INVALID_DISCOVERY', 'pinned Corium peer and digest required')
    return NativeClient(federation['federation_id'],provider), sources

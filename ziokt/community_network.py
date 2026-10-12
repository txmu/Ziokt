"""Bounded encrypted community exchange over the existing mTLS/grant endpoint."""
import base64
import hashlib
from pathlib import Path
import threading

from .artifacts import ArtifactStore
from .community import MAX_BYTES, content_id, exact, hash_id
from .protocol import ProtocolError, encoded
from .security import sign, grant

METHODS = {'community.status', 'community.checkpoint.create', 'community.checkpoint.get'}


class CommunityEndpoint:
    def __init__(self, community, private):
        self.community, self.private = community, private
        self.public = sign({}, private, 'Ziokt/check-key/v1')['public_key']
        community._member(self.public, 'recover')
        self.exports = ArtifactStore(community.root/'exchange')
        self.lock = threading.RLock()
        self.cached = None

    def call(self, method, params, principal):
        if method not in METHODS: raise ProtocolError('POLICY_DENIED', 'unknown community network method')
        self.community._member(principal, 'replicate')
        with self.lock, self.community.lock:
            self.community._current()
            if method == 'community.status':
                exact(params, set())
                return {'community_id': self.community.community_id, 'policy': self.community.policy_id,
                        'records': self.community.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],
                        'publisher': self.public, 'runtime_ready': False,
                        'inventory_digest': self.community.inventory_digest()}
            if method == 'community.checkpoint.create':
                exact(params, set())
                inventory = self.community.inventory_digest()
                if self.cached and self.cached[0] == inventory:
                    self.exports.get(self.cached[1]['digest'])
                    return self.cached[1]
                if len(list(self.exports.root.iterdir())) >= 4:
                    raise ProtocolError('BACKPRESSURE', 'archive or remove reviewed exchange snapshots before exporting more')
                blob = self.community.checkpoint(self.private)
                digest = self.exports.put(blob)
                result = {'digest': digest, 'size': len(blob), 'publisher': self.public,
                          'community_id': self.community.community_id, 'policy': self.community.policy_id}
                self.cached = (inventory, result)
                return result
            exact(params, {'digest', 'offset', 'length'})
            hash_id(params['digest'])
            if type(params['offset']) is not int or params['offset'] < 0 or type(params['length']) is not int or not 1 <= params['length'] <= 6144:
                raise ProtocolError('INVALID_REQUEST', 'bounded snapshot content range required')
            # Stable immutable export; each response refers to the same bytes.
            blob = self.exports.get(params['digest'])
            if params['offset'] > len(blob): raise ProtocolError('INVALID_REQUEST', 'snapshot offset out of range')
            return {'digest': params['digest'], 'offset': params['offset'], 'size': len(blob),
                    'data_base64': base64.b64encode(blob[params['offset']:params['offset']+params['length']]).decode()}


def sync_remote(community, endpoint, context, private, *, publisher):
    """Fresh scoped grants per range; immutable digest pinned before restoration.

    Does not enable a direct path when a restricted community loses its carrier.
    Local apps and backups continue to function if this call cannot connect.
    """
    from .remote import request_remote, resource_for
    if community.policy['privacy'] == 'restricted' and endpoint.get('carrier') is None:
        raise ProtocolError('NO_POLICY_COMPLIANT_PATH', 'restricted community requires explicit onion carrier')
    def call(method, params):
        request = {'provider_id': community.community_id, 'method': method, 'params': params}
        token = grant(private, audience=community.community_id, action=method, resource=resource_for(method, params),
                      federation=community.community_id, request_digest=content_id(encoded(request)))
        return request_remote(endpoint['host'], endpoint['port'], context, request, token, carrier=endpoint.get('carrier'))
    status = call('community.status', {})
    exact(status, {'community_id', 'policy', 'records', 'publisher', 'runtime_ready', 'inventory_digest'})
    if status['community_id'] != community.community_id or status['policy'] != community.policy_id or status['publisher'] != publisher:
        raise ProtocolError('SCOPE_MISMATCH', 'remote community policy or publisher differs')
    if status['inventory_digest'] == community.inventory_digest():
        return {'unchanged': True, 'runtime_ready': False, 'native_apply_required': True}
    item = call('community.checkpoint.create', {})
    exact(item, {'digest', 'size', 'publisher', 'community_id', 'policy'})
    hash_id(item['digest'])
    if (item['publisher'] != publisher or item['community_id'] != community.community_id or item['policy'] != community.policy_id or
            type(item['size']) is not int or not 32 <= item['size'] <= MAX_BYTES):
        raise ProtocolError('SCOPE_MISMATCH', 'remote checkpoint publisher, policy or budget mismatch')
    data = bytearray()
    while len(data) < item['size']:
        length = min(6144, item['size']-len(data))
        part = call('community.checkpoint.get', {'digest': item['digest'], 'offset': len(data), 'length': length})
        exact(part, {'digest', 'offset', 'size', 'data_base64'})
        if part['digest'] != item['digest'] or part['offset'] != len(data) or part['size'] != item['size']:
            raise ProtocolError('INVALID_RESPONSE', 'immutable snapshot range drifted')
        try: chunk = base64.b64decode(part['data_base64'], validate=True)
        except (ValueError, TypeError): raise ProtocolError('INVALID_RESPONSE', 'invalid range encoding')
        if len(chunk) != length: raise ProtocolError('INVALID_RESPONSE', 'truncated snapshot range')
        data.extend(chunk)
    if content_id(data) != item['digest']:
        raise ProtocolError('ARTIFACT_DIGEST_MISMATCH', 'downloaded checkpoint differs from pinned digest')
    return community.restore(bytes(data), publisher)

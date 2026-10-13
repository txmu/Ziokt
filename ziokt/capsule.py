"""Air-gapped offline synchronization capsules: survive complete network blackouts.

Enables partition-tolerant "sneakernet" distribution via physical storage
(USB drive, optical media, SD card) with atomic causal DAG state merge.
"""
import io
import os
from pathlib import Path
import secrets
import struct
import time

from .community import Community, content_id, exact
from .protocol import ProtocolError, encoded, strict_json, secure_read, make_private
from .security import sign, verify

CAPSULE_MAGIC = b'ZIOKT-CAPSULE-V1\n'
MAX_CAPSULE_HEADER = 65536


def export_capsule(community, private, output_path=None, *, description=''):
    if not isinstance(description, str) or len(description) > 256:
        raise ProtocolError('INVALID_CAPSULE', 'bounded capsule description required')
    with community.lock:
        community._current()
        public = sign({}, private, 'test')['public_key']
        community._member(public, 'recover')
        checkpoint = community.checkpoint(private)
        origin = community.origin()
        events = community._events()
        header = {
            'schema': 'ziokt.capsule.v1',
            'community_id': community.community_id,
            'policy': community.policy_id,
            'publisher': public,
            'origin': origin,
            'description': description,
            'records_count': len(events),
            'checkpoint_digest': content_id(checkpoint),
            'timestamp': int(time.time()),
            'nonce': secrets.token_hex(16)
        }
        envelope = sign(header, private, 'Ziokt/capsule/v1')
        manifest_raw = encoded(envelope)
        if len(manifest_raw) > MAX_CAPSULE_HEADER:
            raise ProtocolError('CAPSULE_LIMIT', 'capsule header exceeds budget')
        body = CAPSULE_MAGIC + struct.pack('!I', len(manifest_raw)) + manifest_raw + checkpoint
        if output_path is not None:
            from .cli import write_binary_exclusive
            write_binary_exclusive(Path(output_path), body)
        return {
            'output': str(output_path) if output_path is not None else None,
            'size': len(body),
            'digest': content_id(body),
            'checkpoint_digest': header['checkpoint_digest'],
            'records_count': header['records_count'],
            'publisher': public,
            'body': body
        }


def read_capsule_envelope(data):
    if not isinstance(data, bytes) or len(data) < len(CAPSULE_MAGIC) + 4:
        raise ProtocolError('INVALID_CAPSULE', 'truncated capsule material')
    if not data.startswith(CAPSULE_MAGIC):
        raise ProtocolError('INVALID_CAPSULE', 'unrecognized capsule format magic')
    offset = len(CAPSULE_MAGIC)
    header_len = struct.unpack('!I', data[offset:offset+4])[0]
    offset += 4
    if not 1 <= header_len <= MAX_CAPSULE_HEADER or offset + header_len > len(data):
        raise ProtocolError('INVALID_CAPSULE', 'invalid capsule manifest length')
    manifest_raw = data[offset:offset+header_len]
    offset += header_len
    checkpoint_bytes = data[offset:]
    envelope = strict_json(manifest_raw, MAX_CAPSULE_HEADER)
    publisher = envelope.get('public_key') if isinstance(envelope, dict) else None
    if not publisher:
        raise ProtocolError('INVALID_CAPSULE', 'signed capsule envelope required')
    payload = verify(envelope, publisher, 'Ziokt/capsule/v1')
    exact(payload, {'schema', 'community_id', 'policy', 'publisher', 'origin',
                    'description', 'records_count', 'checkpoint_digest',
                    'timestamp', 'nonce'}, 'INVALID_CAPSULE')
    if payload['schema'] != 'ziokt.capsule.v1' or payload['publisher'] != publisher:
        raise ProtocolError('INVALID_CAPSULE', 'capsule header scope or publisher mismatch')
    if content_id(checkpoint_bytes) != payload['checkpoint_digest']:
        raise ProtocolError('ARTIFACT_DIGEST_MISMATCH', 'capsule checkpoint differs from signed digest')
    return payload, publisher, checkpoint_bytes


def capsule_info(source):
    if isinstance(source, (str, Path)):
        data = secure_read(Path(source), 64 * 1024 * 1024, private=None)
    else:
        data = source
    payload, publisher, checkpoint_bytes = read_capsule_envelope(data)
    return {**payload, 'size': len(data), 'checkpoint_size': len(checkpoint_bytes)}


def import_capsule(community, source, *, expected_publisher=None):
    if isinstance(source, (str, Path)):
        data = secure_read(Path(source), 64 * 1024 * 1024, private=None)
    else:
        data = source
    payload, publisher, checkpoint_bytes = read_capsule_envelope(data)
    if expected_publisher and publisher != expected_publisher:
        raise ProtocolError('POLICY_DENIED', 'capsule publisher differs from expected authority')
    with community.lock:
        community._current()
        if payload['community_id'] != community.community_id:
            raise ProtocolError('SCOPE_MISMATCH', 'capsule belongs to another community')
        restored = community.restore(checkpoint_bytes, publisher)
        return {
            'restored': restored,
            'capsule': payload,
            'publisher': publisher,
            'offline_sync_completed': True
        }

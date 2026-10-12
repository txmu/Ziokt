"""Recipient-only mailboxes and privately exchanged scoped service invitations."""
import base64
import secrets
import struct
import time

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from .community import exact, PUBLIC
from .protocol import ProtocolError, encoded, strict_json
from .security import sign, verify
from .carrier import onion_address


def mailbox_public(private):
    return X25519PrivateKey.from_private_bytes(private).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def _mail_key(shared, recipient):
    return HKDF(hashes.SHA256(), 32, None, b'Ziokt/mailbox/v1/'+recipient.encode()).derive(shared)


def seal_mail(recipient, mailbox_key, subject, text):
    if not isinstance(recipient, str) or not PUBLIC.fullmatch(recipient) or not isinstance(subject, str) or not isinstance(text, str):
        raise ProtocolError('INVALID_MAIL', 'pinned recipient identity, mailbox key and text required')
    payload = encoded({'subject': subject, 'text': text})
    if len(payload) > 1984: raise ProtocolError('MAIL_LIMIT', 'private message exceeds padded mailbox budget')
    ephemeral = X25519PrivateKey.generate()
    try: key = _mail_key(ephemeral.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(mailbox_key))), recipient)
    except (ValueError, TypeError): raise ProtocolError('INVALID_MAIL', 'exact X25519 recipient mailbox key required')
    public = ephemeral.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    nonce = secrets.token_bytes(12)
    plain = struct.pack('!I', len(payload))+payload
    plain += secrets.token_bytes(1988-len(plain))
    ciphertext = public+nonce+AESGCM(key).encrypt(nonce, plain, recipient.encode())
    return {'to': recipient, 'ciphertext': base64.b64encode(ciphertext).decode()}


def open_mail(private, recipient, body):
    exact(body, {'to', 'ciphertext'}, 'INVALID_MAIL')
    if body['to'] != recipient: raise ProtocolError('POLICY_DENIED', 'message belongs to another recipient')
    try:
        blob = base64.b64decode(body['ciphertext'], validate=True)
        if len(blob) != 2048: raise ValueError()
        key = _mail_key(X25519PrivateKey.from_private_bytes(private).exchange(X25519PublicKey.from_public_bytes(blob[:32])), recipient)
        plain = AESGCM(key).decrypt(blob[32:44], blob[44:], recipient.encode())
        size = struct.unpack('!I', plain[:4])[0]
        if size > len(plain)-4: raise ValueError()
        value = strict_json(plain[4:4+size]); exact(value, {'subject', 'text'}, 'INVALID_MAIL')
        if not all(isinstance(v, str) for v in value.values()): raise ValueError()
        return value
    except (ValueError, TypeError, InvalidTag):
        raise ProtocolError('MAIL_AUTH_FAILED', 'recipient mailbox decryption rejected')


def invitation(community, private, invitation_key, host, port, *, lifetime=3600):
    community._member(sign({}, private, 'test')['public_key'], 'discover')
    onion_address(host)
    if type(port) is not int or not 1 <= port <= 65535 or type(lifetime) is not int or not 1 <= lifetime <= 86400:
        raise ProtocolError('INVALID_INVITATION', 'bounded private invitation endpoint and lifetime required')
    value = sign({'community_id': community.community_id, 'policy': community.policy_id,
                  'host': host, 'port': port, 'expires': int(time.time())+lifetime,
                  'nonce': secrets.token_hex(16)}, private, 'Ziokt/community-invitation/v1')
    raw = encoded(value)
    if len(raw)+32 > 4096: raise ProtocolError('INVALID_INVITATION', 'invitation frame budget')
    nonce = secrets.token_bytes(12)
    plain = struct.pack('!I', len(raw))+raw+secrets.token_bytes(4064-len(raw))
    return nonce+AESGCM(invitation_key).encrypt(nonce, plain, b'Ziokt/community-invitation/v1')


def accept_invitation(community, blob, invitation_key, publisher):
    community._member(publisher, 'discover')
    if not isinstance(blob, bytes) or len(blob) != 4096: raise ProtocolError('INVALID_INVITATION', 'fixed encrypted invitation required')
    try:
        plain = AESGCM(invitation_key).decrypt(blob[:12], blob[12:], b'Ziokt/community-invitation/v1')
        size = struct.unpack('!I', plain[:4])[0]
        if size > len(plain)-4: raise ValueError()
        value = verify(strict_json(plain[4:4+size]), publisher, 'Ziokt/community-invitation/v1')
        exact(value, {'community_id', 'policy', 'host', 'port', 'expires', 'nonce'}, 'INVALID_INVITATION')
        if (value['community_id'] != community.community_id or value['policy'] != community.policy_id or type(value['expires']) is not int or
                not int(time.time()) < value['expires'] <= int(time.time())+86400 or type(value['port']) is not int or not 1 <= value['port'] <= 65535):
            raise ValueError()
        onion_address(value['host'])
        return {'host': value['host'], 'port': value['port'], 'membership_granted': False, 'tls_trust_required': True}
    except (ValueError, TypeError, InvalidTag):
        raise ProtocolError('INVITATION_REJECTED', 'invitation authentication, scope or expiry rejected')

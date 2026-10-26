"""Unified Mail: multi-channel postal service bridging Corium, ETP, and Community.

Addresses bind ZDNS (<local_part>@<domain>). Attachments integrate with
Content Fabric content-addressed objects (cf1-[a-f0-9]{64}). Public relay / forwarding
interfaces are guarded with cryptographic authentication, anti-spam heuristics,
sliding-window rate limiting, and anti-flood protections.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import struct
import threading
import time

from .protocol import ProtocolError, encoded, secure_read, strict_json
from .security import sign, verify
from .naming import split_name, GROUPS, SUFFIXES, Names

MAIL_DOMAIN = 'Ziokt/unified-mail/v1'
RELAY_RECEIPT_DOMAIN = 'Ziokt/mail-relay-receipt/v1'

MAX_SUBJECT_LEN = 256
MAX_BODY_LEN = 65536
MAX_ATTACHMENTS = 4
MAX_ATTACHMENT_SIZE = 16 * 1024 * 1024       # 16 MiB per attachment
MAX_TOTAL_ATTACHMENT_SIZE = 32 * 1024 * 1024 # 32 MiB total attachments
RATE_LIMIT_WINDOW = 60                       # 60-second window
SENDER_RATE_LIMIT = 10                       # Max 10 messages / window per sender
GLOBAL_RATE_LIMIT = 60                       # Max 60 messages / window globally
BURST_THRESHOLD = 5                          # Max 5 rapid messages in <= 2 seconds
TIMESTAMP_TOLERANCE = 300                    # 5-minute freshness window

LOCAL_PART_RE = re.compile(r'^[a-zA-Z0-9_.+-]{1,64}\Z')
HEX64_RE = re.compile(r'^[a-f0-9]{64}\Z')
CF_ID_RE = re.compile(r'^cf1-[a-f0-9]{64}\Z')
SHA256_DIGEST_RE = re.compile(r'^sha256:[a-f0-9]{64}\Z')


def sanitize_filename(name):
    if not isinstance(name, str) or not (1 <= len(name) <= 255):
        raise ProtocolError('INVALID_ATTACHMENT', 'attachment filename length 1..255 required')
    if name in {'.', '..'} or '/' in name or '\\' in name or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ProtocolError('INVALID_ATTACHMENT', 'safe attachment filename required without path traversal')
    return name


def parse_mail_address(address):
    """Parse and validate a ZDNS email address: <local_part>@<domain>."""
    if not isinstance(address, str) or len(address) > 320 or '@' not in address:
        raise ProtocolError('INVALID_ADDRESS', 'valid <user>@<domain> address required')
    local_part, domain = address.split('@', 1)
    if not LOCAL_PART_RE.fullmatch(local_part):
        raise ProtocolError('INVALID_ADDRESS', 'canonical local-part required')
    canonical, authority, root, children = split_name(domain)
    return local_part, canonical, authority, root, children


def resolve_mail_destination(address, names=None, nns_resolver=None):
    """Resolve destination channel and recipient key from a ZDNS address."""
    try:
        local_part, domain, authority, root, children = parse_mail_address(address)
    except (ProtocolError, ValueError):
        from .mail_internet import address as internet_address
        external=internet_address(address)
        # Reserved native authorities must never fall back to an internet relay.
        if external.rsplit('.',1)[-1] in SUFFIXES:
            raise ProtocolError('INVALID_ADDRESS','native mail name cannot downgrade to SMTP')
        return {'schema':'ziokt.mail-destination.v1','address':external,'local_part':external.split('@',1)[0],
                'domain':external.split('@',1)[1],'channel':'internet','authority':'internet','recipient_key':None,'resolved':True}
    channel = 'community'
    if authority in ('corium',):
        channel = 'corium'
    elif authority in ('etp',):
        channel = 'etp'
    elif authority in ('ziokt',):
        channel = 'community'

    recipient_key = None
    if HEX64_RE.fullmatch(local_part.lower()):
        recipient_key = local_part.lower()

    if names is not None:
        try:
            entry = names.resolve(domain)
            if isinstance(entry, dict) and entry.get('owner'):
                recipient_key = entry['owner']
        except Exception:
            pass

    if recipient_key is None and nns_resolver is not None:
        try:
            resolved = nns_resolver(root)
            if isinstance(resolved, dict) and resolved.get('owner'):
                recipient_key = resolved['owner']
        except Exception:
            pass

    return {
        'schema': 'ziokt.mail-destination.v1',
        'address': f"{local_part}@{domain}",
        'local_part': local_part,
        'domain': domain,
        'channel': channel,
        'authority': authority,
        'recipient_key': recipient_key,
        'resolved': True
    }


def validate_attachment(item, cf=None, max_size=MAX_ATTACHMENT_SIZE):
    """Validate a single Content Fabric attachment descriptor."""
    if not isinstance(item, dict) or set(item) - {'id', 'name', 'size', 'digest', 'mime', 'merkle_root', 'v'}:
        raise ProtocolError('INVALID_ATTACHMENT', 'exact attachment descriptor keys required')
    for req in ('id', 'name', 'size', 'digest', 'mime'):
        if req not in item:
            raise ProtocolError('INVALID_ATTACHMENT', f'missing required attachment field: {req}')

    if not isinstance(item['id'], str) or not CF_ID_RE.fullmatch(item['id']):
        raise ProtocolError('INVALID_ATTACHMENT', 'attachment id must be canonical cf1-[a-f0-9]{64}')
    sanitize_filename(item['name'])

    if type(item['size']) is not int or not (0 <= item['size'] <= max_size):
        raise ProtocolError('ATTACHMENT_SIZE_EXCEEDED', f'attachment size exceeds budget ({max_size} bytes)')

    if not isinstance(item['digest'], str) or not SHA256_DIGEST_RE.fullmatch(item['digest']):
        raise ProtocolError('INVALID_ATTACHMENT', 'attachment digest must be sha256:[a-f0-9]{64}')

    if not isinstance(item['mime'], str) or not (1 <= len(item['mime']) <= 128):
        raise ProtocolError('INVALID_ATTACHMENT', 'attachment mime type length 1..128 required')

    if cf is not None:
        try:
            # If ContentFabric instance provided, verify object existence
            oid = item['id']
            cf.object_info(cf.owner if hasattr(cf, 'owner') else 'public', oid)
        except Exception as err:
            raise ProtocolError('CONTENT_FABRIC_UNAVAILABLE', f'referenced Content Fabric object unverified: {err}')

    return item


def validate_attachments(attachments, cf=None):
    """Validate attachment list count, total size, and individual descriptors."""
    if attachments is None:
        return []
    if not isinstance(attachments, list):
        raise ProtocolError('INVALID_ATTACHMENT', 'attachments must be a list')
    if len(attachments) > MAX_ATTACHMENTS:
        raise ProtocolError('ATTACHMENT_LIMIT', f'maximum {MAX_ATTACHMENTS} attachments allowed per mail')

    seen_ids = set()
    total_size = 0
    validated = []
    for att in attachments:
        item = validate_attachment(att, cf=cf)
        if item['id'] in seen_ids:
            raise ProtocolError('INVALID_ATTACHMENT', 'duplicate attachment object ID')
        seen_ids.add(item['id'])
        total_size += item['size']
        if total_size > MAX_TOTAL_ATTACHMENT_SIZE:
            raise ProtocolError('ATTACHMENT_SIZE_EXCEEDED', f'total attachment budget exceeded ({MAX_TOTAL_ATTACHMENT_SIZE} bytes)')
        validated.append(item)
    return validated


class AntiFloodGuard:
    """Sliding-window rate limiter with burst suppression and automatic pruning."""
    def __init__(self, sender_limit=SENDER_RATE_LIMIT, global_limit=GLOBAL_RATE_LIMIT,
                 window_seconds=RATE_LIMIT_WINDOW, burst_threshold=BURST_THRESHOLD):
        self.sender_limit = sender_limit
        self.global_limit = global_limit
        self.window = window_seconds
        self.burst_threshold = burst_threshold
        self.sender_records = {}
        self.global_records = []
        self._lock = threading.Lock()

    def check_rate_limit(self, sender, now=None):
        if now is None:
            now = time.time()
        with self._lock:
            # Prune global
            self.global_records = [t for t in self.global_records if now - t < self.window]
            if len(self.global_records) >= self.global_limit:
                raise ProtocolError('GLOBAL_RATE_LIMITED', 'mail relay global capacity reached; retry later')

            # Prune sender
            records = [t for t in self.sender_records.get(sender, []) if now - t < self.window]
            # Check burst: consecutive messages in <= 2 seconds
            burst_window = 2.0
            recent_burst = [t for t in records if now - t <= burst_window]
            if len(recent_burst) >= self.burst_threshold:
                raise ProtocolError('BURST_LIMIT_EXCEEDED', 'rapid burst sending rate exceeded; throttled')

            if len(records) >= self.sender_limit:
                raise ProtocolError('RATE_LIMITED', f'sender rate limit ({self.sender_limit} msgs/min) exceeded')

            records.append(now)
            self.sender_records[sender] = records
            self.global_records.append(now)

            # Auto-prune inactive senders if map grows large
            if len(self.sender_records) > 2000:
                self.sender_records = {k: v for k, v in self.sender_records.items() if v and now - v[-1] < self.window}


class AntiSpamGuard:
    """Validates message content bounds, freshness, and replay prevention."""
    def __init__(self, tolerance=TIMESTAMP_TOLERANCE, replay_capacity=10000):
        self.tolerance = tolerance
        self.replay_capacity = replay_capacity
        self.seen_messages = set()
        self.seen_queue = []
        self._lock = threading.Lock()

    def validate_content(self, subject, body, attachments=None):
        if not isinstance(subject, str) or not (1 <= len(subject) <= MAX_SUBJECT_LEN):
            raise ProtocolError('INVALID_SUBJECT', f'subject length must be 1..{MAX_SUBJECT_LEN}')
        if any(ord(c) < 32 and c != ' ' for c in subject):
            raise ProtocolError('INVALID_SUBJECT', 'subject contains invalid control characters')

        if not isinstance(body, str) or not (1 <= len(body) <= MAX_BODY_LEN):
            raise ProtocolError('INVALID_BODY', f'body length must be 1..{MAX_BODY_LEN}')

        return validate_attachments(attachments)

    def check_freshness(self, timestamp, now=None):
        if type(timestamp) is not int:
            raise ProtocolError('INVALID_TIMESTAMP', 'integer epoch timestamp required')
        if now is None:
            now = int(time.time())
        if abs(now - timestamp) > self.tolerance:
            raise ProtocolError('TIMESTAMP_OUT_OF_BOUNDS', f'mail timestamp outside acceptable {self.tolerance}s window')

    def check_replay(self, message_id):
        if not isinstance(message_id, str) or not message_id:
            raise ProtocolError('INVALID_MESSAGE_ID', 'unique message identifier required')
        with self._lock:
            if message_id in self.seen_messages:
                raise ProtocolError('REPLAY_DETECTED', 'message identifier already processed; replay rejected')
            self.seen_messages.add(message_id)
            self.seen_queue.append(message_id)
            if len(self.seen_queue) > self.replay_capacity:
                old = self.seen_queue.pop(0)
                self.seen_messages.discard(old)


class CoriumMailChannel:
    """Mail transport channel integrating with Corium forum.db / mails table."""
    def __init__(self, forum_db=None, objects_dir=None):
        self.forum_db = Path(forum_db) if forum_db else None
        self.objects_dir = Path(objects_dir) if objects_dir else None
        if self.forum_db:
            self._ensure_schema()
        if self.objects_dir:
            self.objects_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_schema(self):
        self.forum_db.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.forum_db)) as conn:
            with conn as db:
                db.execute('''
                    CREATE TABLE IF NOT EXISTS mails (
                        tx_hash TEXT PRIMARY KEY,
                        recipient_id TEXT NOT NULL,
                        mail_object_hash TEXT NOT NULL,
                        local_path TEXT,
                        timestamp INTEGER
                    )
                ''')
                db.execute('CREATE INDEX IF NOT EXISTS idx_mails_recipient ON mails(recipient_id, timestamp)')

    def send(self, sender_key, recipient_id, subject, body, attachments=None, timestamp=None):
        validated_attachments = validate_attachments(attachments)
        ts = timestamp if timestamp is not None else int(time.time())
        payload = {
            'schema': 'ziokt.corium-mail.v1',
            'sender': sender_key,
            'recipient': recipient_id,
            'subject': subject,
            'body': body,
            'attachments': validated_attachments,
            'timestamp': ts
        }
        encoded_payload = encoded(payload)
        object_hash = 'sha256:' + hashlib.sha256(encoded_payload).hexdigest()
        tx_hash = hashlib.sha256((sender_key + recipient_id + str(ts) + object_hash).encode()).hexdigest()

        local_path = ''
        if self.objects_dir:
            obj_path = self.objects_dir / object_hash.replace(':', '_')
            obj_path.write_bytes(encoded_payload)
            local_path = str(obj_path)

        if self.forum_db:
            with closing(sqlite3.connect(self.forum_db)) as conn:
                with conn as db:
                    db.execute(
                        'INSERT OR REPLACE INTO mails (tx_hash, recipient_id, mail_object_hash, local_path, timestamp) VALUES (?, ?, ?, ?, ?)',
                        (tx_hash, recipient_id, object_hash, local_path, ts)
                    )

        return {
            'tx_hash': tx_hash,
            'mail_object_hash': object_hash,
            'local_path': local_path,
            'channel': 'corium',
            'payload': payload
        }

    def inbox(self, recipient_id, limit=50):
        if not self.forum_db or not self.forum_db.exists():
            return []
        with closing(sqlite3.connect(self.forum_db)) as conn:
            rows = conn.execute(
                'SELECT tx_hash, recipient_id, mail_object_hash, local_path, timestamp FROM mails WHERE recipient_id = ? ORDER BY timestamp DESC LIMIT ?',
                (recipient_id, limit)
            ).fetchall()
        results = []
        for row in rows:
            tx_hash, r_id, obj_hash, l_path, ts = row
            item = {
                'tx_hash': tx_hash,
                'recipient_id': r_id,
                'mail_object_hash': obj_hash,
                'local_path': l_path,
                'timestamp': ts
            }
            if l_path and Path(l_path).exists():
                try:
                    item['content'] = strict_json(Path(l_path).read_bytes())
                except Exception:
                    pass
            results.append(item)
        return results

    def read(self, tx_hash):
        if not self.forum_db or not self.forum_db.exists():
            raise ProtocolError('MAIL_NOT_FOUND', 'Corium forum database unavailable')
        with closing(sqlite3.connect(self.forum_db)) as conn:
            row = conn.execute(
                'SELECT tx_hash, recipient_id, mail_object_hash, local_path, timestamp FROM mails WHERE tx_hash = ?',
                (tx_hash,)
            ).fetchone()
        if not row:
            raise ProtocolError('MAIL_NOT_FOUND', f'no mail found with tx_hash {tx_hash}')
        tx_hash, r_id, obj_hash, l_path, ts = row
        item = {
            'tx_hash': tx_hash,
            'recipient_id': r_id,
            'mail_object_hash': obj_hash,
            'local_path': l_path,
            'timestamp': ts
        }
        if l_path and Path(l_path).exists():
            item['content'] = strict_json(Path(l_path).read_bytes())
        return item


class ETPMailChannel:
    """Mail transport channel integrating with ETP mailbox v2 frames."""
    def __init__(self, etp_service=None, mailbox_store_dir=None):
        self.etp_service = etp_service
        self.mailbox_store_dir = Path(mailbox_store_dir) if mailbox_store_dir else None
        if self.mailbox_store_dir:
            self.mailbox_store_dir.mkdir(parents=True, exist_ok=True)

    def send(self, sender_key, recipient_key, subject, body, attachments=None, timestamp=None):
        validated_attachments = validate_attachments(attachments)
        ts = timestamp if timestamp is not None else int(time.time())
        payload = {
            'schema': 'ziokt.etp-mail.v1',
            'sender': sender_key,
            'recipient': recipient_key,
            'subject': subject,
            'body': body,
            'attachments': validated_attachments,
            'timestamp': ts
        }
        raw_payload = encoded(payload)
        # Format ETP mailbox v2 frame: [version=2, opcode=1 (deliver), recipient_len (1B), recipient, payload]
        recipient_bytes = recipient_key.encode('utf-8')
        if len(recipient_bytes) > 255:
            raise ProtocolError('INVALID_ETP_MAIL', 'recipient key exceeds byte budget')
        frame = bytearray([2, 1, len(recipient_bytes)]) + recipient_bytes + raw_payload
        message_id = hashlib.sha256(frame).hexdigest()

        if self.mailbox_store_dir:
            box_file = self.mailbox_store_dir / f"{recipient_key}.mailbox"
            with open(box_file, 'ab') as f:
                f.write(struct.pack('!I', len(frame)) + frame)

        if self.etp_service and hasattr(self.etp_service, 'mailbox_request'):
            import base64
            self.etp_service.mailbox_request(base64.b64encode(frame).decode())

        return {
            'message_id': message_id,
            'channel': 'etp',
            'frame_len': len(frame),
            'payload': payload
        }

    def inbox(self, recipient_key):
        if not self.mailbox_store_dir:
            return []
        box_file = self.mailbox_store_dir / f"{recipient_key}.mailbox"
        if not box_file.exists():
            return []
        items = []
        data = box_file.read_bytes()
        offset = 0
        while offset + 4 <= len(data):
            frame_len = struct.unpack('!I', data[offset:offset+4])[0]
            offset += 4
            if offset + frame_len > len(data):
                break
            frame = data[offset:offset+frame_len]
            offset += frame_len
            if len(frame) >= 3 and frame[0] == 2 and frame[1] == 1:
                r_len = frame[2]
                r_key = frame[3:3+r_len].decode('utf-8', errors='ignore')
                raw_payload = frame[3+r_len:]
                try:
                    payload = strict_json(raw_payload)
                    items.append({
                        'recipient': r_key,
                        'message_id': hashlib.sha256(frame).hexdigest(),
                        'payload': payload
                    })
                except Exception:
                    pass
        return items


class CommunityMailChannel:
    """Mail transport channel integrating with native Ziokt Community mailboxes."""
    def __init__(self, community=None, mailbox_key=None, mailbox_db=None):
        self.community = community
        self.mailbox_key = mailbox_key
        self.mailbox_db = Path(mailbox_db) if mailbox_db else None
        if self.mailbox_db:
            self._ensure_schema()

    def _ensure_schema(self):
        self.mailbox_db.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.mailbox_db)) as conn:
            with conn as db:
                db.execute('''
                    CREATE TABLE IF NOT EXISTS community_mailbox (
                        message_id TEXT PRIMARY KEY,
                        sender TEXT NOT NULL,
                        recipient TEXT NOT NULL,
                        subject TEXT NOT NULL,
                        body TEXT NOT NULL,
                        sealed TEXT,
                        attachments TEXT,
                        timestamp INTEGER NOT NULL,
                        delivery_status TEXT NOT NULL,
                        receipt TEXT
                    )
                ''')
                db.execute('CREATE INDEX IF NOT EXISTS idx_comm_recip ON community_mailbox(recipient, timestamp)')

    def send(self, sender_key, recipient, recipient_mailbox_key=None, subject="", body="", attachments=None, timestamp=None):
        from .community_privacy import seal_mail
        validated_attachments = validate_attachments(attachments)
        ts = timestamp if timestamp is not None else int(time.time())
        text_with_meta = body
        if validated_attachments:
            text_with_meta += "\n--- Content Fabric Attachments ---\n" + json.dumps(validated_attachments)

        sealed = None
        if recipient_mailbox_key and len(recipient_mailbox_key) == 64:
            try:
                sealed = seal_mail(recipient, recipient_mailbox_key, subject, text_with_meta)
            except Exception:
                sealed = None

        message_id = hashlib.sha256(encoded({'sender':sender_key,'recipient':recipient,'timestamp':ts,
                                             'subject':subject,'body':body,'attachments':validated_attachments})).hexdigest()

        if self.mailbox_db:
            with closing(sqlite3.connect(self.mailbox_db)) as conn:
                with conn as db:
                    db.execute('''
                        INSERT OR REPLACE INTO community_mailbox
                        (message_id, sender, recipient, subject, body, sealed, attachments, timestamp, delivery_status, receipt)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        message_id,
                        sender_key,
                        recipient,
                        subject,
                        body,
                        json.dumps(sealed) if sealed else None,
                        json.dumps(validated_attachments),
                        ts,
                        'delivered',
                        json.dumps({'message_id': message_id, 'delivered_at': ts})
                    ))

        return {
            'channel': 'community',
            'message_id': message_id,
            'recipient': recipient,
            'sender': sender_key,
            'subject': subject,
            'delivery_status': 'delivered',
            'sealed': sealed,
            'attachments': validated_attachments,
            'timestamp': ts
        }

    def inbox(self, recipient_id, limit=50):
        if not self.mailbox_db or not self.mailbox_db.exists():
            return []
        with closing(sqlite3.connect(self.mailbox_db)) as conn:
            rows = conn.execute(
                'SELECT message_id, sender, recipient, subject, body, sealed, attachments, timestamp, delivery_status FROM community_mailbox WHERE recipient = ? OR recipient LIKE ? ORDER BY timestamp DESC LIMIT ?',
                (recipient_id, f"{recipient_id}@%", limit)
            ).fetchall()
        results = []
        for r in rows:
            m_id, snd, rcp, sub, bdy, sld, atts, ts, st = r
            results.append({
                'message_id': m_id,
                'channel': 'community',
                'sender': snd,
                'recipient': rcp,
                'subject': sub,
                'body': bdy,
                'sealed': json.loads(sld) if sld else None,
                'attachments': json.loads(atts) if atts else [],
                'timestamp': ts,
                'delivery_status': st
            })
        return results

    def read(self, message_id):
        if not self.mailbox_db or not self.mailbox_db.exists():
            raise ProtocolError('MAIL_NOT_FOUND', 'Community mailbox database unavailable')
        with closing(sqlite3.connect(self.mailbox_db)) as conn:
            row = conn.execute(
                'SELECT message_id, sender, recipient, subject, body, sealed, attachments, timestamp, delivery_status FROM community_mailbox WHERE message_id = ?',
                (message_id,)
            ).fetchone()
        if not row:
            raise ProtocolError('MAIL_NOT_FOUND', f'no community mail found with id {message_id}')
        m_id, snd, rcp, sub, bdy, sld, atts, ts, st = row
        return {
            'message_id': m_id,
            'channel': 'community',
            'sender': snd,
            'recipient': rcp,
            'subject': sub,
            'body': bdy,
            'sealed': json.loads(sld) if sld else None,
            'attachments': json.loads(atts) if atts else [],
            'timestamp': ts,
            'delivery_status': st
        }

    def open(self, private_mailbox_key, recipient, sealed_body):
        from .community_privacy import open_mail
        return open_mail(private_mailbox_key, recipient, sealed_body)


class MailRelay:
    """Public relay / forwarding engine equipped with authentication, anti-spam, and anti-flood."""
    def __init__(self, node_id, signing_key=None, names=None, corium_channel=None,
                 etp_channel=None, community_channel=None, content_fabric=None, relay_db=None, internet_channel=None):
        self.node_id = node_id
        self.signing_key = signing_key
        self.names = names
        self.corium_channel = corium_channel or CoriumMailChannel()
        self.etp_channel = etp_channel or ETPMailChannel()
        self.community_channel = community_channel or CommunityMailChannel()
        self.cf = content_fabric
        self.internet_channel = internet_channel
        self.relay_db = Path(relay_db) if relay_db else None
        if self.relay_db:
            self._ensure_schema()
        self.anti_flood = AntiFloodGuard()
        self.anti_spam = AntiSpamGuard()

    def _ensure_schema(self):
        self.relay_db.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.relay_db)) as conn:
            with conn as db:
                db.execute('''
                    CREATE TABLE IF NOT EXISTS delivery_log (
                        message_id TEXT PRIMARY KEY,
                        envelope BLOB NOT NULL,
                        sender TEXT NOT NULL,
                        recipient TEXT NOT NULL,
                        channel TEXT NOT NULL,
                        status TEXT NOT NULL,
                        attempts INTEGER NOT NULL,
                        last_attempt INTEGER NOT NULL,
                        receipt BLOB,
                        error TEXT NOT NULL DEFAULT ''
                    )
                ''')
                db.execute('CREATE INDEX IF NOT EXISTS idx_delivery_status ON delivery_log(status, last_attempt)')

    def forward(self, envelope, *, _retry=False):
        """Relay a signed mail envelope with authentication, anti-flood, and anti-spam verification."""
        if not isinstance(envelope, dict):
            raise ProtocolError('INVALID_ENVELOPE', 'dictionary mail envelope required')

        sender_public = envelope.get('public_key')
        if not isinstance(sender_public, str) or not HEX64_RE.fullmatch(sender_public):
            raise ProtocolError('AUTH_REQUIRED', 'canonical ed25519 sender public key required')

        # 1. Anti-flood & rate limiting
        self.anti_flood.check_rate_limit(sender_public)

        # 2. Cryptographic authentication: verify sender signature over envelope payload
        payload = verify(envelope, sender_public, MAIL_DOMAIN)
        if not isinstance(payload, dict):
            raise ProtocolError('INVALID_PAYLOAD', 'dictionary mail payload required')

        for field in ('id', 'from', 'to', 'subject', 'body', 'timestamp'):
            if field not in payload:
                raise ProtocolError('INVALID_PAYLOAD', f'missing required payload field: {field}')

        persisted=None
        if self.relay_db:
            with closing(sqlite3.connect(self.relay_db)) as db:
                persisted=db.execute('SELECT envelope,receipt,status,attempts FROM delivery_log WHERE message_id=?',(payload['id'],)).fetchone()
        if persisted:
            if bytes(persisted[0])!=encoded(envelope):raise ProtocolError('REPLAY_DETECTED','mail identifier reused with different content')
            if not _retry:return strict_json(persisted[1]) if persisted[1] else {'message_id':payload['id'],'status':'pending'}
            if persisted[2] not in {'failed','pending'} or persisted[3]>=5:raise ProtocolError('REPLAY_DETECTED','delivery cannot be retried')
        elif _retry:raise ProtocolError('REPLAY_DETECTED','retry requires a durable previously accepted envelope')

        # 3. Anti-spam checks: content bounds, freshness, replay deduplication
        validated_attachments = self.anti_spam.validate_content(payload['subject'], payload['body'], payload.get('attachments'))
        if not _retry:
            self.anti_spam.check_freshness(payload['timestamp'])
            self.anti_spam.check_replay(payload['id'])

        # 4. ZDNS Address resolution
        dest = resolve_mail_destination(payload['to'], names=self.names)
        channel = dest['channel']

        # 5. Route to target channel
        channel_result = None
        delivery_status = 'relayed'
        delivery_error = ''
        try:
            if channel == 'internet':
                if self.internet_channel is None:raise ProtocolError('MAIL_UNAVAILABLE','internet mail is not configured')
                channel_result=self.internet_channel.send(sender_public,payload['to'],payload['subject'],payload['body'],validated_attachments,payload['timestamp'],message_id=payload['id'])
                delivery_status='queued'
            elif channel == 'corium':
                channel_result = self.corium_channel.send(
                    sender_key=sender_public,
                    recipient_id=dest['recipient_key'] or dest['local_part'],
                    subject=payload['subject'],
                    body=payload['body'],
                    attachments=validated_attachments,
                    timestamp=payload['timestamp']
                )
            elif channel == 'etp':
                channel_result = self.etp_channel.send(
                    sender_key=sender_public,
                    recipient_key=dest['recipient_key'] or dest['local_part'],
                    subject=payload['subject'],
                    body=payload['body'],
                    attachments=validated_attachments,
                    timestamp=payload['timestamp']
                )
            else:
                channel_result = self.community_channel.send(
                    sender_key=sender_public,
                    recipient=dest['recipient_key'] or dest['local_part'],
                    recipient_mailbox_key=dest.get('recipient_key'),
                    subject=payload['subject'],
                    body=payload['body'],
                    attachments=validated_attachments,
                    timestamp=payload['timestamp']
                )
            if delivery_status != 'queued':delivery_status = 'delivered'
        except Exception as exc:
            delivery_status = 'failed'
            delivery_error = str(exc)
            channel_result = {'error': delivery_error, 'channel': channel}

        # 6. Issue relay receipt
        receipt = {
            'schema': 'ziokt.mail-relay-receipt.v1',
            'message_id': payload['id'],
            'sender': payload['from'],
            'recipient': payload['to'],
            'channel': channel,
            'relay_node': self.node_id,
            'relayed_at': int(time.time()),
            'status': 'queued' if delivery_status == 'queued' else 'relayed' if delivery_status != 'failed' else 'failed',
            'error': delivery_error if delivery_status == 'failed' else None,
            'details': channel_result
        }

        signed_receipt = sign(receipt, self.signing_key, RELAY_RECEIPT_DOMAIN) if self.signing_key else receipt

        if self.relay_db:
            with closing(sqlite3.connect(self.relay_db)) as conn:
                with conn as db:
                    db.execute('''
                        INSERT OR REPLACE INTO delivery_log
                        (message_id, envelope, sender, recipient, channel, status, attempts, last_attempt, receipt, error)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        payload['id'],
                        encoded(envelope),
                        payload['from'],
                        payload['to'],
                        channel,
                        delivery_status,
                        1,
                        int(time.time()),
                        encoded(signed_receipt),
                        delivery_error
                    ))

        return signed_receipt

    def retry_failed(self, limit=10):
        if not self.relay_db or not self.relay_db.exists():
            return {'retried_count': 0, 'succeeded': 0, 'failed': 0, 'results': []}
        with closing(sqlite3.connect(self.relay_db)) as conn:
            rows = conn.execute(
                "SELECT message_id, envelope, attempts FROM delivery_log WHERE status IN ('pending', 'failed') AND attempts < 5 ORDER BY last_attempt ASC LIMIT ?",
                (limit,)
            ).fetchall()
        retried = 0
        succeeded = 0
        failed = 0
        results = []
        for msg_id, raw_env, attempts in rows:
            retried += 1
            now = int(time.time())
            try:
                env = strict_json(raw_env)
                with self.anti_spam._lock:
                    self.anti_spam.seen_messages.discard(msg_id)
                receipt = self.forward(env,_retry=True)
                with closing(sqlite3.connect(self.relay_db)) as conn:
                    with conn as db:db.execute('UPDATE delivery_log SET attempts=? WHERE message_id=?',(attempts+1,msg_id))
                st = receipt.get('payload', {}).get('status') if 'payload' in receipt else receipt.get('status', 'relayed')
                if st in ('relayed', 'delivered', 'queued'):
                    succeeded += 1
                else:
                    failed += 1
                results.append({'message_id': msg_id, 'status': st, 'attempts': attempts + 1})
            except Exception as exc:
                failed += 1
                with closing(sqlite3.connect(self.relay_db)) as conn:
                    with conn as db:
                        db.execute(
                            "UPDATE delivery_log SET attempts = attempts + 1, last_attempt = ?, status = 'failed', error = ? WHERE message_id = ?",
                            (now, str(exc), msg_id)
                        )
                results.append({'message_id': msg_id, 'status': 'failed', 'error': str(exc), 'attempts': attempts + 1})
        return {'retried_count': retried, 'succeeded': succeeded, 'failed': failed, 'results': results}

    def delivery_receipt(self, message_id):
        if not self.relay_db or not self.relay_db.exists():
            raise ProtocolError('RECEIPT_NOT_FOUND', 'no relay database configured')
        with closing(sqlite3.connect(self.relay_db)) as conn:
            row = conn.execute(
                'SELECT message_id, sender, recipient, channel, status, attempts, last_attempt, receipt, error FROM delivery_log WHERE message_id = ?',
                (message_id,)
            ).fetchone()
        if not row:
            raise ProtocolError('RECEIPT_NOT_FOUND', f'no receipt for message {message_id}')
        m_id, snd, rcp, chn, st, att, l_att, rcpt, err = row
        return {
            'message_id': m_id,
            'sender': snd,
            'recipient': rcp,
            'channel': chn,
            'status': st,
            'attempts': att,
            'last_attempt': l_att,
            'receipt': strict_json(rcpt) if rcpt else None,
            'error': err or None
        }


class UnifiedMail:
    """Top-level unified mail coordinator bridging all channels and relay services."""
    def __init__(self, node_id="node-unified-mail", signing_key=None, names=None,
                 corium_channel=None, etp_channel=None, community_channel=None, content_fabric=None,
                 mailbox_db=None, relay_db=None, internet_channel=None):
        self.node_id = node_id
        self.signing_key = signing_key
        self.names = names
        self.corium_channel = corium_channel or CoriumMailChannel()
        self.etp_channel = etp_channel or ETPMailChannel()
        self.community_channel = community_channel or CommunityMailChannel(mailbox_db=mailbox_db)
        self.cf = content_fabric
        self.internet_channel = internet_channel
        self.relay = MailRelay(
            node_id=node_id,
            signing_key=signing_key,
            names=names,
            corium_channel=self.corium_channel,
            etp_channel=self.etp_channel,
            community_channel=self.community_channel,
            content_fabric=content_fabric,
            relay_db=relay_db,
            internet_channel=internet_channel
        )

    def resolve(self, address):
        return resolve_mail_destination(address, names=self.names)

    @classmethod
    def configured(cls, config):
        root=Path(config['state']);root.mkdir(parents=True,mode=0o700,exist_ok=True)
        from .package_storage import safe_path
        from .mail_internet import InternetMail
        internet=InternetMail(config['internet'],config.get('internet_state',root/'internet')) if config.get('internet') else None
        return cls(node_id=config.get('node_id','local-mail'),
                   corium_channel=CoriumMailChannel(safe_path(root,'corium.db'),safe_path(root,'objects')),
                   etp_channel=ETPMailChannel(mailbox_store_dir=safe_path(root,'etp')),
                   mailbox_db=safe_path(root,'community.db'),relay_db=safe_path(root,'relay.db'),internet_channel=internet)

    def create_envelope(self, sender_private_key, from_address, to_address, subject, body, attachments=None, timestamp=None):
        """Construct and sign an envelope ready for relay forwarding."""
        msg_id = secrets.token_hex(16)
        ts = timestamp if timestamp is not None else int(time.time())
        validated_attachments = validate_attachments(attachments, cf=self.cf)
        payload = {
            'id': msg_id,
            'from': from_address,
            'to': to_address,
            'subject': subject,
            'body': body,
            'attachments': validated_attachments,
            'timestamp': ts
        }
        return sign(payload, sender_private_key, MAIL_DOMAIN)

    def send(self, sender_private_key, from_address, to_address, subject, body, attachments=None):
        """Send a mail by creating a signed envelope and passing through relay."""
        envelope = self.create_envelope(sender_private_key, from_address, to_address, subject, body, attachments)
        return self.relay.forward(envelope)

    def inbox(self, recipient_id, channel=None):
        """Fetch inbox records across Corium, ETP, and Community channels."""
        results = {}
        if channel in (None, 'corium'):
            results['corium'] = self.corium_channel.inbox(recipient_id)
        if channel in (None, 'etp'):
            results['etp'] = self.etp_channel.inbox(recipient_id)
        if channel in (None, 'community'):
            results['community'] = self.community_channel.inbox(recipient_id)
        if channel in (None,'internet') and self.internet_channel:
            results['internet']=self.internet_channel.inbox(recipient_id)
        return results

    def read_corium(self, tx_hash):
        return self.corium_channel.read(tx_hash)

    def read_community(self, message_id):
        return self.community_channel.read(message_id)

    def retry_failed(self, limit=10):
        return self.relay.retry_failed(limit=limit)

    def delivery_receipt(self, message_id):
        return self.relay.delivery_receipt(message_id)


def execute_mail_cli(args):
    """CLI dispatcher for `ziokt mail` subcommands."""
    action = getattr(args, 'mail_action', None)
    config=getattr(args,'config',None)
    if config:
        unified=UnifiedMail.configured(strict_json(secure_read(config,65536)))
    else:
        unified=UnifiedMail.configured({'state':str(Path.home()/'.local/share/ziokt/mail')})
    if action=='send':
        result=unified.send(secure_read(args.key,32),args.from_address,args.to,args.subject,secure_read(args.body_file,65536,private=None).decode())
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if action=='internet-resolve':
        if not unified.internet_channel:raise ProtocolError('MAIL_UNAVAILABLE','configure an internet mail account first')
        print(json.dumps(unified.internet_channel.resolve(args.message_id,args.decision)));return
    if action in {'internet-flush','internet-poll','internet-status'}:
        if not unified.internet_channel:raise ProtocolError('MAIL_UNAVAILABLE','configure an internet mail account first')
        operation={'internet-flush':unified.internet_channel.flush,'internet-poll':unified.internet_channel.poll,'internet-status':unified.internet_channel.status}[action]
        print(json.dumps(operation() if action=='internet-status' else operation(args.limit),ensure_ascii=False,indent=2));return
    if action == 'resolve':
        res = unified.resolve(args.address)
        print(json.dumps(res, indent=2))
        return 0
    elif action == 'inbox':
        res = unified.inbox(args.recipient, channel=getattr(args, 'channel', None))
        print(json.dumps(res, indent=2))
        return 0
    elif action == 'read':
        channel = getattr(args, 'channel', 'corium')
        if channel == 'community':
            res = unified.read_community(args.tx_hash)
        else:
            res = unified.read_corium(args.tx_hash)
        print(json.dumps(res, indent=2))
        return 0
    elif action == 'relay':
        envelope_data = secure_read(args.envelope)
        envelope = strict_json(envelope_data)
        receipt = unified.relay.forward(envelope)
        print(json.dumps(receipt, indent=2))
        return 0
    elif action == 'retry':
        res = unified.retry_failed(limit=getattr(args, 'limit', 10))
        print(json.dumps(res, indent=2))
        return 0
    elif action == 'receipt':
        res = unified.delivery_receipt(args.message_id)
        print(json.dumps(res, indent=2))
        return 0
    else:
        raise ProtocolError('ACTION_REQUIRED', f'unknown mail action {action}')

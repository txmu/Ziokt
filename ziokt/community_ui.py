"""Local authenticated browser portal; no remote plaintext publication or scripts."""
import base64
import hmac
import http.server
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit, parse_qs

from .community import DOMAINS, MAX_FILE, exact
from .protocol import ProtocolError, encoded, strict_json
from .security import sign


def portal_server(community, private, *, port=0, mailbox=None, peer=None, peer_context=None, publisher=None):
    if type(port) is not int or not 0 <= port <= 65535:
        raise ProtocolError('INVALID_CONFIG', 'bounded local portal port required')
    token = secrets.token_urlsafe(32)
    if any(v is not None for v in (peer, peer_context, publisher)) and not all(v is not None for v in (peer, peer_context, publisher)):
        raise ProtocolError('INVALID_CONFIG', 'complete fixed peer, TLS context and publisher required')
    public = sign({}, private, 'test')['public_key']
    if public not in community.policy['members']:
        raise ProtocolError('POLICY_DENIED', 'portal signer is not a community member')
    assets = Path(__file__).parent/'web'
    class Handler(http.server.BaseHTTPRequestHandler):
        def setup(self): super().setup(); self.connection.settimeout(10)
        def log_message(self, *_): pass
        def reply(self, status, data, kind='application/json'):
            if not isinstance(data, bytes): data = encoded(data)
            self.send_response_only(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.send_header('Connection', 'close'); self.end_headers(); self.wfile.write(data)
        def authorize(self):
            origin = 'http://127.0.0.1:'+str(self.server.server_port)
            if self.headers.get('Host') != origin[7:] or self.headers.get('Origin') not in {None, origin}:
                raise ProtocolError('POLICY_DENIED', 'local origin required')
            if len(self.headers.get_all('Authorization', [])) != 1 or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+token):
                raise ProtocolError('POLICY_DENIED', 'local browser session required')
            community._current()
        def do_GET(self):
            try:
                parsed = urlsplit(self.path)
                mapping = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/app.css': ('app.css', 'text/css; charset=utf-8')}
                if parsed.path in mapping:
                    name, kind = mapping[parsed.path]; self.reply(200, (assets/name).read_bytes(), kind); return
                self.authorize()
                if parsed.path == '/api/status':
                    from .community_privacy import mailbox_public
                    self.reply(200, {'community_id': community.community_id, 'privacy': community.policy['privacy'],
                        'rights': community.policy['members'][public], 'public_key': public, 'mailbox': mailbox is not None,
                        'mailbox_public': mailbox_public(mailbox) if mailbox is not None else None,
                        'network_sync_available': peer is not None}); return
                if parsed.path == '/api/view':
                    params = parse_qs(parsed.query)
                    if set(params) != {'domain'} or len(params['domain']) != 1: raise ProtocolError('INVALID_REQUEST', 'one application domain required')
                    self.reply(200, community.view(params['domain'][0])); return
                raise ProtocolError('INVALID_REQUEST', 'unknown local page')
            except (ProtocolError, ValueError, OSError) as exc:
                self.reply(403, {'error': getattr(exc, 'code', 'PORTAL_ERROR')})
        def do_POST(self):
            try:
                self.authorize()
                if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                    raise ProtocolError('INVALID_REQUEST', 'exact bounded request body required')
                size = int(self.headers.get('Content-Length', '0'))
                if self.path == '/api/file-upload':
                    if self.headers.get('Content-Type') != 'application/octet-stream' or not 0 <= size <= MAX_FILE:
                        raise ProtocolError('INVALID_REQUEST', 'bounded binary upload required')
                    self.reply(200, community.put_file(self.rfile.read(size))); return
                if not 1 <= size <= 65536: raise ProtocolError('INVALID_REQUEST', 'portal request budget exceeded')
                if self.headers.get('Content-Type') != 'application/json': raise ProtocolError('INVALID_REQUEST', 'JSON portal request required')
                value = strict_json(self.rfile.read(size))
                if self.path == '/api/sync':
                    exact(value, set())
                    if peer is None: raise ProtocolError('NO_POLICY_COMPLIANT_PATH', 'no explicitly configured community peer')
                    from .community_network import sync_remote
                    self.reply(200, sync_remote(community, peer, peer_context, private, publisher=publisher)); return
                if self.path == '/api/publish':
                    exact(value, {'domain', 'key', 'body', 'parents', 'deleted'})
                    self.reply(200, {'event': community.publish(private, value['domain'], value['key'], value['body'], parents=value['parents'], deleted=value['deleted'])}); return
                if self.path == '/api/mail-send':
                    from .community_privacy import seal_mail
                    exact(value, {'recipient', 'mailbox', 'subject', 'text', 'key'})
                    body = seal_mail(value['recipient'], value['mailbox'] or community.mailbox_for(value['recipient']), value['subject'], value['text'])
                    self.reply(200, {'event': community.publish(private, 'mail', value['key'], body)}); return
                if self.path == '/api/mail-open':
                    from .community_privacy import open_mail
                    if mailbox is None: raise ProtocolError('POLICY_DENIED', 'local mailbox key unavailable')
                    self.reply(200, open_mail(mailbox, public, value)); return
                if self.path == '/api/file-put':
                    exact(value, {'data_base64'})
                    data = base64.b64decode(value['data_base64'], validate=True)
                    self.reply(200, community.put_file(data)); return
                if self.path == '/api/file-get':
                    self.reply(200, community.get_file(value), 'application/octet-stream'); return
                if self.path == '/api/checkpoint':
                    exact(value, set())
                    self.reply(200, community.checkpoint(private), 'application/octet-stream'); return
                raise ProtocolError('INVALID_REQUEST', 'unknown local action')
            except (ProtocolError, ValueError, OSError, TypeError, KeyError) as exc:
                self.reply(403, {'error': getattr(exc, 'code', 'PORTAL_ERROR')})
    class Server(http.server.ThreadingHTTPServer):
        daemon_threads = True
        slots = threading.BoundedSemaphore(16)
        def process_request(self, request, address):
            if not self.slots.acquire(False): self.shutdown_request(request); return
            super().process_request(request, address)
        def process_request_thread(self, request, address):
            try: super().process_request_thread(request, address)
            finally: self.slots.release()
        def handle_error(self, *_): pass
    return Server(('127.0.0.1', port), Handler), token

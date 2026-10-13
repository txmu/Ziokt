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


def portal_server(community, private, *, port=0, mailbox=None, peer=None, peer_context=None, publisher=None,
                  registration_config=None):
    if type(port) is not int or not 0 <= port <= 65535:
        raise ProtocolError('INVALID_CONFIG', 'bounded local portal port required')
    token = secrets.token_urlsafe(32)
    if any(v is not None for v in (peer, peer_context, publisher)) and not all(v is not None for v in (peer, peer_context, publisher)):
        raise ProtocolError('INVALID_CONFIG', 'complete fixed peer, TLS context and publisher required')
    public = sign({}, private, 'test')['public_key']
    if public not in community.policy['members']:
        raise ProtocolError('POLICY_DENIED', 'portal signer is not a community member')
    registration = None
    if community.policy.get('registration', {}).get('required'):
        if registration_config is None:
            raise ProtocolError('INVALID_CONFIG', 'required registration needs the local federation config')
    if registration_config is not None:
        from .registration import RegistrationGate
        registration = RegistrationGate(community, registration_config)
    assets = Path(__file__).parent/'web'
    class Handler(http.server.BaseHTTPRequestHandler):
        def setup(self): super().setup(); self.connection.settimeout(10)
        def log_message(self, *_): pass
        def reply(self, status, data, kind='application/json', csp=None, set_cookie=False):
            if not isinstance(data, bytes): data = encoded(data)
            self.send_response_only(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            default_csp = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            self.send_header('Content-Security-Policy', csp or default_csp)
            if set_cookie:
                self.send_header('Set-Cookie', f'ziokt_session={token}; SameSite=Strict; HttpOnly; Path=/')
            self.send_header('Connection', 'close'); self.end_headers(); self.wfile.write(data)
        def authorize(self, allow_unregistered=False, request_token=None):
            origin = 'http://127.0.0.1:'+str(self.server.server_port)
            if self.headers.get('Host') != origin[7:] or self.headers.get('Origin') not in {None, origin}:
                raise ProtocolError('POLICY_DENIED', 'local origin required')
            auth_header = self.headers.get('Authorization', '')
            cookie_header = self.headers.get('Cookie', '')
            cookie_token = None
            if cookie_header:
                for part in cookie_header.split(';'):
                    if '=' in part:
                        k, v = part.strip().split('=', 1)
                        if k == 'ziokt_session':
                            cookie_token = v
                            break
            authorized = False
            if auth_header and hmac.compare_digest(auth_header, 'Bearer '+token):
                authorized = True
            elif cookie_token and hmac.compare_digest(cookie_token, token):
                authorized = True
            elif request_token and hmac.compare_digest(request_token, token):
                authorized = True
            if not authorized:
                raise ProtocolError('POLICY_DENIED', 'local browser session required')
            community._current()
            if registration is not None and not allow_unregistered:
                registration.require(public)
        def registration_state(self):
            if registration is None:
                return {'required': False, 'registered': True, 'state': '未启用材料登记'}
            return {'required': registration.policy['required'], **registration.status(public)}
        def do_GET(self):
            try:
                parsed = urlsplit(self.path)
                mapping = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/app.css': ('app.css', 'text/css; charset=utf-8')}
                if parsed.path in mapping:
                    name, kind = mapping[parsed.path]; self.reply(200, (assets/name).read_bytes(), kind); return
                if parsed.path.startswith('/site/'):
                    site_tail = parsed.path[len('/site/'):]
                    if not site_tail or '/' not in site_tail:
                        target = f'/site/{site_tail}/' if site_tail else '/'
                        if parsed.query: target += f'?{parsed.query}'
                        self.send_response_only(302)
                        self.send_header('Location', target)
                        self.send_header('Connection', 'close')
                        self.end_headers()
                        return
                    query_token = parse_qs(parsed.query).get('token', [None])[0]
                    self.authorize(request_token=query_token)
                    site_name, subpath = site_tail.split('/', 1)
                    from .community_site import load_site_file
                    res = load_site_file(community, site_name, subpath)
                    site_csp = "default-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
                    self.reply(200, res['content'], kind=res['content_type'], csp=site_csp, set_cookie=True); return
                self.authorize(allow_unregistered=parsed.path == '/api/status')
                if parsed.path == '/api/status':
                    from .community_privacy import mailbox_public
                    self.reply(200, {'community_id': community.community_id, 'privacy': community.policy['privacy'],
                        'carrier_required': community.policy['privacy'] == 'restricted',
                        'rights': community.policy['members'][public], 'public_key': public, 'mailbox': mailbox is not None,
                        'mailbox_public': mailbox_public(mailbox) if mailbox is not None else None,
                        'network_sync_available': peer is not None,
                        'registration': self.registration_state()}, set_cookie=True); return
                if parsed.path == '/api/sites':
                    from .community_site import list_sites
                    self.reply(200, {'sites': list_sites(community)}); return
                if parsed.path == '/api/view':
                    params = parse_qs(parsed.query)
                    if set(params) != {'domain'} or len(params['domain']) != 1: raise ProtocolError('INVALID_REQUEST', 'one application domain required')
                    self.reply(200, community.view(params['domain'][0])); return
                raise ProtocolError('INVALID_REQUEST', 'unknown local page')
            except (ProtocolError, ValueError, OSError) as exc:
                self.reply(403, {'error': getattr(exc, 'code', 'PORTAL_ERROR')})
        def do_POST(self):
            try:
                self.authorize(allow_unregistered=self.path == '/api/registration')
                if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                    raise ProtocolError('INVALID_REQUEST', 'exact bounded request body required')
                size = int(self.headers.get('Content-Length', '0'))
                if self.path == '/api/registration':
                    if registration is None:
                        raise ProtocolError('POLICY_DENIED', 'materials registration is not configured')
                    if self.headers.get('Content-Type') != 'application/octet-stream' or not 1 <= size <= 65536:
                        raise ProtocolError('INVALID_REQUEST', 'bounded text document upload required')
                    result = registration.submit(public, self.rfile.read(size))
                    self.reply(200, {'registration': self.registration_state(), **result}); return
                if self.path == '/api/registration-purge':
                    if registration is None:
                        raise ProtocolError('POLICY_DENIED', 'materials registration is not configured')
                    exact(strict_json(self.rfile.read(size)) if size else {}, set())
                    result = registration.purge(public)
                    self.reply(200, {'registration': self.registration_state(), **result}); return
                if self.path == '/api/file-upload':
                    if not set(community.policy['members'].get(public, [])) & {'files', 'packages'}:
                        raise ProtocolError('POLICY_DENIED', 'file or package upload permission required')
                    if self.headers.get('Content-Type') != 'application/octet-stream' or not 0 <= size <= MAX_FILE:
                        raise ProtocolError('INVALID_REQUEST', 'bounded binary upload required')
                    self.reply(200, community.put_file(self.rfile.read(size))); return
                if self.path == '/api/capsule-import':
                    if 'recover' not in community.policy['members'].get(public, []):
                        raise ProtocolError('POLICY_DENIED', 'recover permission required to import capsule')
                    if self.headers.get('Content-Type') != 'application/octet-stream' or not 1 <= size <= 64 * 1024 * 1024:
                        raise ProtocolError('INVALID_REQUEST', 'bounded binary capsule upload required')
                    from .capsule import import_capsule
                    self.reply(200, import_capsule(community, self.rfile.read(size))); return
                if self.path == '/api/capsule-info':
                    if self.headers.get('Content-Type') != 'application/octet-stream' or not 1 <= size <= 64 * 1024 * 1024:
                        raise ProtocolError('INVALID_REQUEST', 'bounded binary capsule upload required')
                    from .capsule import capsule_info
                    self.reply(200, capsule_info(self.rfile.read(size))); return
                if not 1 <= size <= 65536: raise ProtocolError('INVALID_REQUEST', 'portal request budget exceeded')
                if self.headers.get('Content-Type') != 'application/json': raise ProtocolError('INVALID_REQUEST', 'JSON portal request required')
                value = strict_json(self.rfile.read(size))
                if self.path == '/api/capsule-export':
                    exact(value, {'description'} if 'description' in value else set())
                    if 'recover' not in community.policy['members'].get(public, []):
                        raise ProtocolError('POLICY_DENIED', 'recover permission required to export capsule')
                    from .capsule import export_capsule
                    res = export_capsule(community, private, None, description=value.get('description', ''))
                    self.reply(200, res['body'], kind='application/octet-stream'); return
                if self.path == '/api/site':
                    exact(value, {'name', 'title'}|({'anonymous'} if 'anonymous' in value else set()))
                    from .community_site import publish_site
                    self.reply(200, publish_site(community, private, value['name'], value['title'], anonymous=bool(value.get('anonymous', False)))); return
                if self.path == '/api/vote':
                    exact(value, {'proposal', 'choice'})
                    event = community.vote(private, value['proposal'], value['choice'])
                    self.reply(200, {'event': event, 'tally': community.tally(value['proposal'])}); return
                if self.path == '/api/tally':
                    exact(value, {'proposal'})
                    self.reply(200, community.tally(value['proposal'])); return
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
                    key = value['key'] or ('msg-' + secrets.token_hex(12))
                    body = seal_mail(value['recipient'], value['mailbox'] or community.mailbox_for(value['recipient']), value['subject'], value['text'])
                    self.reply(200, {'event': community.publish(private, 'mail', key, body)}); return
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

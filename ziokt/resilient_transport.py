"""Bounded failover among approved paths; no privacy or TLS downgrade.

Only reads and independently content-addressed community operations are retried.
Native host mutations with uncertain outcomes require explicit reconciliation.
"""
import errno
import re
import ssl
import time
from .protocol import ProtocolError
from .routes import resolve_endpoint, _candidate_endpoint, validate_route

RETRYABLE_METHODS = frozenset({'community.status','community.checkpoint.create',
    'community.checkpoint.get','community.checkpoint.release','community.event.put',
    'community.blob.put','privacy.status','privacy.review.get','privacy.review.list',
    'zkn.shield.notes','zkn.shield.images','zkn.fact','operation.status','tracker.query','tracker.status'})
TRANSIENT = frozenset({errno.ECONNREFUSED,errno.ECONNRESET,errno.ETIMEDOUT,
                      errno.ENETUNREACH,errno.EHOSTUNREACH,errno.EPIPE})


def request_resilient(privacy, endpoint, context, request, signed_grant, *,
                      cancellation=None, total_timeout=120):
    from .remote import request_remote
    from .carrier import carrier_deadline
    if type(total_timeout) is not int or not 1<=total_timeout<=120:
        raise ProtocolError('INVALID_CONFIG','finite failover deadline required')
    route=validate_route(endpoint.get('connection_policy'),endpoint)
    if route['mode']=='approved-paths':
        paths=[]
        selected=resolve_endpoint(privacy,endpoint)
        peer_only=(selected.get('carrier') or {}).get('kind')=='peer-multihop'
        # Check all routes before a connection; observed assertions alone never
        # substitute for a concrete Tor/I2P carrier and pinned mTLS credentials.
        from .policy import select_path
        for candidate in endpoint['candidates']:
            if not isinstance(candidate,dict):raise ProtocolError('INVALID_CONFIG','typed approved path required')
            if candidate.get('approved') is not True:continue
            try:
                explicit_peer=(candidate.get('connection_policy') or {}).get('mode')=='peer-multihop'
                profile='private' if privacy=='restricted' and peer_only and explicit_peer else privacy
                select_path(profile,[candidate])
                path=resolve_endpoint(privacy,_candidate_endpoint(endpoint,candidate))
            except ProtocolError as exc:
                if exc.code=='NO_POLICY_COMPLIANT_PATH':continue
                raise
            if privacy=='restricted':
                kind=(path.get('carrier') or {}).get('kind')
                # Preserve an explicit peer-only deployment without pretending
                # it is Tor. Anonymous paths never fail over to peer-only/direct.
                if peer_only and kind!='peer-multihop':continue
                if not peer_only and kind not in {'tor-socks5','i2p-sam'}:continue
            paths.append(path)
        if not paths:raise ProtocolError('NO_POLICY_COMPLIANT_PATH','no approved concrete route satisfies privacy')
    else:paths=[resolve_endpoint(privacy,endpoint)]
    if request.get('method') not in RETRYABLE_METHODS:paths=paths[:1]
    if len(paths)>1 and not callable(signed_grant):
        raise ProtocolError('INVALID_CONFIG','failover requires fresh scoped signed grants')
    deadline=time.monotonic()+total_timeout
    diagnostics = []
    for index,path in enumerate(paths):
        if cancellation is not None and cancellation.is_set():raise ProtocolError('CANCELLED','private failover cancelled')
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        try:
            return request_remote(path['host'],path['port'],context,request,signed_grant,
                carrier=path.get('carrier'),timeout=min(carrier_deadline(path.get('carrier')),remaining),cancellation=cancellation,
                privacy_padding=privacy!='standard')
        except ssl.SSLError:
            # Authentication errors are not connectivity failures.
            raise
        except ProtocolError as exc:
            if exc.code not in {'CARRIER_UNAVAILABLE','BACKPRESSURE'}:raise
            item = {'code': exc.code}
            local = getattr(exc, 'transport_diagnostic', None)
            if type(local) is dict:
                phase, kind, reply = (local.get(field) for field in ('phase', 'kind', 'socks_reply'))
                if type(phase) is str and re.fullmatch(r'entry-connect|entry-connected|(?:target|hop-[1-4])-(?:auth-method|isolation-auth|socks-connect|bound-address)', phase): item['phase'] = phase
                if type(kind) is str and kind in {'OSError','TimeoutError','ConnectionRefusedError','ConnectionResetError','BrokenPipeError'}: item['kind'] = kind
                if type(reply) is int and 0 <= reply <= 255: item['socks_reply'] = reply
            diagnostics.append(item)
        except OSError as exc:
            if not isinstance(exc,(TimeoutError,ConnectionError)) and exc.errno not in TRANSIENT:raise
            diagnostics.append({'code': 'TRANSPORT_TIMEOUT' if isinstance(exc, TimeoutError) else 'TRANSPORT_UNAVAILABLE'})
        # Do not expose addresses, requests, identities or keys in retry logs.
    error = ProtocolError('CARRIER_UNAVAILABLE','approved paths unavailable; privacy preserved, no direct fallback')
    error.transport_diagnostics = diagnostics[:4]
    raise error

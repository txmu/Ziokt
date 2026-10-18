"""Bounded failover among approved paths; no privacy or TLS downgrade.

Only reads and independently content-addressed community operations are retried.
Native host mutations with uncertain outcomes require explicit reconciliation.
"""
import errno
import ssl
import time
from .protocol import ProtocolError
from .routes import resolve_endpoint, _candidate_endpoint, validate_route

RETRYABLE_METHODS = frozenset({'community.status','community.checkpoint.create',
    'community.checkpoint.get','community.checkpoint.release','community.event.put',
    'community.blob.put','privacy.status','privacy.review.get','privacy.review.list',
    'zkn.shield.notes','zkn.fact','operation.status','tracker.query','tracker.status'})
TRANSIENT = frozenset({errno.ECONNREFUSED,errno.ECONNRESET,errno.ETIMEDOUT,
                      errno.ENETUNREACH,errno.EHOSTUNREACH,errno.EPIPE})


def request_resilient(privacy, endpoint, context, request, signed_grant, *,
                      cancellation=None, total_timeout=120):
    from .remote import request_remote
    if type(total_timeout) is not int or not 1<=total_timeout<=120:
        raise ProtocolError('INVALID_CONFIG','finite failover deadline required')
    route=validate_route(endpoint.get('connection_policy'),endpoint)
    if route['mode']=='approved-paths':
        paths=[]
        # Check all routes before a connection; observed assertions alone never
        # substitute for a concrete Tor/I2P carrier and pinned mTLS credentials.
        from .policy import select_path
        for candidate in endpoint['candidates']:
            if not isinstance(candidate,dict):raise ProtocolError('INVALID_CONFIG','typed approved path required')
            if candidate.get('approved') is not True:continue
            try:
                select_path(privacy,[candidate])
                path=resolve_endpoint(privacy,_candidate_endpoint(endpoint,candidate))
            except ProtocolError as exc:
                if exc.code=='NO_POLICY_COMPLIANT_PATH':continue
                raise
            if privacy=='restricted' and (path.get('carrier',{}).get('kind') not in {'tor-socks5','i2p-sam'}):continue
            paths.append(path)
        if not paths:raise ProtocolError('NO_POLICY_COMPLIANT_PATH','no approved concrete route satisfies privacy')
    else:paths=[resolve_endpoint(privacy,endpoint)]
    if request.get('method') not in RETRYABLE_METHODS:paths=paths[:1]
    if len(paths)>1 and not callable(signed_grant):
        raise ProtocolError('INVALID_CONFIG','failover requires fresh scoped signed grants')
    deadline=time.monotonic()+total_timeout
    for index,path in enumerate(paths):
        if cancellation is not None and cancellation.is_set():raise ProtocolError('CANCELLED','private failover cancelled')
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        try:
            return request_remote(path['host'],path['port'],context,request,signed_grant,
                carrier=path.get('carrier'),timeout=min(30,remaining),cancellation=cancellation,
                privacy_padding=privacy!='standard')
        except ssl.SSLError:
            # Authentication errors are not connectivity failures.
            raise
        except ProtocolError as exc:
            if exc.code not in {'CARRIER_UNAVAILABLE','BACKPRESSURE'}:raise
        except OSError as exc:
            if not isinstance(exc,(TimeoutError,ConnectionError)) and exc.errno not in TRANSIENT:raise
        # Do not expose addresses, requests, identities or keys in retry logs.
    raise ProtocolError('CARRIER_UNAVAILABLE','approved paths unavailable; privacy preserved, no direct fallback')

"""Explicit route choices; Core requirements never silently change privacy intent."""
from .protocol import ProtocolError

MODES = {'direct', 'anonymous', 'relay', 'approved-paths'}


def validate_route(policy, endpoint):
    if policy is None:
        return {'mode': 'relay' if endpoint.get('rendezvous') is not None else 'anonymous' if endpoint.get('carrier') is not None else 'direct', 'allow_direct_fallback': False}
    if not isinstance(policy, dict) or set(policy) != {'mode', 'allow_direct_fallback'} or policy['mode'] not in MODES or type(policy['allow_direct_fallback']) is not bool:
        raise ProtocolError('INVALID_CONFIG', 'explicit route mode and fallback permission required')
    if policy['mode'] == 'direct' and endpoint.get('carrier') is not None:
        raise ProtocolError('INVALID_CONFIG', 'direct mode cannot silently use an anonymous carrier')
    if policy['mode'] == 'anonymous' and (endpoint.get('carrier') is None or policy['allow_direct_fallback']):
        raise ProtocolError('NO_POLICY_COMPLIANT_PATH', 'anonymous mode requires its carrier and excludes direct fallback')
    if policy['mode'] == 'relay' and endpoint.get('rendezvous') is None:
        raise ProtocolError('INVALID_CONFIG', 'relay mode requires an approved rendezvous peer')
    if policy['mode'] == 'approved-paths' and (not isinstance(endpoint.get('candidates'), list) or not 1 <= len(endpoint['candidates']) <= 4):
        raise ProtocolError('INVALID_CONFIG', 'approved-paths mode requires 1 to 4 explicit candidate paths')
    return policy


def admit_endpoint(privacy, endpoint):
    route = validate_route(endpoint.get('connection_policy'), endpoint)
    if route['mode'] == 'approved-paths':
        from .policy import select_path
        selected = select_path(privacy, endpoint['candidates'])
        return {**route, 'selected': selected}
    if privacy == 'restricted' and (endpoint.get('carrier') is None or route['mode'] == 'direct' or route['allow_direct_fallback']):
        raise ProtocolError('NO_POLICY_COMPLIANT_PATH', 'restricted policy requires a verified carrier without direct fallback')
    return route

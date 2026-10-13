"""Explicit route choices; Core requirements never silently change privacy intent."""
from .protocol import ProtocolError

MODES = {'direct', 'anonymous', 'relay', 'approved-paths', 'peer-multihop', 'discovered-peers'}


def validate_route(policy, endpoint):
    if policy is None:
        kind = endpoint.get('carrier', {}).get('kind') if isinstance(endpoint.get('carrier'), dict) else None
        return {'mode': 'peer-multihop' if kind == 'peer-multihop' else 'relay' if endpoint.get('rendezvous') is not None else 'anonymous' if endpoint.get('carrier') is not None else 'direct', 'allow_direct_fallback': False}
    if not isinstance(policy, dict) or set(policy) != {'mode', 'allow_direct_fallback'} or not isinstance(policy['mode'], str) or policy['mode'] not in MODES or type(policy['allow_direct_fallback']) is not bool:
        raise ProtocolError('INVALID_CONFIG', 'explicit route mode and fallback permission required')
    if policy['mode'] == 'direct' and endpoint.get('carrier') is not None:
        raise ProtocolError('INVALID_CONFIG', 'direct mode cannot silently use an anonymous carrier')
    if policy['mode'] == 'anonymous' and (endpoint.get('carrier') is None or policy['allow_direct_fallback']):
        raise ProtocolError('NO_POLICY_COMPLIANT_PATH', 'anonymous mode requires its carrier and excludes direct fallback')
    if policy['mode'] == 'anonymous' and (not isinstance(endpoint.get('carrier'), dict) or endpoint['carrier'].get('kind') not in {'tor-socks5', 'i2p-sam'}):
        raise ProtocolError('NO_POLICY_COMPLIANT_PATH', 'anonymous route requires its Tor or I2P carrier')
    if policy['mode'] == 'peer-multihop' and (not isinstance(endpoint.get('carrier'), dict) or endpoint['carrier'].get('kind') != 'peer-multihop' or policy['allow_direct_fallback']):
        raise ProtocolError('NO_POLICY_COMPLIANT_PATH', 'peer multihop requires an explicit carrier without fallback')
    if policy['mode'] == 'relay' and endpoint.get('rendezvous') is None:
        raise ProtocolError('INVALID_CONFIG', 'relay mode requires an approved rendezvous peer')
    if policy['mode'] == 'approved-paths' and (not isinstance(endpoint.get('candidates'), list) or not 1 <= len(endpoint['candidates']) <= 4):
        raise ProtocolError('INVALID_CONFIG', 'approved-paths mode requires 1 to 4 explicit candidate paths')
    if policy['mode'] == 'discovered-peers':
        from pathlib import Path
        if policy['allow_direct_fallback'] or not isinstance(endpoint.get('discovery'), str) or not Path(endpoint['discovery']).is_absolute():
            raise ProtocolError('INVALID_CONFIG', 'discovery requires a fixed opt-in config without fallback')
    return policy


def admit_endpoint(privacy, endpoint):
    if privacy not in {'standard', 'private', 'restricted'} or not isinstance(endpoint, dict):
        raise ProtocolError('INVALID_CONFIG', 'known privacy profile and typed endpoint required')
    route = validate_route(endpoint.get('connection_policy'), endpoint)
    if route['mode'] == 'discovered-peers':
        from .peer_directory import load_directory, DiscoveryWorker
        directory, config = load_directory(endpoint['discovery'])
        if 'signing_key' in config:
            if directory.worker is None: directory.worker = DiscoveryWorker(directory, config)
            directory.worker.start()
        carrier = directory.build_route(config['hop_count'], config['client_tls'], (endpoint['host'], endpoint['port']))
        resolved = {**endpoint, 'carrier': carrier, 'connection_policy': {'mode': 'peer-multihop', 'allow_direct_fallback': False}}
        admit_endpoint(privacy, resolved)
        return {**route, 'resolved': resolved}
    if route['mode'] == 'approved-paths':
        from .policy import select_path
        # Peer routing is an explicit operator opt-in, with a separate claim
        # from Tor anonymity. It still needs authenticated encrypted content.
        selected = None
        for candidate in endpoint['candidates']:
            if not isinstance(candidate, dict): raise ProtocolError('INVALID_CONFIG', 'typed approved path required')
            peer_route = isinstance(candidate.get('connection_policy'), dict) and candidate['connection_policy'].get('mode') == 'peer-multihop'
            profile = 'private' if privacy == 'restricted' and peer_route else privacy
            try: selected = select_path(profile, [candidate])
            except ProtocolError as exc:
                if exc.code == 'NO_POLICY_COMPLIANT_PATH': continue
                raise
            break
        if selected is None:
            raise ProtocolError('NO_POLICY_COMPLIANT_PATH', 'no approved path satisfies privacy requirements')
        candidate_endpoint = _candidate_endpoint(endpoint, selected)
        admit_endpoint(privacy, candidate_endpoint)
        if not route['allow_direct_fallback'] and endpoint.get('carrier') is not None and candidate_endpoint.get('carrier') is None:
            raise ProtocolError('NO_POLICY_COMPLIANT_PATH', 'approved path cannot bypass the configured carrier')
        return {**route, 'selected': selected}
    if not isinstance(endpoint.get('host'), str) or not endpoint['host'] or type(endpoint.get('port')) is not int or not 1 <= endpoint['port'] <= 65535:
        raise ProtocolError('INVALID_CONFIG', 'fixed connection host and port required')
    if endpoint.get('carrier') is not None:
        from .carrier import validate_carrier
        validate_carrier(endpoint['carrier'], endpoint['host'])
        if endpoint['carrier']['kind'] == 'peer-multihop' and route['mode'] not in {'peer-multihop', 'relay'}:
            raise ProtocolError('NO_POLICY_COMPLIANT_PATH', 'explicit peer route mode required')
    elif endpoint['host'].endswith(('.onion', '.i2p')):
        raise ProtocolError('NO_POLICY_COMPLIANT_PATH', 'anonymous endpoints require their explicit carrier')
    if privacy == 'restricted' and (endpoint.get('carrier') is None or route['mode'] == 'direct' or route['allow_direct_fallback']):
        raise ProtocolError('NO_POLICY_COMPLIANT_PATH', 'restricted policy requires a verified carrier without direct fallback')
    return route


def _candidate_endpoint(endpoint, candidate):
    required = {'approved', 'observed', 'host', 'port'}
    if not required <= set(candidate) or set(candidate)-required-{'carrier', 'connection_policy', 'rendezvous'}:
        raise ProtocolError('INVALID_CONFIG', 'approved candidates need concrete bounded connection settings')
    policy = candidate.get('connection_policy')
    if isinstance(policy, dict) and policy.get('mode') == 'approved-paths':
        raise ProtocolError('INVALID_CONFIG', 'nested candidate selection rejected')
    # Credentials remain pinned by the parent config, transport comes entirely
    # from this candidate. Never inherit the parent's unselected direct host.
    resolved = {k: v for k, v in endpoint.items() if k not in {'host', 'port', 'carrier', 'connection_policy', 'rendezvous', 'candidates'}}
    resolved.update({k: v for k, v in candidate.items() if k not in {'approved', 'observed'}})
    return resolved


def resolve_endpoint(privacy, endpoint):
    route = admit_endpoint(privacy, endpoint)
    if route['mode'] == 'discovered-peers': return route['resolved']
    return _candidate_endpoint(endpoint, route['selected']) if route['mode'] == 'approved-paths' else dict(endpoint)

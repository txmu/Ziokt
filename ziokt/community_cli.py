"""Explicit community lifecycle, applications, replicas and network exchange."""
from pathlib import Path
import secrets

from .community import Community, DOMAINS, RIGHTS, create_policy, content_id
from .protocol import ProtocolError, secure_read, strict_json
from .security import sign


def register(sub):
    parser = sub.add_parser('community', help='portable private community apps, encrypted replicas and network sync')
    actions = parser.add_subparsers(dest='community_action', required=True)
    init = actions.add_parser('init', help='create private keys and signed membership policy; no network activation')
    init.add_argument('--root', required=True, type=Path)
    init.add_argument('--name', required=True)
    init.add_argument('--privacy', choices=('private', 'restricted'), default='restricted')
    for action in ('publish', 'view', 'put-file', 'get-file', 'checkpoint', 'restore', 'replicate', 'sync', 'serve', 'policy'):
        cmd = actions.add_parser(action)
        cmd.add_argument('--root', required=True, type=Path)
        cmd.add_argument('--policy', required=True, type=Path)
        cmd.add_argument('--owner', required=True)
        cmd.add_argument('--encryption-key', required=True, type=Path)
        if action in ('publish', 'checkpoint', 'replicate', 'sync', 'serve', 'policy'):
            cmd.add_argument('--signing-key', required=True, type=Path)
        if action in ('publish', 'view'):
            cmd.add_argument('--domain', choices=sorted(DOMAINS), required=True)
            cmd.add_argument('--object-key', required=action == 'publish')
        if action == 'publish':
            cmd.add_argument('--body', required=True, type=Path)
            cmd.add_argument('--parents', type=Path)
            cmd.add_argument('--delete', action='store_true')
        if action == 'put-file': cmd.add_argument('--input', required=True, type=Path)
        if action == 'get-file':
            cmd.add_argument('--manifest', required=True, type=Path)
            cmd.add_argument('--output', required=True, type=Path)
        if action == 'checkpoint': cmd.add_argument('--output', required=True, type=Path)
        if action == 'restore':
            cmd.add_argument('--input', required=True, type=Path)
            cmd.add_argument('--publisher', required=True)
        if action == 'replicate':
            cmd.add_argument('--peer-root', type=Path, required=True, action='append')
            cmd.add_argument('--minimum', type=int, default=2)
        if action in ('sync', 'serve'): cmd.add_argument('--tls-config', required=True, type=Path)
        if action == 'sync': cmd.add_argument('--publisher', required=True)
        if action == 'policy':
            cmd.add_argument('--members', required=True, type=Path)
            cmd.add_argument('--epoch', required=True, type=int)
            cmd.add_argument('--output', required=True, type=Path)


def execute(args):
    from .cli import write_exclusive, write_binary_exclusive
    if args.community_action == 'init':
        if args.root.exists(): raise ProtocolError('ALREADY_EXISTS', 'new community root required')
        args.root.mkdir(mode=0o700, parents=True)
        from .protocol import make_private
        make_private(args.root)
        private, key = secrets.token_bytes(32), secrets.token_bytes(32)
        public = sign({}, private, 'Ziokt/check-key/v1')['public_key']
        policy = create_policy(private, args.name, {public: sorted(RIGHTS)}, privacy=args.privacy)
        write_binary_exclusive(args.root/'owner.key', private)
        write_binary_exclusive(args.root/'content.key', key)
        write_exclusive(args.root/'policy.json', policy)
        with Community(args.root/'state', policy, public, key): pass
        return {'community_id': args.name, 'owner': public, 'policy': str(args.root/'policy.json'),
                'encryption_key': str(args.root/'content.key'), 'signing_key': str(args.root/'owner.key'),
                'state_root': str(args.root/'state'), 'network_enabled': False}
    policy = strict_json(secure_read(args.policy))
    with Community(args.root, policy, args.owner, secure_read(args.encryption_key, 32)) as community:
        private = secure_read(args.signing_key, 32) if hasattr(args, 'signing_key') else None
        action = args.community_action
        if action == 'publish':
            return {'event': community.publish(private, args.domain, args.object_key, strict_json(secure_read(args.body)),
                parents=strict_json(secure_read(args.parents)) if args.parents else None, deleted=args.delete)}
        if action == 'view': return community.view(args.domain, args.object_key)
        if action == 'put-file': return community.put_file(secure_read(args.input, 520192, private=None))
        if action == 'get-file':
            data = community.get_file(strict_json(secure_read(args.manifest)))
            write_binary_exclusive(args.output, data)
            return {'output': str(args.output), 'size': len(data), 'digest': content_id(data)}
        if action == 'checkpoint':
            blob = community.checkpoint(private); write_binary_exclusive(args.output, blob)
            return {'output': str(args.output), 'digest': content_id(blob), 'size': len(blob)}
        if action == 'restore': return community.restore(secure_read(args.input, 32*1024*1024), args.publisher)
        if action == 'policy':
            if sign({}, private, 'Ziokt/check-key/v1')['public_key'] != args.owner or args.epoch <= community.policy['epoch']:
                raise ProtocolError('POLICY_DENIED', 'owner signature and increasing policy epoch required')
            document = create_policy(private, community.community_id, strict_json(secure_read(args.members)),
                                     epoch=args.epoch, privacy=community.policy['privacy'])
            write_exclusive(args.output, document)
            return {'policy': str(args.output), 'epoch': args.epoch, 'content_key_rotation_required_for_confidential_revocation': True}
        if action == 'replicate':
            peers = []
            try:
                for path in args.peer_root: peers.append(Community(path, policy, args.owner, secure_read(args.encryption_key, 32)))
                result = community.replicate(peers, private, minimum=args.minimum)
                result['healthy'] = result['satisfied']; return result
            finally:
                for peer in peers: peer.close()
        if action in ('sync', 'serve'):
            from .remote import load_remote, tls_context, remote_server
            from .community_network import CommunityEndpoint, sync_remote
            endpoint = load_remote(args.tls_config, serving=action == 'serve')
            context = tls_context(endpoint['certificate'], endpoint['private_key'], endpoint['ca'], server=action == 'serve')
            if action == 'sync': return sync_remote(community, endpoint, context, private, publisher=args.publisher)
            if endpoint['host'] != '127.0.0.1':
                raise ProtocolError('INVALID_CONFIG', 'community server is loopback-only; expose via explicitly configured onion service')
            federation = {'enabled': True, 'federation_id': community.community_id, 'providers': []}
            server = remote_server(federation, context, endpoint['replay_state'], endpoint['trusted_clients'],
                host=endpoint['host'], port=endpoint['port'], allow_mutations=endpoint['allow_mutations'],
                community=CommunityEndpoint(community, private))
            try: server.serve_forever()
            except KeyboardInterrupt: pass
            finally: server.server_close()
            return {'stopped': True}
        raise ProtocolError('INVALID_APPLICATION', 'unknown community action')

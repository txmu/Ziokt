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
    init.add_argument('--limits', type=Path)
    for action in ('publish', 'view', 'vote', 'tally', 'put-file', 'get-file', 'checkpoint', 'restore', 'replicate', 'sync', 'serve', 'policy', 'rotate', 'invite', 'accept', 'mail-send', 'mail-open', 'ui', 'native', 'materialize'):
        cmd = actions.add_parser(action)
        cmd.add_argument('--root', required=True, type=Path)
        cmd.add_argument('--policy', required=True, type=Path)
        cmd.add_argument('--owner', required=True)
        cmd.add_argument('--encryption-key', required=True, type=Path)
        if action in ('publish', 'vote', 'checkpoint', 'replicate', 'sync', 'serve', 'policy', 'rotate', 'invite', 'mail-send', 'ui', 'native'):
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
            cmd.add_argument('--limits', type=Path)
            cmd.add_argument('--registration', type=Path, help='signed community registration policy JSON')
        if action in ('invite', 'accept'):
            cmd.add_argument('--invitation-key', required=True, type=Path)
        if action == 'invite':
            cmd.add_argument('--host', required=True)
            cmd.add_argument('--port', required=True, type=int)
            cmd.add_argument('--output', required=True, type=Path)
        if action == 'accept':
            cmd.add_argument('--input', required=True, type=Path)
            cmd.add_argument('--publisher', required=True)
        if action == 'mail-send':
            cmd.add_argument('--recipient', required=True)
            cmd.add_argument('--recipient-mailbox')
            cmd.add_argument('--message', required=True, type=Path)
            cmd.add_argument('--object-key', required=True)
        if action == 'mail-open':
            cmd.add_argument('--message', required=True, type=Path)
            cmd.add_argument('--mailbox-key', required=True, type=Path)
            cmd.add_argument('--recipient', required=True)
        if action == 'ui':
            cmd.add_argument('--registration-config', type=Path, help='local federation config required by registration policy')
            cmd.add_argument('--port', type=int, default=0)
            cmd.add_argument('--session-file', type=Path, required=True)
            cmd.add_argument('--mailbox-key', type=Path)
            cmd.add_argument('--peer-tls', type=Path)
            cmd.add_argument('--peer-publisher')
        if action == 'materialize':
            cmd.add_argument('--manifest', type=Path, required=True)
            cmd.add_argument('--native-store', type=Path, required=True)
        if action == 'native':
            cmd.add_argument('--config', type=Path, required=True)
            cmd.add_argument('--journal', type=Path, required=True)
            cmd.add_argument('--manifest', type=Path, required=True)
            cmd.add_argument('--domain', choices=('hosting', 'compute'), required=True)
            cmd.add_argument('--object-key', required=True)
            cmd.add_argument('--apply', action='store_true')
            cmd.add_argument('--expected-digest')
            cmd.add_argument('--confirm', action='store_true')
        if action == 'rotate':
            cmd.add_argument('--next-policy', type=Path, required=True)
            cmd.add_argument('--next-encryption-key', type=Path, required=True)
        if action in ('vote', 'tally'):
            cmd.add_argument('--proposal', required=True)
        if action == 'vote': cmd.add_argument('--choice', choices=('yes', 'no', 'abstain'), required=True)


def execute(args):
    from .cli import write_exclusive, write_binary_exclusive
    if args.community_action == 'init':
        if args.root.exists(): raise ProtocolError('ALREADY_EXISTS', 'new community root required')
        args.root.mkdir(mode=0o700, parents=True)
        from .protocol import make_private
        make_private(args.root)
        private, key = secrets.token_bytes(32), secrets.token_bytes(32)
        public = sign({}, private, 'Ziokt/check-key/v1')['public_key']
        policy = create_policy(private, args.name, {public: sorted(RIGHTS)}, privacy=args.privacy,
                               limits=strict_json(secure_read(args.limits)) if args.limits else None)
        write_binary_exclusive(args.root/'owner.key', private)
        write_binary_exclusive(args.root/'content.key', key)
        mailbox = secrets.token_bytes(32)
        write_binary_exclusive(args.root/'mailbox.key', mailbox)
        from .community_privacy import mailbox_public
        write_exclusive(args.root/'policy.json', policy)
        with Community(args.root/'state', policy, public, key) as community:
            community.publish(private, 'identity', public, {'name': args.name, 'public_key': public, 'mailbox_public': mailbox_public(mailbox)})
        return {'community_id': args.name, 'owner': public, 'policy': str(args.root/'policy.json'),
                'encryption_key': str(args.root/'content.key'), 'signing_key': str(args.root/'owner.key'),
                'state_root': str(args.root/'state'), 'mailbox_public': mailbox_public(mailbox), 'network_enabled': False}
    policy = strict_json(secure_read(args.policy))
    with Community(args.root, policy, args.owner, secure_read(args.encryption_key, 32)) as community:
        private = secure_read(args.signing_key, 32) if hasattr(args, 'signing_key') else None
        action = args.community_action
        if action == 'vote': return {'event': community.vote(private, args.proposal, args.choice)}
        if action == 'tally': return community.tally(args.proposal)
        if action == 'rotate':
            with community.rotate(strict_json(secure_read(args.next_policy)), secure_read(args.next_encryption_key, 32), private) as rotated:
                return {'policy': rotated.policy_id, 'epoch': rotated.policy['epoch'], 'historical_data_preserved': True,
                        'new_key_distribution_required': True}
        if action == 'materialize':
            from .community_native import materialize
            from .artifacts import ArtifactStore
            return materialize(community, strict_json(secure_read(args.manifest)), ArtifactStore(args.native_store))
        if action == 'native':
            from .community_native import native_workflow
            from .workflow import WorkflowJournal
            from .config import load
            with WorkflowJournal(args.journal) as journal:
                return native_workflow(community, private, load(args.config), journal, strict_json(secure_read(args.manifest)),
                    domain=args.domain, object_key=args.object_key, apply=args.apply,
                    expected_digest=args.expected_digest, confirmed=args.confirm)
        if action == 'invite':
            from .community_privacy import invitation
            blob = invitation(community, private, secure_read(args.invitation_key, 32), args.host, args.port)
            write_binary_exclusive(args.output, blob)
            return {'output': str(args.output), 'encrypted': True}
        if action == 'accept':
            from .community_privacy import accept_invitation
            return accept_invitation(community, secure_read(args.input, 4096), secure_read(args.invitation_key, 32), args.publisher)
        if action == 'mail-send':
            from .community_privacy import seal_mail
            message = strict_json(secure_read(args.message))
            from .community import exact
            exact(message, {'subject', 'text'})
            body = seal_mail(args.recipient, args.recipient_mailbox or community.mailbox_for(args.recipient), message['subject'], message['text'])
            return {'event': community.publish(private, 'mail', args.object_key, body)}
        if action == 'mail-open':
            from .community_privacy import open_mail
            return open_mail(secure_read(args.mailbox_key, 32), args.recipient, strict_json(secure_read(args.message)))
        if action == 'ui':
            from .community_ui import portal_server
            mailbox = secure_read(args.mailbox_key, 32) if args.mailbox_key else None
            peer = context = None
            if args.peer_tls or args.peer_publisher:
                if not args.peer_tls or not args.peer_publisher:
                    raise ProtocolError('INVALID_CONFIG', 'fixed peer TLS config and publisher must be supplied together')
                from .remote import load_remote, tls_context
                peer = load_remote(args.peer_tls)
                context = tls_context(peer['certificate'], peer['private_key'], peer['ca'])
            server, token = portal_server(community, private, port=args.port, mailbox=mailbox,
                peer=peer, peer_context=context, publisher=args.peer_publisher,
                registration_config=args.registration_config)
            try:
                write_exclusive(args.session_file, {'url': 'http://127.0.0.1:'+str(server.server_port)+'/', 'token': token})
                server.serve_forever()
            except KeyboardInterrupt: pass
            finally: server.server_close()
            return {'stopped': True}
        if action == 'publish':
            return {'event': community.publish(private, args.domain, args.object_key, strict_json(secure_read(args.body)),
                parents=strict_json(secure_read(args.parents)) if args.parents else None, deleted=args.delete)}
        if action == 'view': return community.view(args.domain, args.object_key)
        if action == 'put-file':
            from .community import MAX_FILE
            return community.put_file(secure_read(args.input, MAX_FILE, private=None))
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
                                     epoch=args.epoch, privacy=community.policy['privacy'],
                                     limits=strict_json(secure_read(args.limits)) if args.limits else community.policy.get('limits'),
                                     registration=strict_json(secure_read(args.registration)) if args.registration else community.policy.get('registration'))
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

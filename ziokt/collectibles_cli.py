"""Collectibles, signed Extensions and explicit joint-node CLI routes."""
from pathlib import Path
import hashlib
import secrets
import threading

from .protocol import ProtocolError,encoded,secure_read,strict_json


def register(sub):
    extensions=sub.add_parser('extensions',help='signed isolated Shadow6 extensions without rebuilding a Core')
    actions=extensions.add_subparsers(dest='extension_action',required=True)
    for action in ('catalog','install','invoke'):
        cmd=actions.add_parser(action)
        if action in ('catalog','install'):cmd.add_argument('--shadow6',type=Path,required=True)
        if action=='install':
            cmd.add_argument('--output',type=Path,required=True);cmd.add_argument('--binding',type=Path,required=True);cmd.add_argument('--signing-key',type=Path,required=True)
        if action=='invoke':
            cmd.add_argument('--binding',type=Path,required=True);cmd.add_argument('--signing-key',type=Path,required=True)
            cmd.add_argument('--core',required=True);cmd.add_argument('--core-digest',required=True);cmd.add_argument('--event',type=Path,required=True)
    zkn=sub.add_parser('zkn',help='collectible receiver, private gift and durable multihop delivery')
    actions=zkn.add_subparsers(dest='collectible_action',required=True)
    cmd=actions.add_parser('receiver');cmd.add_argument('--network',required=True);cmd.add_argument('--offer',type=Path,required=True);cmd.add_argument('--wallet',type=Path,required=True)
    cmd=actions.add_parser('gift')
    for name in ('snapshot','offer','owner-key','outbox','outbox-key'):cmd.add_argument('--'+name,type=Path,required=True)
    cmd.add_argument('--nonce',type=int,required=True);cmd.add_argument('--extensions',type=Path);cmd.add_argument('--legacy-delivery',action='store_true')
    cmd=actions.add_parser('public-transfer',help='explicit legacy public ownership transfer')
    for name in ('config',):cmd.add_argument('--'+name,type=Path,required=True)
    for name in ('provider','token','recipient'):cmd.add_argument('--'+name,required=True)
    cmd.add_argument('--nonce',type=int,required=True)
    for action in ('status','deliver'):
        cmd=actions.add_parser(action);cmd.add_argument('--outbox',type=Path,required=True);cmd.add_argument('--outbox-key',type=Path,required=True)
        if action=='deliver':
            cmd.add_argument('--tls-config',type=Path,required=True);cmd.add_argument('--signing-key',type=Path,required=True);cmd.add_argument('--legacy-delivery',action='store_true')
            cmd.add_argument('--federation',required=True);cmd.add_argument('--provider',required=True)
            cmd.add_argument('--confirmations',type=int,default=2);cmd.add_argument('--follow',action='store_true');cmd.add_argument('--interval',type=int,default=10)
    cmd=actions.add_parser('accept')
    for name in ('wallet','snapshot','transaction','config','receipt'):cmd.add_argument('--'+name,type=Path,required=True)
    cmd.add_argument('--provider',required=True);cmd.add_argument('--confirmations',type=int,default=2)
    zkc=sub.add_parser('zkc',help='holder-authorized collectible editions and sealed packs')
    actions=zkc.add_subparsers(dest='collectible_action',required=True)
    cmd=actions.add_parser('issue')
    for name in ('network','token','serial','content-digest'):cmd.add_argument('--'+name,required=True)
    cmd.add_argument('--kind',choices=('repeat','unique'),required=True);cmd.add_argument('--owner-key',type=Path,required=True)
    cmd.add_argument('--transaction',type=Path,required=True);cmd.add_argument('--config',type=Path,required=True);cmd.add_argument('--provider',required=True)
    cmd=actions.add_parser('pack')
    for name in ('transactions','owner-key','offer','output'):cmd.add_argument('--'+name,type=Path,required=True)
    cmd.add_argument('--network',required=True);cmd.add_argument('--extensions',type=Path)
    cmd=actions.add_parser('unpack')
    for name in ('pack','wallet','publisher-key','config','output'):cmd.add_argument('--'+name,type=Path,required=True)
    cmd.add_argument('--provider',required=True);cmd.add_argument('--confirmations',type=int,default=2)
    node=sub.add_parser('node',help='review and export joint Corium, Virtual Broker and S6EPE deployment')
    actions=node.add_subparsers(dest='node_action',required=True)
    cmd=actions.add_parser('init')
    for name in ('shadow6','federation-config','registry','virtual-config','output'):cmd.add_argument('--'+name,type=Path,required=True)
    cmd.add_argument('--corium-provider',required=True)
    cmd.add_argument('--corium-unit',default='corium.service');cmd.add_argument('--guard-unit',default='shadow6-guard.service');cmd.add_argument('--gate-unit',default='shadow6-gate.service')
    cmd.add_argument('--native-only',action='store_true')
    for action in ('plan','export','serve'):
        cmd=actions.add_parser(action);cmd.add_argument('--profile',type=Path,required=True)
        if action=='export':cmd.add_argument('--output',type=Path,required=True);cmd.add_argument('--name',default='ziokt-node')
        if action=='serve':cmd.add_argument('--expected-digest',required=True)


def _json(path,maximum=65536):return strict_json(secure_read(path,maximum),maximum)


def _client(config_path,provider):
    from .config import load
    from .client import NativeClient
    config=load(config_path)
    p=next((p for p in config['providers'] if p['provider_id']==provider and p['native_project']=='corium'),None)
    if not config['enabled'] or p is None:raise ProtocolError('INVALID_CONFIG','enabled reviewed native Corium provider required')
    return NativeClient(config['federation_id'],p)


def submit(client,action,resource,arguments):
    op='collectible-'+secrets.token_hex(16)
    plan=client.call('operation.prepare',{'operation_id':op,'action':action,'resource':resource,'arguments':arguments,'expected_revision':None})
    return client.call('operation.commit',{'operation_id':op,'plan_digest':plan['plan_digest']})


def execute(args):
    from .cli import write_exclusive,write_binary_exclusive
    if args.action=='extensions':
        from .extensions import feature_matrix,install,Extensions
        if args.extension_action=='catalog':return {'schema':'ziokt.extensions.v1','cores':feature_matrix(args.shadow6)}
        if args.extension_action=='install':
            binding=install(args.shadow6,args.output,secure_read(args.signing_key,32));write_exclusive(args.binding,binding);return binding
        return Extensions(_json(args.binding),secure_read(args.signing_key,32),args.core,args.core_digest)(_json(args.event))
    if args.action=='node':
        from .node import create_profile,plan,export_units,serve
        if args.node_action=='init':
            profile=create_profile(args.shadow6,args.federation_config,args.corium_provider,args.registry,args.virtual_config,
                {'corium':args.corium_unit,'guard':args.guard_unit,'gate':args.gate_unit},require_s6epe=not args.native_only)
            write_exclusive(args.output,profile);return plan(profile,probe=False)
        profile=_json(args.profile)
        if args.node_action=='plan':return plan(profile)
        if args.node_action=='export':return export_units(profile,args.profile,args.output,args.name)
        serve(profile,args.expected_digest);return {'stopped':True}
    from .collectibles import receiver,gift,accept_gift,GiftOutbox,GiftRoutes,GiftRPC,issue_edition,pack_editions,unpack_editions
    if args.action=='zkn':
        action=args.collectible_action
        if action=='receiver':
            offer,wallet=receiver(args.network);write_exclusive(args.wallet,wallet);write_exclusive(args.offer,offer)
            return {'schema':'ziokt.zkn-receiver-created.v1','offer':str(args.offer),'wallet':str(args.wallet),'single_use':True}
        if action in ('gift','status','deliver'):
            box=GiftOutbox(args.outbox,secure_read(args.outbox_key,32),privacy_mode='legacy' if getattr(args,'legacy_delivery',False) else 'mixed')
            try:
                if action=='gift':
                    from .extensions import load_extensions
                    tx=gift(_json(args.snapshot),args.nonce,_json(args.offer),secure_read(args.owner_key,16384).decode(),extension=load_extensions(args.extensions) if args.extensions else None)
                    tx_hash=box.enqueue(tx);return {'transaction_hash':tx_hash,'phase':'queued','private':True,'fee_required':False}
                if action=='status':return {'gifts':box.status()}
                from .remote import load_remote,tls_context
                endpoint=load_remote(args.tls_config);context=tls_context(endpoint['certificate'],endpoint['private_key'],endpoint['ca'])
                routes=GiftRoutes(endpoint);cancel=threading.Event();rpc=GiftRPC(args.federation,args.provider,context,secure_read(args.signing_key,32),cancellation=cancel,delivery_version=1 if args.legacy_delivery else 2)
                if not 1<=args.interval<=300:raise ProtocolError('INVALID_CONFIG','bounded delivery polling interval required')
                try:
                    while True:
                        result=box.cycle(rpc,routes,confirmations=args.confirmations,cancellation=cancel)
                        if not args.follow:return {'gifts':result}
                        cancel.wait(args.interval)
                except KeyboardInterrupt:cancel.set();return {'gifts':box.status(),'stopped':True}
            finally:box.close()
        client=_client(args.config,args.provider)
        if action=='public-transfer':return submit(client,'zkn.transfer','zkn:'+args.token,{'recipient':args.recipient,'nonce':args.nonce})
        from ._runtime import asset_signed_gift
        tx=_json(args.transaction);tx_hash=asset_signed_gift(tx,tx['data']['network_id'])[1]
        receipt=accept_gift(_json(args.wallet),_json(args.snapshot),tx,client.call('zkn.fact',{'transaction_hash':tx_hash}),confirmations=args.confirmations)
        write_exclusive(args.receipt,receipt);return receipt
    action=args.collectible_action
    if action=='issue':
        tx=issue_edition(args.network,args.token,args.kind,args.serial,args.content_digest,secure_read(args.owner_key,16384).decode())
        # Keep recoverable exact signed bytes before any native submission.
        write_exclusive(args.transaction,tx)
        return submit(_client(args.config,args.provider),'zkc.issue','zkn:'+args.token,{'transaction':tx})
    if action=='pack':
        from .extensions import load_extensions
        blob=pack_editions(_json(args.transactions,1024*1024),args.network,secure_read(args.owner_key,16384).decode(),_json(args.offer),extension=load_extensions(args.extensions) if args.extensions else None)
        write_binary_exclusive(args.output,blob);return {'pack':str(args.output),'bytes':len(blob),'fee_required':False}
    result=unpack_editions(secure_read(args.pack,1024*1024),_json(args.wallet),publisher=secure_read(args.publisher_key,16384,private=None).decode().rstrip('\n'),
        query=_client(args.config,args.provider).call,confirmations=args.confirmations)
    write_exclusive(args.output,result);return result

"""Modern SafeFS and typed Ano/ZDA command entry points."""
import argparse
import hashlib
from pathlib import Path
from .protocol import encoded,secure_read,strict_json,ProtocolError
from .i18n import translate,LOCALES


def register(sub):
    cmd=sub.add_parser('companion',help='integrated SafeFS, Ano/ZDA, UFS/DCPM, TC-16 and ecosystem tools')
    families=cmd.add_subparsers(dest='companion',required=True)
    catalog=families.add_parser('catalog');catalog.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);catalog.add_argument('--lang',choices=LOCALES,default='en')
    vault=families.add_parser('safefs');actions=vault.add_subparsers(dest='companion_action',required=True)
    for action in ('put','get','publish','doctor'):
        item=actions.add_parser(action);item.add_argument('--lang',choices=LOCALES,default='en')
        if action!='doctor':
            item.add_argument('--root',type=Path,required=True);item.add_argument('--scope',required=True);item.add_argument('--key',type=Path,required=True)
        if action=='put':item.add_argument('--input',type=Path,required=True);item.add_argument('--name',required=True)
        if action in ('get','publish'):item.add_argument('--digest',required=True)
        if action=='get':item.add_argument('--output',type=Path,required=True)
        if action=='publish':item.add_argument('--bridge-config',type=Path,required=True)
    cpu=families.add_parser('tc16');actions=cpu.add_subparsers(dest='companion_action',required=True)
    for action in ('compile','run'):
        item=actions.add_parser(action);item.add_argument('--lang',choices=LOCALES,default='en');item.add_argument('--input',type=Path,required=True)
        item.add_argument('--syntax',choices=('assembly','tcc'),default='assembly')
        if action=='run':item.add_argument('--cycles',type=int,default=10000);item.add_argument('--debug',action='store_true')
        else:item.add_argument('--output',type=Path,required=True)
    packages=families.add_parser('ufsdcpm');actions=packages.add_subparsers(dest='companion_action',required=True)
    for action in ('put','get','publish'):
        item=actions.add_parser(action);item.add_argument('--lang',choices=LOCALES,default='en');item.add_argument('--root',type=Path,required=True);item.add_argument('--scope',required=True);item.add_argument('--key',type=Path,required=True)
        if action=='put':
            item.add_argument('--directory',type=Path,required=True);item.add_argument('--name',required=True);item.add_argument('--version',required=True);item.add_argument('--signing-key',type=Path,required=True);item.add_argument('--dependency',action='append',default=[])
        else:item.add_argument('--digest',required=True)
        if action=='get':item.add_argument('--authority',required=True);item.add_argument('--output',type=Path,required=True)
        if action=='publish':item.add_argument('--bridge-config',type=Path,required=True)
    ano=families.add_parser('ano');actions=ano.add_subparsers(dest='companion_action',required=True)
    for action in ('evaluate','truth-table','defence'):
        item=actions.add_parser(action);item.add_argument('--lang',choices=LOCALES,default='en')
        if action in ('evaluate','defence'):item.add_argument('--input',type=Path,required=True)
    tri=families.add_parser('tri');actions=tri.add_subparsers(dest='companion_action',required=True)
    for action in ('put','get','publish'):
        item=actions.add_parser(action);item.add_argument('--lang',choices=LOCALES,default='en')
        item.add_argument('--root',type=Path,required=True);item.add_argument('--scope',default='tri');item.add_argument('--key',type=Path,required=True)
        if action=='put':item.add_argument('--input',type=Path,required=True);item.add_argument('--state',type=Path)
        else:item.add_argument('--digest',required=True)
        if action=='get':item.add_argument('--output',type=Path,required=True)
        if action=='publish':item.add_argument('--bridge-config',type=Path,required=True)


def execute(args):
    if args.companion=='catalog':
        from .ecosystem import inventory
        return inventory(args.root)
    if args.companion=='tc16':
        from .tc16 import TC16_CPU,assemble,TCCCompiler
        from .cli import write_binary_exclusive
        source=secure_read(args.input,65536,private=None).decode()
        if args.syntax=='tcc':source=TCCCompiler().compile(source)
        program=assemble(source)
        if args.companion_action=='compile':
            write_binary_exclusive(args.output,program);return {'schema':'ziokt.tc16-program.v1','word_bits':16,'isa':'tc16.v1','bytes':len(program),'output':str(args.output),'message':translate('tc16.compiled',args.lang)}
        cpu=TC16_CPU(debug=args.debug);cpu.load_program(program)
        return {**cpu.run(max_cycles=args.cycles),'message':translate('tc16.executed',args.lang)}
    if args.companion=='tri':
        from .safefs import Vault,MAX_FILE
        from .cli import write_binary_exclusive
        from .tri import project_bundle,read_project
        if args.scope!='tri':raise ProtocolError('INVALID_SAFEFS','Tri requires its own fixed SafeFS scope')
        vault=Vault(args.root,args.scope,secure_read(args.key,32))
        if args.companion_action=='put':
            program=secure_read(args.input,MAX_FILE,private=None).decode('utf-8')
            state=strict_json(secure_read(args.state,MAX_FILE,private=None)) if args.state else None
            bundle=project_bundle(program,state);item=vault.put('tri/projects/'+hashlib.sha256(bundle).hexdigest(),bundle)
            return {**item,'message':translate('tri.saved',args.lang),'plaintext_disclosed':False}
        if args.companion_action=='get':
            name,data=vault.get(args.digest)
            if not name.startswith('tri/projects/'):raise ProtocolError('POLICY_DENIED','Tri project object required')
            project=read_project(data);write_binary_exclusive(args.output,encoded(project))
            return {'output':str(args.output),'message':translate('tri.opened',args.lang)}
        from .companion_bridge import CompanionBridge
        bridge=CompanionBridge(args.bridge_config)
        try:
            if bridge.app!='tri':raise ProtocolError('POLICY_DENIED','Tri scoped bridge required')
            return {**vault.publish(bridge.community,bridge.private,args.digest),'message':translate('tri.published',args.lang)}
        finally:bridge.close()
    if args.companion=='ufsdcpm':
        from .ufsdcpm import IntegratedStorage,MAX_PACKAGE
        from .safefs import Vault
        from .cli import write_binary_exclusive
        store=IntegratedStorage(Vault(args.root,args.scope,secure_read(args.key,32)))
        if args.companion_action=='put':
            if args.directory.is_symlink() or not args.directory.is_dir():raise ProtocolError('UNSAFE_FILE','real package directory required')
            files={};total=0
            for path in args.directory.rglob('*'):
                if path.is_symlink():raise ProtocolError('UNSAFE_FILE','package symlinks denied')
                if path.is_file():
                    data=secure_read(path,MAX_PACKAGE,private=None);total+=len(data)
                    if total>MAX_PACKAGE or len(files)>=128:raise ProtocolError('PACKAGE_LIMIT','bounded package tree required')
                    files[path.relative_to(args.directory).as_posix()]=data
            return {**store.publish_package(args.name,args.version,files,args.dependency,secure_read(args.signing_key,32)),'message':translate('package.saved',args.lang)}
        if args.companion_action=='get':
            manifest,_=store.download_package(args.digest,args.authority);_,blob=store.vault.get(args.digest);write_binary_exclusive(args.output,blob)
            return {'manifest':manifest,'output':str(args.output),'message':translate('package.verified',args.lang)}
        from .companion_bridge import CompanionBridge
        bridge=CompanionBridge(args.bridge_config)
        try:
            if bridge.app!='ufsdcpm':raise ProtocolError('POLICY_DENIED','scoped UFS/DCPM bridge required')
            return store.vault.publish(bridge.community,bridge.private,args.digest)
        finally:bridge.close()
    if args.companion=='ano':
        from .ano import evaluate,truth_table,defence
        if args.companion_action=='truth-table':return truth_table()
        value=strict_json(secure_read(args.input))
        if args.companion_action=='evaluate':return evaluate(value)
        if not isinstance(value,dict) or set(value)!={'evidence','required'}:raise ProtocolError('INVALID_ANO','exact defence evidence required')
        result=defence(value['evidence'],value['required']);return {**result,'message':translate('ano.'+result['decision'],args.lang)}
    from .safefs import Vault,sandbox_plan,MAX_FILE
    from .cli import write_binary_exclusive
    if args.companion_action=='doctor':return sandbox_plan()
    vault=Vault(args.root,args.scope,secure_read(args.key,32))
    if args.companion_action=='put':return {**vault.put(args.name,secure_read(args.input,MAX_FILE,private=None)),'message':translate('safefs.saved',args.lang)}
    if args.companion_action=='get':
        name,data=vault.get(args.digest);write_binary_exclusive(args.output,data)
        return {'name':name,'output':str(args.output),'message':translate('safefs.opened',args.lang)}
    from .companion_bridge import CompanionBridge
    bridge=CompanionBridge(args.bridge_config)
    try:return {**vault.publish(bridge.community,bridge.private,args.digest),'message':translate('safefs.shared',args.lang)}
    finally:bridge.close()


def main(argv=None):
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='action',required=True);register(sub)
    args=parser.parse_args(['companion',*(argv or [])])
    try:print(encoded(execute(args)).decode());return 0
    except (ProtocolError,OSError,ValueError) as exc:
        code=getattr(exc,'code','COMPANION_FAILED');print(encoded({'ok':False,'error':code,'message':translate(code,args.lang)}).decode());return 2

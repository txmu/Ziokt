#!/usr/bin/env python3
"""Pin the same local protocol in independent native deliveries; never run them."""
import argparse
import hashlib
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = "# BEGIN ZIOKT LOCAL PROVIDER (generated from Ziokt/spec/provider_runtime.py)\n"
END = "# END ZIOKT LOCAL PROVIDER\n"
ZKT_START = "# BEGIN ZIOKT ZKT ENGINE\n"
ZKT_END = "# END ZIOKT ZKT ENGINE\n"
ACTION_START = "# BEGIN ZIOKT NATIVE ACTIONS (generated, fixed monolith dispatcher)\n"
ACTION_END = "# END ZIOKT NATIVE ACTIONS\n"


def embedded(runtime, zkt):
    return START + '''# This early machine entry deliberately precedes native locks/recovery/TUI.
if [[ "${BASH_SOURCE[0]}" -ef "$0" && "${1:-}" == ziokt ]]; then
    shift
    command -v python3 >/dev/null 2>&1 || { printf '%s\\n' 'Ziokt requires Python 3.' >&2; exit 2; }
    # Python source uses stdin; request bytes remain on inherited descriptor 3.
    _ZIOKT_CORIUM_SOURCE="${BASH_SOURCE[0]}" python3 - "$@" 3<&0 <<'PY_ZIOKT_PROVIDER'
''' + runtime + '\n' + zkt + '''
sys.dont_write_bytecode = True
raise SystemExit(main("corium", argv=sys.argv[1:], rpc_stream=os.fdopen(3, "rb", closefd=False)))
PY_ZIOKT_PROVIDER
    exit $?
fi
''' + END


def zkt_engine(runtime, zkt):
    return ZKT_START + '''_ziokt_zkt_engine() {
    "${PYTHON_CMD:-python3}" - "$@" <<'PY_ZIOKT_ZKT_ENGINE'
''' + runtime + '\n' + zkt + '''
raise SystemExit(zkt_engine_main(sys.argv[1:]))
PY_ZIOKT_ZKT_ENGINE
}
corix_zkt() {
    local action="${1:-}"; [ $# -ge 1 ] && shift
    case "$action" in
        status) [ $# -eq 0 ] || return 2; _ziokt_zkt_engine status "$BLOCKCHAIN_DB" ;;
        account) [ $# -eq 1 ] || return 2; _ziokt_zkt_engine account "$BLOCKCHAIN_DB" "$1" ;;
        record) [ $# -eq 1 ] || return 2; _ziokt_zkt_engine record "$BLOCKCHAIN_DB" "$1" ;;
        policy) [ $# -eq 1 ] || return 2; _ziokt_zkt_engine policy "$BLOCKCHAIN_DB" "$1" ;;
        propose|vote|enact|proposals) [ $# -eq 1 ] || return 2; _ziokt_zkt_engine "$action" "$BLOCKCHAIN_DB" "$1" ;;
        *) printf '%s\\n' 'corix_zkt status | account ADDRESS | record CLAIM_JSON | policy POLICY_JSON' >&2; return 2 ;;
    esac
}
''' + ZKT_END


def native_actions(runtime):
    return ACTION_START + '''_ziokt_native_descriptor() {
    "${PYTHON_CMD:-python3}" - "$@" <<'PY_ZIOKT_NATIVE_DESCRIPTOR'
''' + runtime + '''
try:
    raise SystemExit(native_descriptor_main(sys.argv[1:]))
except ProtocolError as exc:
    print(exc.code, file=sys.stderr)
    raise SystemExit(2)
PY_ZIOKT_NATIVE_DESCRIPTOR
}
_ziokt_native_dispatch() {
    [ $# -eq 1 ] || return 2
    local descriptor action resource
    descriptor=$(_ziokt_native_descriptor "$CORIUM_ROOT" "$CORIUM_NETWORK_ID" "$1") || return 2
    action=$(jq -er '.action' <<< "$descriptor") || return 2
    resource=$(jq -er '.resource' <<< "$descriptor") || return 2
    case "$action" in
        wiki.create)
            local native_input commit_message
            native_input=$(mktemp -d "${VAR_LIB_CORIUM_DIR}/ziokt/wiki-input.XXXXXX") || return 2
            CORIUM_TEMP_ITEMS+=("$native_input")
            jq -j '.arguments.content' <<< "$descriptor" > "$native_input/content.md" || return 2
            chmod 600 "$native_input/content.md"
            commit_message=$(jq -er '.arguments.message' <<< "$descriptor") || return 2
            corix_wiki create "$resource" --file "$native_input/content.md" --message "$commit_message"
            ;;
        snapshot.create) corix_snapshot_create "$resource" ;;
        strata.create)
            local package_manager
            package_manager=$(jq -er '.arguments.package_manager' <<< "$descriptor") || return 2
            corix_strata_create "$resource" "$package_manager"
            ;;
        chain.mine) blockchain_mine_block ;;
        identity.register|content.publish|zkn.transfer|compute.submit|naming.submit)
            local transaction_type transaction_payload
            transaction_type=$(jq -er '.binding_evidence.transaction_type' <<< "$descriptor") || return 2
            transaction_payload=$(jq -ec '.binding_evidence.payload' <<< "$descriptor") || return 2
            blockchain_create_transaction "$transaction_type" "$transaction_payload"
            ;;
        compute.run)
            local engine_id compute_work
            engine_id=${resource#compute:}
            compute_work="${VAR_LIB_CORIUM_DIR}/ziokt/compute-$1"
            mkdir -m 700 "$compute_work" || return 2
            (
                cd "$compute_work" || exit 2
                ulimit -f 128 || exit 2
                corix_compute run --engine "$engine_id" || exit 2
            ) || return 2
            _ziokt_native_compute_result "$CORIUM_ROOT" "$CORIUM_NETWORK_ID" "$1"
            ;;
        recovery.checkpoint)
            local checkpoint_height checkpoint_path
            checkpoint_height=$(jq -er '.binding_evidence.height' <<< "$descriptor") || return 2
            checkpoint_path="${VAR_LIB_CORIUM_DIR}/ziokt/checkpoints/$1.json"
            mkdir -p "${VAR_LIB_CORIUM_DIR}/ziokt/checkpoints" || return 2
            chmod 700 "${VAR_LIB_CORIUM_DIR}/ziokt/checkpoints"
            _internal_export_chain_state "$checkpoint_height" "$checkpoint_path" "" || return 2
            chmod 600 "$checkpoint_path"
            ;;
        recovery.restore)
            local checkpoint_source
            checkpoint_source=$(jq -er '.binding_evidence.source' <<< "$descriptor") || return 2
            _internal_import_phoenix_state "$checkpoint_source"
            ;;
        *) return 2 ;;
    esac
}
_ziokt_transport_send() {
    [ "${CORIUM_CONFIG_CACHE[ziokt_enabled]:-FALSE}" = TRUE ] || return 80
    "${PYTHON_CMD:-python3}" - "$CORIUM_ROOT" "$CORIUM_NETWORK_ID" "$@" <<'PY_ZIOKT_NATIVE_TRANSPORT'
''' + runtime + '''
try:
    raise SystemExit(native_transport_main(sys.argv[1:]))
except (ProtocolError, OSError, ValueError, ImportError) as exc:
    print(getattr(exc, "code", "NATIVE_TRANSPORT_UNAVAILABLE"), file=sys.stderr)
    raise SystemExit(2)
PY_ZIOKT_NATIVE_TRANSPORT
}
''' + '''_ziokt_native_compute_result() {
    "${PYTHON_CMD:-python3}" - "$@" <<'PY_ZIOKT_NATIVE_COMPUTE'
''' + runtime + '''
try:
    compute_finish(sys.argv[1:])
except (ProtocolError, OSError, ValueError) as exc:
    print(getattr(exc, "code", "NATIVE_COMPUTE_FAILED"), file=sys.stderr)
    raise SystemExit(2)
PY_ZIOKT_NATIVE_COMPUTE
}
_ziokt_asset_engine() {
    "${PYTHON_CMD:-python3}" - "$@" <<'PY_ZIOKT_NATIVE_ASSETS'
''' + runtime + '''
try:
    raise SystemExit(asset_engine_main(sys.argv[1:]))
except (ProtocolError,OSError,ValueError,sqlite3.Error) as exc:
    print(getattr(exc,"code","NATIVE_ASSET_FAILED"),file=sys.stderr)
    raise SystemExit(2)
PY_ZIOKT_NATIVE_ASSETS
}
_ziokt_zkn_after_pack() {
    local mint_payload
    _ziokt_asset_engine forward "$BLOCKCHAIN_DB" "$CORIUM_NETWORK_ID" "$CORIUM_ROOT" || return 1
    mint_payload=$(_ziokt_asset_engine snapshot "$BLOCKCHAIN_DB" "$CORIUM_NETWORK_ID" "$CORIUM_ROOT" "$1") || return 1
    [ -z "$mint_payload" ] && return 0
    blockchain_create_transaction zkn_mint "$mint_payload" >/dev/null
}
''' + ACTION_END


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shadow6", type=Path, default=ROOT.parent / "Shadow6")
    parser.add_argument("--corium", type=Path, default=ROOT.parent / "Corium")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    def namespace(name,source):
        source=source.replace('import dna_protocol as DNA','DNA=_native_dna')
        source=source.replace('from dna_protocol import encoded, require, integer, public_key','encoded,require,integer,public_key=_native_dna.encoded,_native_dna.require,_native_dna.integer,_native_dna.public_key')
        source=source.replace('import cooperative_protocol as Cooperative','Cooperative=_native_cooperative').replace('import recovery_consensus as Recovery','Recovery=_native_recovery')
        return 'def _load_'+name+'():\n'+textwrap.indent(source,'    ')+'\n    return locals()\n'+name+'=__import__("types").SimpleNamespace(**_load_'+name+'())\n'
    runtime = (ROOT / "spec/provider_runtime.py").read_text()
    operations = (ROOT / "spec/operation_runtime.py").read_text()
    runtime += '\n' + operations
    runtime += '\n' + (ROOT / "spec/recovery_runtime.py").read_text()
    runtime += '\n' + (ROOT / "spec/governance_runtime.py").read_text()
    runtime += '\n' + (ROOT / "spec/compute_runtime.py").read_text()
    # Corium owns the GIMPS algorithm. The specification is a generated mirror.
    gimps_runtime=(args.corium/'gimps_consensus.py').read_text()
    gimps_library=gimps_runtime.split("\nif __name__ == '__main__':",1)[0]
    runtime+='\ndef _load_native_gimps():\n'+textwrap.indent(gimps_library,'    ')+'\n    return locals()\n_native_gimps=__import__("types").SimpleNamespace(**_load_native_gimps())\n'

    cooperative_sources={name:(ROOT/'spec'/name).read_text() for name in ('dna_protocol.py','cooperative_protocol.py','recovery_consensus.py','cooperative_consensus.py')}
    cooperative_embedded=''.join(namespace(name,cooperative_sources[file]) for name,file in
        (('_native_dna','dna_protocol.py'),('_native_cooperative','cooperative_protocol.py'),('_native_recovery','recovery_consensus.py'),('_native_cooperative_consensus','cooperative_consensus.py')))
    runtime += '\n'+cooperative_embedded
    shielded_runtime=(ROOT / 'spec/shielded_runtime.py').read_text()
    shielded_target=args.corium/'shielded_ownership.py'
    runtime += '\n' + shielded_runtime
    runtime += '\n' + (ROOT / "spec/asset_runtime.py").read_text()
    runtime += '\n' + (ROOT / "spec/naming_runtime.py").read_text()
    runtime += '\n' + (ROOT / "spec/data_runtime.py").read_text()
    runtime += '\n' + (ROOT / "spec/native_transport.py").read_text()
    zkt = (ROOT / "spec/zkt_runtime.py").read_text()
    target = args.shadow6 / "Ziokt-Support/zfcp_runtime.py"
    coordinator_target = ROOT / "ziokt/_runtime.py"
    static_target = ROOT / "ziokt/static_site.py"
    static_runtime=(ROOT/"spec/static_site_runtime.py").read_text()
    currency_target = ROOT / "ziokt/_zkt_runtime.py"
    currency = 'from ._runtime import *\n' + zkt
    script = args.corium / "corix_v108.sh"
    source = script.read_text()
    block = embedded(runtime, zkt)
    if START in source:
        prefix, tail = source.split(START, 1)
        old, suffix = tail.split(END, 1)
        updated = prefix + block + suffix
    else:
        marker = "set -o pipefail\n"
        if source.count(marker) != 1:
            raise SystemExit("native strict-mode anchor is ambiguous")
        updated = source.replace(marker, marker + "\n" + block, 1)
    engine = zkt_engine(runtime, zkt)
    if ZKT_START in updated:
        prefix, tail = updated.split(ZKT_START, 1)
        _, suffix = tail.split(ZKT_END, 1)
        updated = prefix + engine + suffix
    else:
        updated = updated.replace(END, END + '\n' + engine, 1)
    actions = native_actions(runtime)
    if ACTION_START in updated:
        prefix, tail = updated.split(ACTION_START, 1)
        _, suffix = tail.split(ACTION_END, 1)
        updated = prefix + actions + suffix
    else:
        updated = updated.replace(END, END + '\n' + actions, 1)
    updated=updated.replace('ziokt_identity_register|ziokt_content|zkn_mint|zkn_transfer)', 'ziokt_identity_register|ziokt_content|zkn_mint|zkn_transfer|zkn_private_transfer|zkc_issue|zkn_shield_deposit|zkn_shield_transfer|zkn_shield_withdraw|privacy_review_request|privacy_review_vote|privacy_review_revoke|privacy_review_disclose)')
    updated=updated.replace('zkn_transfer|zkn_private_transfer)', 'zkn_transfer|zkn_private_transfer|zkc_issue)')
    updated=updated.replace('ziokt_identity_register|ziokt_content|zkn_mint|zkn_transfer|zkn_private_transfer|zkc_issue)','ziokt_identity_register|ziokt_content|zkn_mint|zkn_transfer|zkn_private_transfer|zkc_issue|zkn_shield_deposit|zkn_shield_transfer|zkn_shield_withdraw|privacy_review_request|privacy_review_vote|privacy_review_revoke|privacy_review_disclose)')
    validation_anchor='    # --- Step 3: State & Logic Verification by Type ---\n    case "$tx_type" in\n'
    validation_hook='''        ziokt_identity_register|ziokt_content|zkn_mint|zkn_transfer|zkn_private_transfer|zkc_issue|zkn_shield_deposit|zkn_shield_transfer|zkn_shield_withdraw|privacy_review_request|privacy_review_vote|privacy_review_revoke|privacy_review_disclose)
            _ziokt_asset_engine validate "$BLOCKCHAIN_DB" "$CORIUM_NETWORK_ID" "$tx_type" "$tx_payload" "$sender_id" || return 1
            ;;
'''
    if validation_hook not in updated:
        if updated.count(validation_anchor)!=1: raise SystemExit('native asset validation anchor ambiguous')
        updated=updated.replace(validation_anchor,validation_anchor+validation_hook,1)
    apply_anchor='            # case 语句现在只负责改变数据库状态。\n            case "$tx_type" in\n'
    apply_hook='''                ziokt_identity_register|ziokt_content|zkn_mint|zkn_transfer|zkn_private_transfer|zkc_issue|zkn_shield_deposit|zkn_shield_transfer|zkn_shield_withdraw|privacy_review_request|privacy_review_vote|privacy_review_revoke|privacy_review_disclose)
                    _ziokt_asset_engine apply "$BLOCKCHAIN_DB" "$CORIUM_NETWORK_ID" "$tx_type" "$tx_payload" "$sender_id" "$tx_hash" "$height" || return 1
                    ;;
'''
    if apply_hook not in updated:
        if updated.count(apply_anchor)!=1: raise SystemExit('native asset apply anchor ambiguous')
        updated=updated.replace(apply_anchor,apply_anchor+apply_hook,1)
    mint_anchor='    db_execute_safe "$BLOCKCHAIN_DB" "INSERT OR REPLACE INTO chain_state VALUES (\'chain_info\',%s);" "$block_hash|$height" || return 1\n'
    mint_hook='    _ziokt_zkn_after_pack "$block_hash" || return 1\n'
    if mint_hook not in updated:
        if updated.count(mint_anchor)!=1: raise SystemExit('native packed NFT anchor ambiguous')
        updated=updated.replace(mint_anchor,mint_anchor+mint_hook,1)
    privacy_admission_anchor = '    # Store the complete transaction details in the local database.\n'
    updated = updated.replace('zkn_shield_*|privacy_review_*) tx_data=$(jq -cS .',
                              'zkn_shield_*|privacy_review_*|zkn_mint|zkn_transfer|zkn_private_transfer|zkc_issue|zkc_transfer|cooperative_command) tx_data=$(jq -cS .')
    privacy_admission_hook = '''    # Native signed assets use the same atomic admission as MCP/native plans.
    case "$tx_type" in
        zkn_shield_*|privacy_review_*|zkn_mint|zkn_transfer|zkn_private_transfer|zkc_issue|zkc_transfer|cooperative_command)
            local privacy_tx
            privacy_tx=$(jq -cn --arg type "$tx_type" --argjson data "$tx_data" --argjson ts "$timestamp" --arg pk "$public_key" --arg sig "$signature" '{type:$type,data:$data,timestamp:$ts,public_key:$pk,signature:$sig}') || return 1
            _ziokt_asset_engine submit-asset "$BLOCKCHAIN_DB" "$CORIUM_NETWORK_ID" "$CORIUM_ROOT" "$privacy_tx" || return 1
            return 0
            ;;
    esac

'''
    if privacy_admission_hook not in updated:
        if updated.count(privacy_admission_anchor) != 1: raise SystemExit('native privacy admission anchor ambiguous')
        updated = updated.replace(privacy_admission_anchor, privacy_admission_hook + privacy_admission_anchor, 1)
    # Static frontend helpers execute in Corium's separate Gateway namespace.
    static_start='# BEGIN ZIOKT STATIC SITE HELPERS\n'
    static_end='# END ZIOKT STATIC SITE HELPERS\n'
    static_block=static_start+(ROOT/'spec/static_site_runtime.py').read_text()+'\n'+static_end
    if static_start in updated:
        left,tail=updated.split(static_start,1);_,right=tail.split(static_end,1)
        updated=left+static_block+right
    else:
        anchor='class CoriumGatewayHandler(http.server.BaseHTTPRequestHandler):'
        if updated.count(anchor)!=1:raise SystemExit('native Gateway static helper anchor ambiguous')
        updated=updated.replace(anchor,static_block+'\n'+anchor,1)
    openci_runtime=(ROOT/'spec/openci_consensus.py').read_text()
    openci_target=args.corium/'openci_consensus.py'
    openci_coordinator=ROOT/'openci/_consensus.py'
    openci_start='# BEGIN ZIOKT OPENCI CONSENSUS V1\n';openci_end='# END ZIOKT OPENCI CONSENSUS V1\n'
    openci_digest=hashlib.sha256(openci_runtime.encode()).hexdigest()
    openci_embedded=openci_runtime.replace('EMBEDDED_SOURCE_DIGEST = None','EMBEDDED_SOURCE_DIGEST = '+repr(openci_digest),1)
    openci_block=openci_start+'''_corium_openci_consensus() (
    ulimit -t 5 -v 262144 || exit 2
    "${PYTHON_CMD:-python3}" - "$@" <<'PY_CORIUM_OPENCI_CONSENSUS'
'''+openci_embedded+'''
try:
    main(sys.argv[1:])
except (ValueError,TypeError,KeyError,InvalidSignature,sqlite3.Error):
    print('OPENCI_CONSENSUS_REJECTED',file=sys.stderr)
    raise SystemExit(2)
PY_CORIUM_OPENCI_CONSENSUS
)
'''+openci_end
    if openci_start in updated:
        left,tail=updated.split(openci_start,1);_,right=tail.split(openci_end,1);updated=left+openci_block+right
    else:
        anchor='_validate_single_transaction() {'
        if updated.count(anchor)!=1:raise SystemExit('native OpenCI validation anchor ambiguous')
        updated=updated.replace(anchor,openci_block+'\n'+anchor,1)
    work_policy=(ROOT/'spec/work_weight_policy.py').read_text()
    work_runtime=(ROOT/'spec/work_consensus.py').read_text()
    dna_runtime=(ROOT/'spec/dna_protocol.py').read_text()
    cooperative_runtime=(ROOT/'spec/cooperative_protocol.py').read_text()
    recovery_runtime=(ROOT/'spec/recovery_consensus.py').read_text()
    extra_work_sources=cooperative_sources
    cooperative_consensus_runtime=cooperative_sources['cooperative_consensus.py']
    recovery_embedded=cooperative_embedded
    recovery_embedded+='DNA,Cooperative,Recovery,CooperativeConsensus=_native_dna,_native_cooperative,_native_recovery,_native_cooperative_consensus\n'
    work_target=args.corium/'work_consensus.py';work_policy_target=args.corium/'work_weight_policy.py'
    work_digest=hashlib.sha256(b'Corium/NativeWorkVerifier/v3\0'+b'\0'.join(value.encode()for value in (work_runtime,work_policy,dna_runtime,recovery_runtime,cooperative_runtime,cooperative_consensus_runtime))).hexdigest()
    work_embedded=work_runtime.replace('EMBEDDED_SOURCE_DIGEST = None','EMBEDDED_SOURCE_DIGEST = '+repr(work_digest),1)
    for line in ('import dna_protocol as DNA','import recovery_consensus as Recovery','import cooperative_protocol as Cooperative','import cooperative_consensus as CooperativeConsensus'):
        work_embedded=work_embedded.replace(line,'')
    work_embedded=work_embedded.replace('from work_weight_policy import validate,commitment,verify_work,work_digest,integer,encoded,MAX_WEIGHT','')
    work_embedded=work_embedded.replace("if __name__=='__main__':main(__import__('sys').argv[1:])",'')
    work_start='# BEGIN CORIUM NATIVE WORK CONSENSUS V2\n';work_end='# END CORIUM NATIVE WORK CONSENSUS V2\n'
    work_primitives='def _native_work_primitives():\n'+textwrap.indent(work_policy,'    ')+'\n    return locals()\n_work_primitives=_native_work_primitives()\nvalidate,commitment,verify_work,work_digest,integer,encoded,MAX_WEIGHT=(_work_primitives[k] for k in ("validate","commitment","verify_work","work_digest","integer","encoded","MAX_WEIGHT"))\n'
    work_block=work_start+'''_corium_work_consensus() (
    ulimit -t 15 -v 262144 || exit 2
    "${PYTHON_CMD:-python3}" - "$@" <<'PY_CORIUM_WORK_CONSENSUS'
'''+work_primitives+'\n'+recovery_embedded+'\n'+work_embedded+'\n'+(ROOT/'spec/replay_anchor_runtime.py').read_text()+'''
import sys
try:
    if sys.argv[1]=='replay-anchor':
        result=replay_anchor(sys.argv[2],sys.argv[3],int(sys.argv[4]),*sys.argv[5:8]);print(json.dumps(result,separators=(',',':')))
    else:main(sys.argv[1:])
except (ValueError,TypeError,KeyError,InvalidSignature,sqlite3.Error):
    print('WORK_CONSENSUS_REJECTED',file=sys.stderr)
    raise SystemExit(2)
PY_CORIUM_WORK_CONSENSUS
)
'''+work_end
    if work_start in updated:
        left,tail=updated.split(work_start,1);_,right=tail.split(work_end,1);updated=left+work_block+right
    else:
        anchor='_validate_single_transaction() {'
        if updated.count(anchor)!=1:raise SystemExit('native work validation anchor ambiguous')
        updated=updated.replace(anchor,work_block+'\n'+anchor,1)
    # Keep standalone monolith verification identical to the authoritative module.
    anchor="<<'PY_CORIUM_GIMPS_CONSENSUS'\n"
    if updated.count(anchor)!=1:raise SystemExit('native GIMPS source anchor ambiguous')
    before,tail=updated.split(anchor,1);_,after=tail.split('\nPY_CORIUM_GIMPS_CONSENSUS',1)
    updated=before+anchor+gimps_runtime.rstrip()+'\nPY_CORIUM_GIMPS_CONSENSUS'+after
    if args.check:
        mismatches = []
        if (ROOT/'spec/gimps_consensus.py').read_text()!=gimps_runtime:mismatches.append('spec/gimps_consensus.py')
        for name,expected in extra_work_sources.items():
            target_source=args.corium/name
            if not target_source.is_file() or target_source.read_text()!=expected:mismatches.append(str(target_source))
        for name,expected in extra_work_sources.items():
            path=args.corium/name
            if not path.is_file()or path.read_text()!=expected:mismatches.append(str(path))
        for path, expected in ((target, runtime), (script, updated), (shielded_target, shielded_runtime), (openci_target,openci_runtime), (openci_coordinator,openci_runtime), (work_target,work_runtime), (work_policy_target,work_policy),
                               (coordinator_target, runtime), (currency_target, currency), (static_target,static_runtime)):
            if not path.is_file() or path.read_text() != expected:
                mismatches.append(str(path))
        if mismatches:
            raise SystemExit("native provider protocol drift: " + ", ".join(mismatches) +
                             "; verify native-sources.lock.json against the published protocol copies")
        print("Native protocol copies match Ziokt specification")
    else:
        (ROOT/'spec/gimps_consensus.py').write_text(gimps_runtime)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(runtime)
        shielded_target.write_text(shielded_runtime)
        work_target.write_text(work_runtime)
        for name,value in extra_work_sources.items():(args.corium/name).write_text(value)
        work_policy_target.write_text(work_policy)
        openci_target.write_text(openci_runtime)
        openci_coordinator.write_text(openci_runtime)
        coordinator_target.write_text(runtime)
        static_target.write_text(static_runtime)
        currency_target.write_text(currency)
        script.write_text(updated)


if __name__ == "__main__":
    main()

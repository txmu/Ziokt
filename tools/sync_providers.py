#!/usr/bin/env python3
"""Pin the same local protocol in independent native deliveries; never run them."""
import argparse
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
''' + ACTION_END


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shadow6", type=Path, default=ROOT.parent / "Shadow6")
    parser.add_argument("--corium", type=Path, default=ROOT.parent / "Corium")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    runtime = (ROOT / "spec/provider_runtime.py").read_text()
    operations = (ROOT / "spec/operation_runtime.py").read_text()
    runtime += '\n' + operations
    runtime += '\n' + (ROOT / "spec/recovery_runtime.py").read_text()
    runtime += '\n' + (ROOT / "spec/governance_runtime.py").read_text()
    runtime += '\n' + (ROOT / "spec/compute_runtime.py").read_text()
    runtime += '\n' + (ROOT / "spec/data_runtime.py").read_text()
    runtime += '\n' + (ROOT / "spec/native_transport.py").read_text()
    zkt = (ROOT / "spec/zkt_runtime.py").read_text()
    target = args.shadow6 / "Ziokt-Support/zfcp_runtime.py"
    coordinator_target = ROOT / "ziokt/_runtime.py"
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
    if args.check:
        if (not target.is_file() or target.read_text() != runtime or updated != source or
                not coordinator_target.is_file() or coordinator_target.read_text() != runtime or
                not currency_target.is_file() or currency_target.read_text() != currency):
            raise SystemExit("native provider protocol drift")
        print("Native protocol copies match Ziokt specification")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(runtime)
        coordinator_target.write_text(runtime)
        currency_target.write_text(currency)
        script.write_text(updated)


if __name__ == "__main__":
    main()

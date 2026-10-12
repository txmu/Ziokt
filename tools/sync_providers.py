#!/usr/bin/env python3
"""Pin the same local protocol in independent native deliveries; never run them."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = "# BEGIN ZIOKT LOCAL PROVIDER (generated from Ziokt/spec/provider_runtime.py)\n"
END = "# END ZIOKT LOCAL PROVIDER\n"
ACTION_START = "# BEGIN ZIOKT NATIVE ACTIONS (generated, fixed monolith dispatcher)\n"
ACTION_END = "# END ZIOKT NATIVE ACTIONS\n"


def embedded(runtime):
    return START + '''# This early machine entry deliberately precedes native locks/recovery/TUI.
if [[ "${BASH_SOURCE[0]}" -ef "$0" && "${1:-}" == ziokt ]]; then
    shift
    command -v python3 >/dev/null 2>&1 || { printf '%s\\n' 'Ziokt requires Python 3.' >&2; exit 2; }
    # Python source uses stdin; request bytes remain on inherited descriptor 3.
    _ZIOKT_CORIUM_SOURCE="${BASH_SOURCE[0]}" python3 - "$@" 3<&0 <<'PY_ZIOKT_PROVIDER'
''' + runtime + '''
sys.dont_write_bytecode = True
raise SystemExit(main("corium", argv=sys.argv[1:], rpc_stream=os.fdopen(3, "rb", closefd=False)))
PY_ZIOKT_PROVIDER
    exit $?
fi
''' + END


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
    runtime += '\n' + (ROOT / "spec/data_runtime.py").read_text()
    runtime += '\n' + (ROOT / "spec/native_transport.py").read_text()
    target = args.shadow6 / "Ziokt-Support/zfcp_runtime.py"
    coordinator_target = ROOT / "ziokt/_runtime.py"
    script = args.corium / "corix_v108.sh"
    source = script.read_text()
    block = embedded(runtime)
    if START in source:
        prefix, tail = source.split(START, 1)
        old, suffix = tail.split(END, 1)
        updated = prefix + block + suffix
    else:
        marker = "set -o pipefail\n"
        if source.count(marker) != 1:
            raise SystemExit("native strict-mode anchor is ambiguous")
        updated = source.replace(marker, marker + "\n" + block, 1)
    actions = native_actions(runtime)
    if ACTION_START in updated:
        prefix, tail = updated.split(ACTION_START, 1)
        _, suffix = tail.split(ACTION_END, 1)
        updated = prefix + actions + suffix
    else:
        updated = updated.replace(END, END + '\n' + actions, 1)
    if args.check:
        if (not target.is_file() or target.read_text() != runtime or updated != source or
                not coordinator_target.is_file() or coordinator_target.read_text() != runtime):
            raise SystemExit("native provider protocol drift")
        print("Native protocol copies match Ziokt specification")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(runtime)
        coordinator_target.write_text(runtime)
        script.write_text(updated)


if __name__ == "__main__":
    main()

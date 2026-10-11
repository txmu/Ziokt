#!/usr/bin/env python3
"""Pin the same local protocol in independent native deliveries; never run them."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = "# BEGIN ZIOKT LOCAL PROVIDER (generated from Ziokt/spec/provider_runtime.py)\n"
END = "# END ZIOKT LOCAL PROVIDER\n"
ZKT_START = "# BEGIN ZIOKT ZKT ENGINE (generated, optional native asset)\n"
ZKT_END = "# END ZIOKT ZKT ENGINE\n"


def embedded(runtime, zkt):
    return START + '''# This early machine entry deliberately precedes native locks/recovery/TUI.
if [[ "${BASH_SOURCE[0]}" -ef "$0" && "${1:-}" == ziokt ]]; then
    shift
    command -v python3 >/dev/null 2>&1 || { printf '%s\\n' 'Ziokt requires Python 3.' >&2; exit 2; }
    # Python source uses stdin; request bytes remain on inherited descriptor 3.
    python3 - "$@" 3<&0 <<'PY_ZIOKT_PROVIDER'
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
raise SystemExit(zkt_engine_main())
PY_ZIOKT_ZKT_ENGINE
}
''' + ZKT_END


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shadow6", type=Path, default=ROOT.parent / "Shadow6")
    parser.add_argument("--corium", type=Path, default=ROOT.parent / "Corium")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    runtime = (ROOT / "spec/provider_runtime.py").read_text()
    operations = (ROOT / "spec/operation_runtime.py").read_text()
    runtime += '\n' + operations
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

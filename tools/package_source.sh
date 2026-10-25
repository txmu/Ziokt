#!/usr/bin/env bash
# Text-only v1.0 joint source packaging; no native compilation.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/Ziokt/tools/package_joint_source.py" ]]; then
    repositories_root=$SCRIPT_DIR
else
    repositories_root=$(cd "$SCRIPT_DIR/../.." && pwd)
fi
repositories_root=${ZIOKT_REPOSITORIES_ROOT:-$repositories_root}
output="$repositories_root/Ziokt-Corium-Shadow6-source-v1.0.zip"
for repository in Ziokt Corium Shadow6 Ziokt-Releases; do
    if [[ -d "$repositories_root/$repository/.git" ]]; then
        if [[ -n "$(git -C "$repositories_root/$repository" status --porcelain)" ]]; then
            printf 'Refusing to package uncommitted sources: %s\n' "$repository" >&2
            exit 1
        fi
        git -C "$repositories_root/$repository" log -1 --format="$repository %H"
    fi
done
arguments=(--repositories-root "$repositories_root" --output "$output")
if [[ -n "${ZIOKT_RELEASE_EVIDENCE:-}" ]]; then arguments+=(--evidence "$ZIOKT_RELEASE_EVIDENCE"); fi
python3 "$repositories_root/Ziokt/tools/package_joint_source.py" "${arguments[@]}"
python3 - "$output" <<'PY'
import datetime,hashlib,pathlib,shutil,sys
source=pathlib.Path(sys.argv[1]);digest=hashlib.sha256(source.read_bytes()).hexdigest()
for tag in ('1.0',datetime.datetime.now(datetime.timezone.utc).date().isoformat()):
    alias=source.with_name('Ziokt-Corium-Shadow6-source-'+tag+'.zip')
    shutil.copyfile(source,alias)
    alias.with_suffix('.zip.sha256').write_text(digest+'  '+alias.name+'\n')
print(digest+'  '+source.name)
PY

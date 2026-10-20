#!/usr/bin/env bash
# CI only. Buildroot owns the dependency graph and staging/install phases.
set -euo pipefail
: "${GITHUB_ACTIONS:?Heavy validation must run on CI}"
target=${1:?target required}
case "$target" in x86_64|aarch64) ;; *) exit 2 ;; esac
repo_root=$(pwd)
build_area="$RUNNER_TEMP/openci-$target"
mkdir -p "$build_area/evidence" "$build_area/overlay/etc"
source_revision=$(python3 -c 'import json;print(json.load(open("ci/openci/buildroot.lock.json"))["revision"])')
source_url=$(python3 -c 'import json;print(json.load(open("ci/openci/buildroot.lock.json"))["repository"])')
defconfig=$(python3 -c 'import json,sys;print(json.load(open("ci/openci/buildroot.lock.json"))["targets"][sys.argv[1]])' "$target")
git init "$build_area/source"
git -C "$build_area/source" remote add origin "$source_url"
git -C "$build_area/source" fetch --depth 1 origin "$source_revision"
git -C "$build_area/source" checkout --detach FETCH_HEAD
test "$(git -C "$build_area/source" rev-parse HEAD)" = "$source_revision"
printf '%s\n' "$GITHUB_SHA" > "$build_area/overlay/etc/openci-build-id"
out="$build_area/output"
export BR2_DL_DIR="$repo_root/.ci-cache/buildroot-downloads"
export CCACHE_DIR="$repo_root/.ci-cache/ccache-$target"
mkdir -p "$BR2_DL_DIR" "$CCACHE_DIR"
make -C "$build_area/source" O="$out" "$defconfig"
cat >> "$out/.config" <<EOF
BR2_CCACHE=y
BR2_CCACHE_DIR="$CCACHE_DIR"
BR2_ROOTFS_OVERLAY="$build_area/overlay"
BR2_TARGET_GENERIC_HOSTNAME="openci"
# BR2_PACKAGE_HOST_QEMU is not set
EOF
if [ "$target" = x86_64 ]; then
    printf 'BR2_TARGET_GENERIC_GETTY_PORT="ttyS0"\n' >> "$out/.config"
else
    printf 'BR2_TARGET_GENERIC_GETTY_PORT="ttyAMA0"\n' >> "$out/.config"
fi
make -C "$build_area/source" O="$out" olddefconfig
cp "$out/.config" "$build_area/evidence/buildroot.config"
# Bootstrap host tools and cross compiler locally on the dedicated CI VM.
# Do not distribute Buildroot package install/staging hooks across workers.
make -C "$build_area/source" O="$out" -j2 toolchain host-ccache 2>&1 | tee "$build_area/evidence/toolchain.log"
export PATH="$out/host/bin:$PATH"
export DISTCC_HOSTS='127.0.0.1:13632/2 127.0.0.1:13633/2'
export DISTCC_LOG="$build_area/evidence/distcc-client.log"
export DISTCC_VERBOSE=1
export DISTCC_FALLBACK=0
# These workers are processes in one ephemeral GitHub VM. They are NOT a
# multi-host trust test, and have no production credentials or public listener.
# Restrict workers to the actual compiler entrypoints in this pinned build.
export DISTCC_CMDLIST="$build_area/compiler-allowlist"
find "$out/host/bin" -maxdepth 1 \( -name '*-gcc' -o -name '*-g++' -o -name '*-gcc.br_real' -o -name '*-g++.br_real' \) -print > "$DISTCC_CMDLIST"
printf '/usr/bin/gcc\n/usr/bin/g++\n/usr/bin/cc\n/usr/bin/c++\n' >> "$DISTCC_CMDLIST"
workers=()
cleanup() {
    for worker in "${workers[@]}"; do kill "$worker" 2>/dev/null || true; done
    for worker in "${workers[@]}"; do wait "$worker" 2>/dev/null || true; done
}
trap cleanup EXIT
for port in 13632 13633; do
    distccd --daemon --no-detach --listen 127.0.0.1 --allow 127.0.0.1 --port "$port" --jobs 2 --job-lifetime 120 --log-level info --log-file "$build_area/evidence/distccd-$port.log" &
    workers+=("$!")
done
python3 ci/openci/distcc_probe.py "$out" "$build_area/evidence"
# ccache calls distcc only on cache misses; ordinary preprocessing stays local.
export CCACHE_PREFIX=distcc
export CCACHE_COMPILERCHECK=content
make -C "$build_area/source" O="$out" -j4 2>&1 | tee "$build_area/evidence/build.log"
unset CCACHE_PREFIX
make -s -C "$build_area/source" O="$out" show-info > "$build_area/evidence/buildroot-packages.json"
"$out/host/bin/ccache" --show-stats > "$build_area/evidence/ccache-stats.txt"
python3 ci/openci/qemu_boot.py "$target" "$out/images" "$build_area/evidence" "$GITHUB_SHA"
python3 ci/openci/evidence.py "$build_area" "$source_revision" "$GITHUB_SHA" "$target"

#!/usr/bin/env bash
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true ]]
repo_root=$(pwd)
work="$RUNNER_TEMP/openci-light"
mkdir -p "$work" dist/light-compiler
revision=$(python3 -c 'import json;print(json.load(open("ci/openci/light/source.lock.json"))["revision"])')
git init "$work/tinycc"
git -C "$work/tinycc" fetch --depth 1 https://github.com/TinyCC/tinycc.git "$revision"
git -C "$work/tinycc" checkout --detach FETCH_HEAD
[[ $(git -C "$work/tinycc" rev-parse HEAD) == "$revision" ]]
for target in x86_64 aarch64; do
  cpu=$target
  define=TCC_TARGET_X86_64
  if [[ $target == aarch64 ]]; then cpu=arm64; define=TCC_TARGET_ARM64; fi
  build="$work/$target"
  cp -a "$work/tinycc" "$build"
  (
    cd "$build"
    ./configure --cpu="$cpu" --cc=cc --ar=ar --config-backtrace=no --config-bcheck=no --config-static=yes
    python3 - <<'PY_EMBED'
import json
from pathlib import Path
Path('tccdefs_.h').write_text('\n'.join(json.dumps(line+'\n') for line in Path('include/tccdefs.h').read_text().splitlines())+'\n')
PY_EMBED
    emcc -Oz -D"$define" -DCONFIG_TCC_STATIC=1 -DCONFIG_TCC_BACKTRACE=0 -DCONFIG_TCC_BCHECK=0 -I. libtcc.c "$repo_root/ci/openci/light/compiler.c" \
      -sMODULARIZE=1 -sEXPORT_NAME=createOpenCITcc -sENVIRONMENT=worker,node \
      -sEXPORTED_FUNCTIONS='["_openci_compile","_malloc","_free"]' \
      -sEXPORTED_RUNTIME_METHODS='["ccall","FS"]' -sFORCE_FILESYSTEM=1 \
      -sINITIAL_MEMORY=67108864 -sALLOW_MEMORY_GROWTH=0 \
      -sSTACK_SIZE=2097152 -sNO_EXIT_RUNTIME=1 -o "$repo_root/dist/light-compiler/$target.js"
  )
done
git -C "$work/tinycc" archive --format=tar --prefix=tinycc/ "$revision" | gzip -n > dist/light-compiler/tinycc-source.tar.gz
mkdir -p dist/light-compiler/build-recipe
cp ci/openci/light/compiler.c ci/openci/light/build.sh ci/openci/light/source.lock.json dist/light-compiler/build-recipe/
cp "$work/tinycc/COPYING" dist/light-compiler/TINYCC-LICENSE
cp ci/openci/light/source.lock.json dist/light-compiler/SOURCE.json
python3 - <<'PY'
import hashlib,json
from pathlib import Path
root=Path('dist/light-compiler');targets={}
for arch in ('x86_64','aarch64'):
    files={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in (arch+'.js',arch+'.wasm')}
    digest=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    targets[arch]={'files':files,'image':'openci/tcc-wasm-'+arch+'@sha256:'+digest}
(root/'manifest.json').write_text(json.dumps({'schema':'openci.light-compiler.v1','source_revision':json.loads((root/'SOURCE.json').read_text())['revision'],'corresponding_source':{'file':'tinycc-source.tar.gz','sha256':hashlib.sha256((root/'tinycc-source.tar.gz').read_bytes()).hexdigest()},'targets':targets,'input_bytes':131072,'memory_bytes':67108864,'output_bytes':1048576},indent=2)+'\n')
PY
node ci/openci/light/probe.cjs

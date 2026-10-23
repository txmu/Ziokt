#!/usr/bin/env bash
# Pinned CI dependency for the mandatory source-release proof gate.
set -euo pipefail
test -n "${RUNNER_TEMP:-}"
curl --fail --location --retry 3 --max-time 180 \
  https://github.com/leanprover/lean4/releases/download/v4.19.0/lean-4.19.0-linux.tar.zst \
  -o "$RUNNER_TEMP/lean.tar.zst"
tar --zstd -xf "$RUNNER_TEMP/lean.tar.zst" -C "$RUNNER_TEMP"
echo "$RUNNER_TEMP/lean-4.19.0-linux/bin" >> "$GITHUB_PATH"

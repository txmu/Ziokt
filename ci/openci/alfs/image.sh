#!/usr/bin/env bash
# Package a prepared root filesystem; no source downloads or compilation.
set -euo pipefail
rootfs=$1
images=$2
size=${3:-8G}
[[ -d "$rootfs" && ! -L "$images" && $(id -u) != 0 ]]
# Root owns the copied system, while the runner creates and uploads the image.
# install also repairs the directory left root-owned by an interrupted run.
sudo install -d -m 0755 -o "$(id -u)" -g "$(id -g)" -- "$images"
truncate -s "$size" "$images/rootfs.ext4"
sudo mkfs.ext4 -q -F -d "$rootfs" "$images/rootfs.ext4"
sudo chown "$(id -u):$(id -g)" -- "$images/rootfs.ext4"

#!/usr/bin/env bash
# Exercise the production packaging commands against a 32 MiB disposable image.
set -euo pipefail
[[ $(id -u) != 0 ]]
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
fixture=$(mktemp -d)
trap 'sudo rm -rf -- "$fixture"' EXIT
sudo mkdir -p "$fixture/rootfs/etc" "$fixture/images"
printf 'ALFS packaging regression\n' | sudo tee "$fixture/rootfs/etc/lfs-release" >/dev/null
# Reproduce the ownership that caused the four-hour build to fail.
[[ $(stat -c %u "$fixture/images") == 0 ]]
if touch "$fixture/images/unprivileged-probe" 2>/dev/null; then
    echo 'Fixture does not reproduce the original permission failure' >&2
    exit 1
fi
bash "$script_dir/image.sh" "$fixture/rootfs" "$fixture/images" 32M
[[ $(stat -c %u "$fixture/images") == "$(id -u)" ]]
[[ $(stat -c %u "$fixture/images/rootfs.ext4") == "$(id -u)" ]]
sudo e2fsck -f -n "$fixture/images/rootfs.ext4"
actual=$(sudo debugfs -R 'cat /etc/lfs-release' "$fixture/images/rootfs.ext4" 2>/dev/null)
[[ "$actual" == 'ALFS packaging regression' ]]
echo 'ALFS image permissions, ext4 integrity and copied root filesystem: PASS (no compilation)'

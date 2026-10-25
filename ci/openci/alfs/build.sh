#!/usr/bin/env bash
# Full official ALFS, on a disposable CI VM only. Never runs on a production node.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && $(uname -m) == x86_64 && $(id -u) != 0 ]]
work="$RUNNER_TEMP/openci-alfs"
mkdir -p "$work/evidence" "$work/downloads"
cleanup() {
  if [[ -d /mnt/openci-lfs/jhalfs/logs ]]; then
    sudo find /mnt/openci-lfs/jhalfs/logs -maxdepth 1 -type f -size -20M -exec cp -t "$work/evidence/" -- {} + || true
    sudo chown -R "$(id -u):$(id -g)" "$work/evidence" || true
  fi
  for path in /mnt/openci-lfs/run /mnt/openci-lfs/sys /mnt/openci-lfs/proc /mnt/openci-lfs/dev; do
    if mountpoint -q "$path"; then sudo umount -R "$path" || true; fi
  done
}
trap cleanup EXIT
python3 - "$work" <<'PY'
import json,subprocess,sys
from pathlib import Path
lock=json.loads(Path('ci/openci/alfs/source.lock.json').read_text());work=Path(sys.argv[1])
for name in ('jhalfs','book'):
    item=lock[name];path=work/name
    subprocess.run(['git','init',str(path)],check=True)
    subprocess.run(['git','-C',str(path),'fetch','--depth','1',item['url'],item['revision']],check=True)
    subprocess.run(['git','-C',str(path),'checkout','--detach','FETCH_HEAD'],check=True)
    assert subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip()==item['revision']
(work/'evidence/source-lock.json').write_text(json.dumps(lock,indent=2)+'\n')
PY
# The official pinned book checks all package checksums during download.
kernel_version=$(python3 -c 'import json;print(json.load(open("ci/openci/alfs/source.lock.json"))["kernel"]["version"])')
kernel_url=$(python3 -c 'import json;print(json.load(open("ci/openci/alfs/source.lock.json"))["kernel"]["url"])')
curl --fail --location --retry 4 --max-time 600 "$kernel_url" -o "$work/downloads/linux-$kernel_version.tar.xz"
python3 - "$work/downloads/linux-$kernel_version.tar.xz" <<'PY'
import hashlib,json,sys
from pathlib import Path
value=Path(sys.argv[1]);expected=json.loads(Path('ci/openci/alfs/source.lock.json').read_text())['kernel']['book_md5']
assert hashlib.md5(value.read_bytes()).hexdigest()==expected,'Official kernel checksum differs'
PY
mkdir "$work/kernel-prep"
tar -xf "$work/downloads/linux-$kernel_version.tar.xz" -C "$work/kernel-prep"
make -C "$work/kernel-prep/linux-$kernel_version" x86_64_defconfig
"$work/kernel-prep/linux-$kernel_version/scripts/config" --file "$work/kernel-prep/linux-$kernel_version/.config" --enable VIRTIO --enable VIRTIO_PCI --enable VIRTIO_BLK --enable VIRTIO_NET --enable EXT4_FS --enable DEVTMPFS --enable DEVTMPFS_MOUNT --enable SERIAL_8250 --enable SERIAL_8250_CONSOLE --disable DEBUG_INFO
make -C "$work/kernel-prep/linux-$kernel_version" olddefconfig
cp "$work/kernel-prep/linux-$kernel_version/.config" "$work/kernel.config"
printf '/dev/vda / ext4 defaults 1 1\n' > "$work/fstab"
sudo mkdir -p /mnt/openci-lfs
sudo chown "$(id -u):$(id -g)" /mnt/openci-lfs
python3 ci/openci/alfs/configure.py "$work"
# Two explicit confirmations; run_make subsequently drives the unmodified book.
python3 ci/openci/alfs/run_jhalfs.py "$work/jhalfs" 2>&1 | tee "$work/evidence/alfs-build.log"
cleanup
sudo test -x /mnt/openci-lfs/usr/bin/gcc
sudo test -s /mnt/openci-lfs/etc/lfs-release
sudo install -m 0644 "$work/kernel.config" "$work/evidence/kernel.config"
sudo install -m 0644 "$work/jhalfs/configuration" "$work/evidence/jhalfs-configuration"
# The image is an ephemeral QEMU test system; the test-only console has no password.
sudo chroot /mnt/openci-lfs /usr/bin/passwd -d root
sudo mkdir -p /mnt/openci-lfs/etc/systemd/system/getty.target.wants
sudo ln -sf /usr/lib/systemd/system/serial-getty@.service /mnt/openci-lfs/etc/systemd/system/getty.target.wants/serial-getty@ttyS0.service
printf '%s\n' "$GITHUB_SHA" | sudo tee /mnt/openci-lfs/etc/openci-build-id >/dev/null
sudo mkdir -p "$work/images" "$work/rootfs"
sudo rsync -aHAX --exclude=/sources --exclude=/jhalfs --exclude=/dev/*** --exclude=/proc/*** --exclude=/sys/*** --exclude=/run/*** /mnt/openci-lfs/ "$work/rootfs/"
sudo mkdir -p "$work/rootfs/dev" "$work/rootfs/proc" "$work/rootfs/sys" "$work/rootfs/run"
truncate -s 8G "$work/images/rootfs.ext4"
sudo mkfs.ext4 -q -F -d "$work/rootfs" "$work/images/rootfs.ext4"
sudo cp /mnt/openci-lfs/boot/vmlinuz-* "$work/images/bzImage"
sudo chown -R "$(id -u):$(id -g)" "$work/images" "$work/evidence"
python3 ci/openci/alfs/boot.py "$work/images" "$work/evidence" "$GITHUB_SHA"
python3 - "$work" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]);files={}
for path in sorted((root/'images').iterdir()):
    with path.open('rb') as source:files[path.name]=hashlib.file_digest(source,'sha256').hexdigest()
(root/'evidence/images-sha256.json').write_text(json.dumps(files,indent=2)+'\n')
PY

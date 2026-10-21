"""CI-only serial boot and guest assertions. Never infer boot success from QEMU exit."""
import json
import os
from pathlib import Path
import re
import sys
import time


def marker_pattern(name):
    if name not in {'BOOT_OK','NETWORK_OK'}:raise ValueError('unknown guest assertion')
    return r'(?m)^OPENCI_'+re.escape(name)+r'\r*$'

def main(target, images, evidence, revision):
    if os.environ.get('GITHUB_ACTIONS')!='true':raise RuntimeError('QEMU verification runs only in CI')
    import pexpect
    images, evidence = Path(images).resolve(), Path(evidence)
    rootfs = images/('rootfs.ext4' if target == 'aarch64' else 'rootfs.ext2')
    common = ['-m', '512', '-nographic', '-monitor', 'none', '-no-reboot', '-snapshot']
    if target == 'x86_64':
        binary = 'qemu-system-x86_64'
        args = ['-M', 'pc', '-kernel', str(images/'bzImage'),
                '-drive', f'file={rootfs},if=virtio,format=raw',
                '-append', 'rootwait root=/dev/vda console=ttyS0',
                '-net', 'nic,model=virtio', '-net', 'user']
    else:
        binary = 'qemu-system-aarch64'
        args = ['-M', 'virt', '-cpu', 'cortex-a53', '-kernel', str(images/'Image'),
                '-drive', f'file={rootfs},if=none,format=raw,id=hd0',
                '-device', 'virtio-blk-device,drive=hd0',
                '-append', 'rootwait root=/dev/vda console=ttyAMA0',
                '-netdev', 'user,id=eth0', '-device', 'virtio-net-device,netdev=eth0']
    started = time.monotonic()
    report = {'schema': 'openci.qemu-test.v1', 'target': target, 'state': 'running',
              'source_revision': revision, 'ssh_verified': False, 'hardware_test': False}
    with (evidence/'serial.log').open('w') as serial:
        child = pexpect.spawn(binary, args+common, encoding='utf-8', timeout=240)
        child.logfile_read = serial
        try:
            report['phase']='login'
            child.expect(r'openci login:')
            child.sendline('root')
            child.expect(r'[#] ')
            # The input line does not contain the contiguous expected output marker.
            report['phase']='rootfs-assertions'
            child.sendline("test \"$(cat /etc/openci-build-id)\" = '"+revision+"' && test -r /proc/mounts && test -d /sys/class/net/eth0 && printf 'OPENCI_%s\\n' BOOT_OK")
            child.expect(marker_pattern('BOOT_OK'))
            report['phase']='network-assertions'
            child.sendline("ip -4 addr show eth0; ip route; ping -c 1 -W 5 10.0.2.2 && printf 'OPENCI_%s\\n' NETWORK_OK")
            child.expect(marker_pattern('NETWORK_OK'))
            report['phase']='shutdown'
            child.sendline('poweroff')
            child.expect(pexpect.EOF, timeout=60)
            child.close(force=False)
            if child.exitstatus!=0:raise RuntimeError('QEMU did not exit cleanly after guest poweroff')
            serial.flush()
            if re.search(r'Kernel panic|Oops:|BUG:', (evidence/'serial.log').read_text()):
                raise RuntimeError('Kernel fault in serial log')
            report.update(state='passed', qemu_exit_code=child.exitstatus, phase='completed', serial_boot_verified=True, rootfs_build_id_verified=True,
                          network_verified=True, duration_seconds=round(time.monotonic()-started, 3))
        except BaseException as error:
            report.update(state='failed', error=type(error).__name__)
            raise
        finally:
            child.close(force=True)
            (evidence/'qemu-test.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main(*sys.argv[1:])

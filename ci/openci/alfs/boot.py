"""Serial assertions for the actual ALFS root filesystem and its own compiler."""
import json
import os
from pathlib import Path
import sys
import time


def main(images,evidence,revision):
    if os.environ.get('GITHUB_ACTIONS')!='true':raise RuntimeError('CI-only ALFS boot')
    import pexpect
    images=Path(images);evidence=Path(evidence)
    report={'schema':'openci.alfs-qemu.v1','source_revision':revision,'state':'running','image_kind':'official-jhalfs-lfs','hardware_test':False}
    started=time.monotonic()
    args=['-m','2048','-smp','2','-nographic','-monitor','none','-no-reboot','-snapshot',
          '-kernel',str(images/'bzImage'),'-drive','file='+str(images/'rootfs.ext4')+',if=virtio,format=raw',
          '-append','root=/dev/vda rw rootwait console=ttyS0 net.ifnames=0',
          '-netdev','user,id=n0','-device','virtio-net-pci,netdev=n0']
    with (evidence/'alfs-serial.log').open('w') as output:
        child=pexpect.spawn('qemu-system-x86_64',args,encoding='utf-8',timeout=300)
        child.logfile_read=output
        try:
            child.expect(r'openci-lfs login:');child.sendline('root');child.expect(r'# ')
            checks=[('ROOTFS',"test -s /etc/lfs-release && test \"$(cat /etc/openci-build-id)\" = '"+revision+"' && test -r /proc/mounts && test -d /sys/class/net/eth0"),
                    ('COMPILER',"printf 'int main(void){return 0;}\\n' >/tmp/probe.c && gcc /tmp/probe.c -o /tmp/probe && /tmp/probe && gcc -dumpmachine"),
                    ('NETWORK',"ip link set eth0 up && ip addr replace 10.0.2.15/24 dev eth0 && ip route replace default via 10.0.2.2 && ping -c 1 -W 5 10.0.2.2")]
            for name,command in checks:
                report['phase']=name
                child.sendline(command+" && printf 'OPENCI_ALFS_%s\\n' "+name)
                child.expect(r'(?m)^OPENCI_ALFS_'+name+r'\r*$')
                report[name.lower()+'_verified']=True
            child.sendline('poweroff');child.expect(pexpect.EOF,timeout=90);child.close(force=False)
            if child.exitstatus!=0:raise RuntimeError('ALFS guest did not shut down cleanly')
            output.flush()
            import re
            if re.search(r'Kernel panic|Oops:|BUG:',(evidence/'alfs-serial.log').read_text()):raise RuntimeError('ALFS kernel fault')
            report.update(state='passed',phase='completed',qemu_exit_code=child.exitstatus,duration_seconds=round(time.monotonic()-started,3))
        except BaseException as error:
            report.update(state='failed',error=type(error).__name__)
            raise
        finally:
            child.close(force=True)
            (evidence/'alfs-qemu.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main(*sys.argv[1:])

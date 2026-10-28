"""Generate jhalfs configuration using its pinned Kconfig parser; no build here."""
import os
from pathlib import Path
import sys
import hashlib
import json


def prepare_kernel_defaults(root):
    """Resolve toolchain-dependent Kconfig defaults in the target chroot."""
    path=root/'jhalfs/LFS/lfs.xsl';source=path.read_text()
    original='timeout 60 make oldconfig';replacement='timeout 60 make olddefconfig'
    if source.count(original)!=1:raise ValueError('Pinned jhalfs kernel configuration boundary changed')
    patched=source.replace(original,replacement)
    path.write_text(patched)
    (root/'evidence/kernel-config-adaptation.json').write_text(json.dumps({'source':'LFS/lfs.xsl',
        'original_sha256':hashlib.sha256(source.encode()).hexdigest(),'patched_sha256':hashlib.sha256(patched.encode()).hexdigest(),
        'original':original,'replacement':replacement,'reason':'Target compiler changes Kconfig defaults; choose kernel defaults noninteractively before the official build and QEMU test.'},indent=2)+'\n')


def parallel_jobs():
    cores=len(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else (os.cpu_count() or 1)
    return max(1,min(4,cores))


def prepare_gcc_tests(root,jobs):
    """Use the pinned book's documented -j option, including inside su tester."""
    if type(jobs)is not int or not 1<=jobs<=4:raise ValueError('bounded ALFS test parallelism required')
    path=root/'book/chapter08/gcc.xml';source=path.read_text()
    original='su tester -c "PATH=$PATH make -k check"'
    replacement='su tester -c "PATH=$PATH make -j'+str(jobs)+' -k check"'
    if source.count(original)!=1:raise ValueError('Pinned GCC test command boundary changed')
    patched=source.replace(original,replacement);path.write_text(patched)
    (root/'evidence/gcc-test-adaptation.json').write_text(json.dumps({'source':'chapter08/gcc.xml','original_sha256':hashlib.sha256(source.encode()).hexdigest(),'patched_sha256':hashlib.sha256(patched.encode()).hexdigest(),'original':original,'replacement':replacement,'jobs':jobs,'tests_removed':False,'reason':'The pinned official book recommends explicit parallel check jobs; preserve the complete critical test suite within each CI phase.'},indent=2)+'\n')


def main(work):
    root=Path(work).resolve();os.chdir(root/'jhalfs')
    prepare_kernel_defaults(root)
    jobs=parallel_jobs();prepare_gcc_tests(root,jobs)
    os.environ['CONFIG_']=''
    sys.path.insert(0,str(root/'jhalfs/menu'))
    import kconfiglib
    config=kconfiglib.Kconfig('Config.in')
    options={'BOOK_LFS_ANY':'y','BOOK_LFS_SYSD':'y','WORKING_COPY':'y',
             'BOOK':str(root/'book'),'LFS_MULTILIB_NO':'y','BUILD_CHROOT':'y',
             'BLFS_TOOL':'n','CUSTOM_TOOLS':'n','BUILDDIR':'/mnt/openci-lfs',
             'LUSER':'openci-lfs','LGROUP':'openci-lfs','GETPKG':'y',
             'SRC_ARCHIVE':str(root/'downloads'),'RUNMAKE':'y','CLEAN':'n',
             'ALL_CORES':'n','N_PARALLEL':str(jobs),'CONFIG_TESTS':'y','TST_1':'y',
             'INSTALL_LOG':'y','STRIP':'y','NO_PROGRESS_BAR':'y',
             'HAVE_FSTAB':'y','FSTAB':str(root/'fstab'),
             'CONFIG_BUILD_KERNEL':'y','CONFIG':str(root/'kernel.config'),
             'TIMEZONE':'UTC','LANG':'C.UTF-8','FULL_LOCALE':'n',
             'HOSTNAME':'openci-lfs','DOMAIN':'local','INTERFACE':'eth0',
             'IP_ADDR':'10.0.2.15','GATEWAY':'10.0.2.2','PREFIX':'24',
             'BROADCAST':'10.0.2.255','DNS1':'10.0.2.3','DNS2':'10.0.2.3',
             'CONFIG_OPTIMIZE':'n','REPORT':'n','COMPARE':'n'}
    for key,value in options.items():
        symbol=config.syms[key]
        if not symbol.set_value(value):raise ValueError('Invalid jhalfs setting: '+key)
    config.write_config('configuration')
    if 'LHOME="/home"' not in Path('configuration').read_text() or 'CONFIG_BOOK_' in Path('configuration').read_text():raise ValueError('jhalfs requires unprefixed shell settings')
    for key,value in options.items():
        if config.syms[key].str_value!=value:raise ValueError('Inactive jhalfs setting: '+key)


if __name__=='__main__':main(sys.argv[1])

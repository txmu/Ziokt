"""Material and output digests. These records are not Corium-verified contributions."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def tree_digest(root):
    # Include relative names, symlink targets and contents, never timestamps.
    h = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix().encode()
        if path.is_symlink():
            h.update(b'L\0'+relative+b'\0'+str(path.readlink()).encode()+b'\0')
        elif path.is_file():
            h.update(b'F\0'+relative+b'\0'+digest(path).encode()+b'\0')
    return h.hexdigest()


def main(area, buildroot_revision, project_revision, target):
    area = Path(area)
    evidence = area/'evidence'
    qemu = json.loads((evidence/'qemu-test.json').read_text())
    if qemu['state'] != 'passed':
        raise RuntimeError('QEMU test did not pass')
    remote_compiles = sum(path.read_text().count('COMPILE_OK') for path in evidence.glob('distccd-*.log'))
    probes=json.loads((evidence/'toolchain-probe.json').read_text())
    probe_count=probes['probe_remote_compiles']
    if type(probe_count) is not int or probe_count<2 or remote_compiles<=probe_count:
        raise RuntimeError('No evidence of remote build compilations beyond actual probe baseline')
    stats = subprocess.check_output([area/'output/host/bin/ccache', '--print-stats'], text=True)
    (evidence/'ccache-machine-stats.txt').write_text(stats)
    values = dict(line.split() for line in stats.splitlines() if len(line.split()) == 2)
    hits = sum(int(values.get(name, 0)) for name in ('direct_cache_hit', 'preprocessed_cache_hit'))
    if not hits:
        raise RuntimeError('No real ccache hit recorded')
    packages = json.loads((evidence/'buildroot-packages.json').read_text())
    components = []
    for name, info in sorted(packages.items()):
        components.append({'type': 'library', 'name': name, 'version': str(info.get('version', 'unknown'))})
    (evidence/'sbom.cdx.json').write_text(json.dumps({'bomFormat': 'CycloneDX', 'specVersion': '1.5',
            'version': 1, 'components': components}, indent=2)+'\n')
    images = {p.name: {'bytes': p.stat().st_size, 'sha256': digest(p)}
              for p in (area/'output/images').iterdir() if p.is_file() and not p.is_symlink()}
    record = {'schema': 'openci.build-evidence.v1', 'state': 'ci-build-and-boot-verified',
              'target': target, 'buildroot_revision': buildroot_revision, 'project_revision': project_revision,
              'config_sha256': digest(evidence/'buildroot.config'),
              'host_toolchain_tree_sha256': tree_digest(area/'output/host'), 'images': images,
              'remote_compiles': remote_compiles, 'probe_remote_compiles':probe_count, 'build_remote_compiles':remote_compiles-probe_count, 'ccache_hits': hits,
              'distcc_topology': 'two-worker-processes-in-one-ephemeral-github-vm',
              'reproducible_build_verified': False, 'software_security_verified': False,
              'ziokt_native_storage_verified': False, 'release_signed': False,
              'corium_contribution_verified': False, 'all_requested_features_complete': False}
    (evidence/'build-evidence.json').write_text(json.dumps(record, indent=2)+'\n')


if __name__ == '__main__':
    main(*sys.argv[1:])

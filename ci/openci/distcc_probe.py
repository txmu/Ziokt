"""CI-only real cross-compile probes; disabled local fallback cannot hide failure."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time


def main(output, evidence):
    if os.environ.get('GITHUB_ACTIONS')!='true':raise RuntimeError('Native compiler probes run only in CI')
    output, evidence = Path(output), Path(evidence)
    compilers = list((output/'host/bin').glob('*-buildroot-*-gcc'))
    if len(compilers) != 1:
        raise RuntimeError('Expected exactly one Buildroot target compiler')
    compiler = compilers[0]
    compiler_info = {
        'path': str(compiler), 'sha256': hashlib.file_digest(compiler.open('rb'), 'sha256').hexdigest(),
        'version': subprocess.check_output([compiler, '--version'], text=True),
        'target': subprocess.check_output([compiler, '-dumpmachine'], text=True).strip(),
        'sysroot': subprocess.check_output([compiler, '-print-sysroot'], text=True).strip(),
        'isolation': 'same-ephemeral-github-vm', 'pump': False,
    }
    source = evidence/'probe.c'
    source.write_text('int openci_probe(int x) { return x * 7 + 11; }\n')
    # Compare identical output paths/flags, with all local distcc fallback disabled.
    target = evidence/'probe.o'
    subprocess.run([compiler, '-O2', '-c', source, '-o', target], check=True, timeout=60)
    expected = target.read_bytes()
    for port in (13632, 13633):
        deadline = time.monotonic()+10
        while True:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Worker did not become ready')
                time.sleep(.1)
        env = dict(os.environ, DISTCC_HOSTS=f'127.0.0.1:{port}/2', DISTCC_FALLBACK='0')
        target.unlink()
        subprocess.run(['distcc', str(compiler), '-O2', '-c', str(source), '-o', str(target)],
                       check=True, timeout=120, env=env)
        if target.read_bytes() != expected:
            raise RuntimeError('Local and worker object bytes differ')
    # Configure-style negative preprocessing must not poison healthy workers.
    negative=evidence/'expected-negative.c';negative.write_text('#error expected configure probe failure\n')
    rejected=subprocess.run(['distcc',str(compiler),'-c',str(negative),'-o',str(target)],
        env=dict(os.environ,DISTCC_FALLBACK='0'),timeout=30,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if rejected.returncode==0:raise RuntimeError('Expected negative configure probe unexpectedly compiled')
    subprocess.run(['distcc',str(compiler),'-O2','-c',str(source),'-o',str(target)],check=True,timeout=120)
    compiler_info['negative_configure_probe_recovered']=True
    # A closed local port must fail, then healthy workers must recover.
    with socket.socket() as unavailable:
        unavailable.bind(('127.0.0.1', 0))
        closed_port = unavailable.getsockname()[1]
        rejected = subprocess.run(['distcc', str(compiler), '-O2', '-c', str(source), '-o', str(target)],
                timeout=30, env=dict(os.environ, DISTCC_HOSTS=f'127.0.0.1:{closed_port}/1',
                                     DISTCC_FALLBACK='0', DISTCC_IO_TIMEOUT='5'),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if rejected.returncode == 0:
            raise RuntimeError('Offline worker was hidden by local fallback')
    compiler_info['offline_worker_rejected'] = True
    # Exercise a real ccache hit with the native target wrapper.
    env = dict(os.environ, CCACHE_PREFIX=os.environ['OPenci_DISTCC_PREFIX'], CCACHE_COMPILERCHECK='content')
    for attempt in range(2):
        subprocess.run([output/'host/bin/ccache',compiler, '-O2', '-c', source, '-o', target], check=True, timeout=120, env=(dict(env,CCACHE_RECACHE='1') if attempt==0 else env))
    # Ordinary distributed preprocessing strips comments used by old host tools
    # as fallthrough annotations. Host compilation must remain on the coordinator.
    host=evidence/'host-fallthrough.c'
    host.write_text('int host_probe(int x) { switch(x) { case 1: x++; /* FALLTHROUGH */\ncase 2: return x; default: return 0; } }\n')
    subprocess.run([output/'host/bin/ccache','/usr/bin/gcc','-Wextra','-Werror=implicit-fallthrough','-c',host,'-o',evidence/'host-fallthrough.o'],check=True,timeout=60,env=dict(env,CCACHE_RECACHE='1'))
    routing=[json.loads(line) for line in Path(os.environ['OPenci_DISTCC_ROUTING_LOG']).read_text().splitlines()]
    if not any(entry['compiler']=='/usr/bin/gcc' and entry['remote'] is False for entry in routing):raise RuntimeError('Host preprocessing isolation was not observed')
    if not any(entry['remote'] is True for entry in routing):raise RuntimeError('Actual target compiler did not use distcc prefix')
    compiler_info['host_tools_kept_on_coordinator']=True
    compiler_info['explicit_ccache_invocation_verified']=True
    compiler_info['probe_remote_compiles']=sum(path.read_text().count('COMPILE_OK') for path in evidence.glob('distccd-*.log'))
    compiler_info['probe_object_sha256'] = hashlib.sha256(expected).hexdigest()
    compiler_info['workers_verified'] = [13632, 13633]
    compiler_info['software_security_verified'] = False
    (evidence/'toolchain-probe.json').write_text(json.dumps(compiler_info, indent=2)+'\n')


if __name__ == '__main__':
    main(*sys.argv[1:])

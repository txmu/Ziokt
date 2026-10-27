"""CI-only: regenerate tiny proofs using a checksum-pinned official mprime.

No GIMPS assignment reservation, result transmission, or proof upload is enabled.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ziokt.gimps_files import verify_proof

URL = 'https://download.mersenne.ca/gimps/v30/30.19/p95v3019b20.linux64.tar.gz'
SHA256 = '4ce2377e03deb4cf189523136e26401ba08f67857a128e420dd030d00cdca601'
# Exact target returned by the official distribution URL (2026-10-27).
# Every cache hit and download must still match the pinned release checksum.
OFFICIAL_REDIRECT = 'https://drive.usercontent.google.com/download?id=16Nim-NX6BGYjcsPBkq1tDbc_8qnwghSB&export=download'
MAX_ARCHIVE = 10 * 1024 * 1024


def official_archive(cache):
    if cache.is_file():
        data = cache.read_bytes()
        if len(data) <= MAX_ARCHIVE and hashlib.sha256(data).hexdigest() == SHA256:
            return data
    error = None
    for attempt in range(3):
        for url in (URL, OFFICIAL_REDIRECT):
            try:
                with urllib.request.urlopen(url, timeout=45) as response:
                    data = response.read(MAX_ARCHIVE + 1)
                if len(data) > MAX_ARCHIVE or hashlib.sha256(data).hexdigest() != SHA256:
                    raise ValueError('official archive checksum or size mismatch')
                cache.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache.with_suffix('.part')
                temporary.write_bytes(data)
                temporary.replace(cache)
                return data
            except (OSError, urllib.error.URLError, ValueError) as caught:
                error = caught
        if attempt < 2:
            time.sleep(2 ** attempt)
    raise RuntimeError('checksum-pinned official archive unavailable after bounded retries') from error


def main():
    if os.environ.get('CI') != 'true':
        raise SystemExit('Run this regeneration in CI; local verification uses checked-in tiny fixtures.')
    with tempfile.TemporaryDirectory(prefix='gimps-official-ci-') as temporary:
        root = Path(temporary)
        archive = root / 'mprime.tar.gz'
        data = official_archive(Path(__file__).resolve().parents[1] / '.cache/gimps' / (SHA256 + '.tar.gz'))
        archive.write_bytes(data)
        binary = root / 'binary'
        with tarfile.open(archive) as source:
            source.extractall(binary, filter='data')
        work = root / 'work'
        work.mkdir()
        (work / 'prime.txt').write_text('StressTester=0\nUsePrimenet=0\nNumWorkers=1\nCoresPerTest=1\nWorkerDiskSpace=0.05\nExitWhenOutOfWork=1\n[PrimeNet]\nProofPower=5\nProofUploads=0\n[Internals]\nV30OptionsConverted=1\n')
        (work / 'worktodo.txt').write_text('PRP=1,2,127,-1,99,0,3,1\nPRP=1,2,521,-1,99,0,3,1\n')
        paths = [work / f'p{p:07d}.proof' for p in (127, 521)]
        env = dict(os.environ, LD_LIBRARY_PATH=str(binary))
        with (work / 'mprime.log').open('wb') as log:
            process = subprocess.Popen([str(binary / 'mprime'), '-w' + str(work), '-d'],
                                       env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic() + 60
                while not all(p.is_file() for p in paths):
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('official mprime did not produce both proofs: ' + (work / 'mprime.log').read_text()[-4000:])
                    time.sleep(.1)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
        verified = [verify_proof(p.read_bytes()) for p in paths]
        print(json.dumps({'official_archive_sha256': SHA256, 'verified': verified,
                          'official_server_submission': False}, sort_keys=True))


if __name__ == '__main__':
    main()

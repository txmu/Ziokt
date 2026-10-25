"""Package actual tested builds; never include test credentials or environments."""
import hashlib
import json
from pathlib import Path
import tarfile
import subprocess

root = Path(__file__).resolve().parents[1]
dist = root / "dist"
dist.mkdir(exist_ok=True)
s = root.parent / "Shadow6"
c = root.parent / "Corium"
with tarfile.open(dist / "shadow6-ziokt.tar.gz", "w:gz") as archive:
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=s).decode().split("\0")
    products = {str(p.relative_to(s)) for directory in s.glob("Core-*") if directory.is_dir()
                for p in directory.rglob("*") if p.is_file() and
                (p.name.startswith("shadow6-") or any(part.startswith("shadow6-") and part.endswith("_app") for part in p.parts) or
                 ".so" in p.suffixes or p.suffix in {".dll", ".dylib"})
                and p.suffix not in {".py", ".txt", ".md", ".c", ".cpp", ".o"}}
    names = sorted(set(filter(None, names)) | products)
    for name in names:
        file = s / name
        if file.is_symlink() or not file.is_file():
            raise ValueError("native source artifact requires regular tracked files: " + name)
        archive.add(file, arcname="Shadow6/" + str(file.relative_to(s)), recursive=False)
# Corium is interpreted Bash; syntax/heredoc checks and the native testchain are
# its build admission, not a claim that the script became a compiled executable.
(dist / "corix-ziokt.sh").write_bytes((c / "corix_v108.sh").read_bytes())
(dist / "corix-ziokt.sh").chmod(0o755)
# Public verification/hold tools must accompany the native single-file runtime.
# A node cannot review and release its history hold using an absent sidecar.
runtime=dist/'corium-runtime';runtime.mkdir(exist_ok=True)
for name in ('consensus_hold.py','consensus_core.py','verify_mainnet_history.py','audit_history_provenance.py',
             'recovery_transition_plan.py','sovereign_status.py','recovery_consensus.py',
             'work_consensus.py','work_weight_policy.py','work_weight_native.py','openci_consensus.py',
             'dna_protocol.py','cooperative_protocol.py','shielded_ownership.py'):
    source=c/name
    if source.is_symlink() or not source.is_file():raise ValueError('native verification source missing: '+name)
    (runtime/name).write_bytes(source.read_bytes())
def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
manifest = {str(p.relative_to(dist)): {"bytes": p.stat().st_size, "sha256": digest(p)}
            for p in dist.rglob('*') if p.is_file() and p != dist/'manifest.json'}
(dist / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

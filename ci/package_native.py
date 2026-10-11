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
    names = sorted(set(filter(None, names)) | {"Core-Go/shadow6-go", "Core-Rust/shadow6-rust"})
    for name in names:
        file = s / name
        if file.is_symlink() or not file.is_file():
            raise ValueError("native source artifact requires regular tracked files: " + name)
        archive.add(file, arcname="Shadow6/" + str(file.relative_to(s)), recursive=False)
# Corium is interpreted Bash; syntax/heredoc checks and the native testchain are
# its build admission, not a claim that the script became a compiled executable.
(dist / "corix-ziokt.sh").write_bytes((c / "corix_v108.sh").read_bytes())
(dist / "corix-ziokt.sh").chmod(0o755)
manifest = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in dist.iterdir() if p.is_file() and p.name != "manifest.json"}
(dist / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

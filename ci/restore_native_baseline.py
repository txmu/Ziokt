"""Admit verified baseline Core binaries without rebuilding every language.

The new native Provider sources remain pinned by native-sources.lock.json; only
Core products unchanged by Ziokt are copied from the successful upstream build.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile

root = Path(__file__).resolve().parents[1]
source = Path(sys.argv[1]).absolute()
lock = json.loads((root / "native-baseline.lock.json").read_text())
if hashlib.sha256(source.read_bytes()).hexdigest() != lock["sha256"]:
    raise ValueError("upstream native baseline digest mismatch")
destination = root.parent / "Shadow6"
with tempfile.TemporaryDirectory(prefix="ziokt-native-baseline-") as directory:
    with tarfile.open(source) as archive:
        archive.extractall(directory, filter="data")
    bundle = Path(directory) / "Shadow6"
    # All native families and the second Gleam Profile share exactly this rule;
    # no business adapter is selected by Core name.
    for folder in sorted(bundle.glob("Core-*")):
        if not folder.is_dir():
            continue
        for file in folder.rglob("*"):
            if not file.is_file() or file.is_symlink():
                continue
            relative = file.relative_to(folder)
            if (file.name.startswith("shadow6-") or any(p.startswith("shadow6-") and p.endswith("_app") for p in relative.parts) or
                    ".so" in file.suffixes or file.suffix in {".dll", ".dylib"}):
                if file.suffix in {".py", ".txt", ".md", ".c", ".cpp", ".o"}: continue
                target = destination / folder.name / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, target)
                target.chmod(0o755 if file.stat().st_mode & 0o111 else 0o644)
    # Recompile Idris Chez scheme application if chezscheme is available, ensuring
    # the generated image matches the host Chez Scheme FASL ABI and interpreter.
    idris_dir = destination / "Core-Idris"
    if idris_dir.is_dir():
        sodium_ffi = idris_dir / "libsodium_ffi.so"
        for app_dir in sorted(idris_dir.glob("*_app")):
            if sodium_ffi.is_file():
                target_ffi = app_dir / "libsodium_ffi.so"
                if not target_ffi.exists():
                    shutil.copyfile(sodium_ffi, target_ffi)
                    target_ffi.chmod(0o755)
            ss_file = app_dir / "shadow6-idris.ss"
            so_file = app_dir / "shadow6-idris.so"
            chez = shutil.which("chezscheme") or shutil.which("chez")
            if ss_file.is_file() and chez:
                cmd = f'(parameterize ([optimize-level 3] [compile-file-message #f]) (compile-program "{ss_file.resolve()}" "{so_file.resolve()}")) (exit 0)'
                import subprocess
                subprocess.run([chez, "-q"], input=cmd.encode(), check=True)
                so_file.chmod(0o755)
        for launcher_name in ("shadow6-idris", "shadow6-idris-crosed"):
            launcher = idris_dir / launcher_name
            if launcher.is_file():
                content = launcher.read_text(encoding="utf-8")
                if 'export LD_LIBRARY_PATH="$DIR:' not in content:
                    content = content.replace('export LD_LIBRARY_PATH="$DIR/', 'export LD_LIBRARY_PATH="$DIR:$DIR/')
                    launcher.write_text(content, encoding="utf-8")
                    launcher.chmod(0o755)
print("Verified unchanged Core products restored for all Native Profiles")


"""Build the coordinator zipapp without native compilation or dependency fetch."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipapp

root = Path(__file__).resolve().parents[1]
output = root / "dist"
output.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="ziokt-build-") as directory:
    stage = Path(directory)
    shutil.copytree(root / "ziokt", stage / "ziokt", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(root / "gateway", stage / "gateway")
    shutil.copytree(root / "openci", stage / "openci", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (stage / "__main__.py").write_text("from ziokt.cli import main\nraise SystemExit(main())\n")
    zipapp.create_archive(stage, output / "ziokt.pyz", compressed=True)
    (stage / "__main__.py").write_text("from openci.cli import main\nmain()\n")
    zipapp.create_archive(stage, output / "openci.pyz", compressed=True)
subprocess.run([sys.executable, str(output / "ziokt.pyz"), "--help"], check=True)
invalid = subprocess.run([sys.executable, str(output / "ziokt.pyz"), "doctor", "--config", str(output / "nonexistent-config.json")], capture_output=True)
assert invalid.returncode == 2, "zipapp must preserve CLI failure status"
print(output / "ziokt.pyz")

subprocess.run([sys.executable, str(output / "openci.pyz"), "--help"], check=True)

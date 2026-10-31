"""Build the coordinator zipapp without native compilation or dependency fetch."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipapp
import json
import zipfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from ziokt.build_info import snapshot
output = root / "dist"
output.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="ziokt-build-") as directory:
    stage = Path(directory)
    shutil.copytree(root / "ziokt", stage / "ziokt", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    native_ufs=stage/'ziokt'/'_ufs_native';native_ufs.mkdir()
    for name in ('ufsultra.py','ufs_http_security.py'):
        shutil.copyfile(root/'companions/ufsdcpm/src'/name,native_ufs/name)
    shutil.copytree(root / "gateway", stage / "gateway")
    shutil.copytree(root / "openci", stage / "openci", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (stage / 'ziokt' / '_build_manifest.json').write_text(json.dumps(snapshot(),sort_keys=True)+'\n')
    (stage / "__main__.py").write_text("from ziokt.cli import main\nraise SystemExit(main())\n")
    zipapp.create_archive(stage, output / "ziokt.pyz", compressed=True)
    (stage / "__main__.py").write_text("from openci.cli import main\nmain()\n")
    zipapp.create_archive(stage, output / "openci.pyz", compressed=True)
subprocess.run([sys.executable, str(output / "ziokt.pyz"), "--help"], check=True)
invalid = subprocess.run([sys.executable, str(output / "ziokt.pyz"), "doctor", "--config", str(output / "nonexistent-config.json")], capture_output=True)
assert invalid.returncode == 2, "zipapp must preserve CLI failure status"
print(output / "ziokt.pyz")

subprocess.run([sys.executable, str(output / "openci.pyz"), "--help"], check=True)

# Prove standalone UFS imports come from the actual installed zipapp, without a checkout.
with tempfile.TemporaryDirectory(prefix="ziokt-packaged-ufs-") as cwd:
    subprocess.run([sys.executable,"-c",
        "import sys;sys.path.insert(0,sys.argv[1]);from ziokt.ufs_protocols import native;modules=native();assert all(sys.argv[1] in m.__file__ for m in modules);print('packaged native UFS modules verified')",
        str(output/'ziokt.pyz')],cwd=cwd,check=True)

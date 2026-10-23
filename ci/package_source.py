"""Committed, preflighted UTF-8 text exchange delivery for all three projects."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=root / 'dist/Ziokt-Corium-Shadow6-source-2026-10-23.zip')
    args = parser.parse_args()
    for name in ('Ziokt', 'Corium', 'Shadow6'):
        if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=root.parent / name).strip():
            raise SystemExit('Commit source before delivery: ' + name)
    spec = importlib.util.spec_from_file_location('joint_source', root / 'tools/package_joint_source.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    print(json.dumps(module.package(root.parent, args.output), indent=2))

if __name__ == '__main__':
    main()

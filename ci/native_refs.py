"""Emit pinned source revisions for native checkout actions."""
import json
import os
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
value = json.loads((root / "native-sources.lock.json").read_text())
with open(os.environ["GITHUB_OUTPUT"], "a") as output:
    for project in ("shadow6", "corium"):
        sha = value[project]["revision"]
        if not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise ValueError("exact native revision required")
        output.write(project + "=" + sha + "\n")

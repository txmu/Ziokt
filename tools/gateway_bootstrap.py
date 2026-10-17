#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.cli import main
raise SystemExit(main(['gateway','bootstrap',*sys.argv[1:]]))

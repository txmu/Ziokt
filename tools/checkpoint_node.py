#!/usr/bin/env python3
"""Capture a local dual-chain checkpoint; this is not new-node fast admission."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.checkpoint_capture import capture_pair

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True);parser.add_argument('--store',required=True);parser.add_argument('--bundle')
 args=parser.parse_args();result=capture_pair(json.loads(Path(args.config).read_text()),args.store,bundle=args.bundle);print(json.dumps(result,indent=2))

if __name__=='__main__':main()

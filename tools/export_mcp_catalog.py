#!/usr/bin/env python3
"""Export exactly the configured MCP tool set; never print credentials."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.mcp import Service,VERSIONS
from ziokt.protocol import secure_read,strict_json

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,default=Path('docs/MCP_TOOL_CATALOG.json'));a=p.parse_args()
    config=strict_json(secure_read(a.config));config['config_path']=str(a.config.resolve());s=Service(config)
    catalog={'schema':'ziokt.mcp-catalog.v1','endpoint':config['issuer']+'/mcp','protocols':list(VERSIONS),'tool_count':len(s.tools),'tools':list(s.tools.values())}
    a.output.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'tools':len(s.tools),'output':str(a.output)}))

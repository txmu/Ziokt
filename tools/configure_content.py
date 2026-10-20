#!/usr/bin/env python3
"""Provision opt-in Content Fabric with independent application credentials."""
import argparse,json,secrets
from pathlib import Path
from ziokt.cli import write_binary_exclusive
from ziokt.safefs import _private_dir


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',required=True,type=Path);parser.add_argument('--port',type=int,default=8210);parser.add_argument('--nntp-port',type=int,default=8119)
 parser.add_argument('--allow-webextensions',action='store_true',help='Allow extension Origins with independent scoped bearer credentials')
 args=parser.parse_args();root=_private_dir(args.directory.resolve())
 if (root/'content.json').exists():parser.error('configuration already exists; refusing to replace keys')
 app=secrets.token_urlsafe(48);peer=secrets.token_urlsafe(48)
 write_binary_exclusive(root/'application.token',app.encode());write_binary_exclusive(root/'peer.token',peer.encode())
 cfg={'schema':'ziokt.content-node.v1','root':str(root/'state'),'listen':'127.0.0.1','port':args.port,'origins':[f'http://127.0.0.1:{args.port}'],'tokens':[{'account':'owner','token':app,'scopes':['content:read','content:write','library:read','library:write','netnews:read','netnews:write','applications:read','applications:write','optimization:read','optimization:write','feeds:read']},{'account':'federation','token':peer,'scopes':['content:read','content:replicate']}],'peers':{},'allow_webextensions':args.allow_webextensions,'nntp':{'enabled':True,'listen':'127.0.0.1','port':args.nntp_port,'anonymous_read':False,'allow_loopback_auth':True}}
 write_binary_exclusive(root/'content.json',json.dumps(cfg,indent=2).encode())
 print(json.dumps({'config':str(root/'content.json'),'application_token_file':str(root/'application.token'),'peer_token_file':str(root/'peer.token'),'gui':f'http://127.0.0.1:{args.port}/','public_listener':False}))

if __name__=='__main__':main()

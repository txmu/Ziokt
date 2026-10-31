#!/usr/bin/env python3
"""UFS extended-protocol entry point, shared with Ziokt and native DCPM."""
import argparse,asyncio,importlib.util,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from ufsultra import Config
from ziokt.ufs_protocols import Hub
from ziokt.protocol import secure_read,strict_json

class ExtendedConfig(Config):
    def default_config(self):
        value=super().default_config()
        value['protocols']={name:{'enabled':True,'port':port,'tls':name in {'ftps','telnet','nntp'}} for name,port in [('ftp',2121),('ftps',2122),('nntp',1119),('gopher',7070),('telnet',2323),('sftp',2222)]}
        return value

class ExtendedServer:
    def __init__(self,config=None):self.hub=Hub(config or ExtendedConfig().data)
    async def start_servers(self):
        print(json.dumps({'schema':'ziokt.ufs-protocols.v1','listeners':await self.hub.start()}),flush=True)
        try:await self.hub.stopping.wait()
        finally:await self.hub.close()
    def shutdown(self):self.hub.stopping.set()

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path);parser.add_argument('--mode',choices=['standard','secure','mirror'],default='standard');parser.add_argument('--daemon',action='store_true');parser.add_argument('--install',action='store_true');args=parser.parse_args()
    if args.install:
        if args.config is None:raise ValueError('service installation requires an explicit private configuration')
        source=ROOT.parent/'Ziokt-Releases/deploy.py'
        if not source.is_file():source=ROOT/'tools/deploy.py'
        spec=importlib.util.spec_from_file_location('ziokt_deployment',source);deployment=importlib.util.module_from_spec(spec);spec.loader.exec_module(deployment)
        root=args.config.resolve().parent;definition=deployment.persist(root,'ufs-protocols',[sys.executable,str(Path(__file__).resolve()),'--config',str(args.config.resolve())]);file=root/'services.json';entries=json.loads(file.read_text()) if file.exists() else {};entries['ufs-protocols']={'definition':definition};deployment.write(file,entries);print(json.dumps({'service':'ufs-protocols','definition':definition}));return
    if args.config is not None:
        from ziokt.ufs_protocols import run
        asyncio.run(run(args.config));return
    from ziokt.ufs_protocols import run
    config=ExtendedConfig();asyncio.run(ExtendedServer(config.data).start_servers())

if __name__=='__main__':main()

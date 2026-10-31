#!/usr/bin/env python3
"""
DCPM-UFS整合系统完整实现
- 统一区块链网络
- 混合存储策略
- 完整P2P支持
- 增强型UFS服务
"""

import os
import hashlib
import sys
import json
import time
import signal
import asyncio
import threading
import shutil
import secrets
import stat
import base64
from urllib.parse import urlsplit, parse_qs
import argparse
from pathlib import Path
from typing import Dict, List, Optional
from dcpm_core import Package, Blockchain, verify_signature, sign_data
import ufsultra
from dcpm_ufs_packages import PackageStore, fetch_http, MAX_PACKAGE
from ziokt.protocol import ProtocolError, secure_read

class IntegratedSystem:
    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        packages = self.config['packages']
        served = Path(self.config['storage']['ufs_root']).absolute()
        private_store = (Path(self.config['storage']['cache'])/'signed-packages').absolute()
        if private_store.is_relative_to(served) or packages.get('signing_key') and Path(packages['signing_key']).absolute().is_relative_to(served):
            raise ValueError('DCPM_PRIVATE_STORAGE_INSIDE_HTTP_ROOT')
        if config_path and Path(config_path).absolute().is_relative_to(served):
            raise ValueError('DCPM_CONFIG_INSIDE_HTTP_ROOT')
        if not isinstance(packages['http_sources'],list) or len(packages['http_sources'])>8:
            raise ValueError('DCPM_HTTP_SOURCE_BUDGET')
        self.package_store = PackageStore(Path(self.config['storage']['cache'])/'signed-packages',
            packages.get('signing_key'), packages.get('trusted_publishers'), self.config['storage']['max_size'])
        self.node_id = hashlib.sha256(self.package_store.public.encode()).hexdigest()
        self.blockchain = Blockchain()  # Original local header mechanism; not Corium consensus.
        self.dcpm_node, self.ufs_chain, self.loop = None, None, None
        self.running = False
        self.ufs_server = None
        self.protocol_hub = None

    def _load_config(self, config_path: Optional[str]) -> Dict:
        """加载配置文件"""
        config_paths = [
            Path(config_path) if config_path else None,
            Path('dcpm-ufs-config.json'),
            Path('/etc/dcpm-ufs/config.json'),
            Path.home() / '.config/dcpm-ufs/config.json'
        ]
        
        for path in config_paths:
            if path and path.exists():
                config = json.loads(secure_read(path,256*1024))
                return self._resolve_paths(self._apply_default_config(config),path.parent)
        
        config = self._default_config()
        target=Path.home()/'.config/dcpm-ufs/config.json'
        config = self._resolve_paths(config,target.parent)
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        try:
            fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as output:
                json.dump(config,output,ensure_ascii=False,indent=2); output.flush(); os.fsync(output.fileno())
        except FileExistsError:
            return self._resolve_paths(self._apply_default_config(json.loads(secure_read(target,256*1024))),target.parent)
        return config

    def _resolve_paths(self, config, base):
        base=Path(base).absolute()
        for section,field in [('storage','cache'),('storage','ufs_root'),('logging','file'),
                ('ufs','root_dir'),('ufs','ssl_cert'),('packages','signing_key'),('p2p','tls_cert'),('p2p','tls_key')]:
            value=config[section].get(field)
            if value is not None:
                if not isinstance(value,str) or not value: raise ValueError('DCPM_CONFIG_PATH')
                path=Path(value)
                config[section][field]=str(path if path.is_absolute() else base/path)
        for source in config['packages']['http_sources']:
            if source.get('ca'):
                path=Path(source['ca']); source['ca']=str(path if path.is_absolute() else base/path)
        return config

    def _default_config(self) -> Dict:
        """默认配置"""
        return {
            'node': {
                'id': None,
                'type': 'hybrid',  # 'dcpm', 'ufs', or 'hybrid'
                'name': 'dcpm-ufs-node'
            },
            'p2p': {
                'host': '127.0.0.1',
                'enabled': False,
                'port': 9000,
                'bootstrap_nodes': [],
                'enable_relay': True,
                'enable_dht': True,
                'enable_pubsub': True
            },
            'ufs': {
                'enabled': True,
                'host': '127.0.0.1',
                'ssl': False,
                'upload': True,
                'legacy_file_chain': False,
                'port': 8000,
                'root_dir': './ufs-storage',
                'max_upload': 64 * 1024**2,  # 10GB
                'max_download': 0,  # 0=无限制
                'auth': {
                    'enabled': True,
                    'users': {
                        'admin': {
                            'password': secrets.token_urlsafe(24),
                            'role': 'admin'
                        }
                    }
                }
            },
            'packages': {'trusted_publishers': [], 'http_sources': []},
            'storage': {
                'cache': './dcpm-cache',
                'ufs_root': './ufs-storage',
                'max_size': 100 * 1024**3,  # 100GB
                'block_size': 1024 * 1024,  # 1MB
                'retention_days': 30
            },
            'ipfs': {
                'enabled': False,
                'gateway': '/ip4/127.0.0.1/tcp/5001'
            },
            'bittorrent': {
                'enabled': False,
                'listen_port': 6881,
                'max_upload_rate': 1024 * 1024,  # 1MB/s
                'max_download_rate': 5 * 1024 * 1024  # 5MB/s
            },
            'network': {
                'prefer_ufs': True,
                'fallback_order': ['ufs', 'ipfs', 'bittorrent'],
                'max_connections': 100
            },
            'logging': {
                'level': 'INFO',
                'file': 'dcpm-ufs.log',
                'max_size': 10 * 1024 * 1024,  # 10MB
                'backup_count': 5
            }
        }

    def _apply_default_config(self, config: Dict) -> Dict:
        """应用默认配置到现有配置"""
        default = self._default_config()
        for section, values in default.items():
            if section not in config:
                config[section] = values
            else:
                for key, value in values.items():
                    if key not in config[section]:
                        config[section][key] = value
        return config

    def _init_dcpm_node(self):
        """初始化DCPM P2P节点"""
        from dcpm_p2p import P2PNode
        # The historical P2P host requires its existing RSA identity. Persist it
        # separately from the Ed25519 package-publisher identity.
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        key_path = Path(self.config['storage']['cache'])/'transport.key'
        if not key_path.exists():
            key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
            raw = key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
            fd = os.open(key_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as target: target.write(raw)
        private = secure_read(key_path,16384)
        key = serialization.load_pem_private_key(private,password=None)
        public = key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        return P2PNode(self.config['p2p']['host'],self.config['p2p']['port'],public,private,
            self.config['p2p'].get('tls_cert'),self.config['p2p'].get('tls_key'))

    def _init_ufs_server(self) -> ufsultra.UltraServer:
        """初始化增强型UFS服务器"""
        # 修改UFS配置以匹配我们的设置
        ufs_config = dict(self.config['ufs'])
        ufs_config.update(root_dir=self.config['storage']['ufs_root'],
            download_limit=self.config['ufs']['max_download'],log_file=self.config['logging']['file'])
        if ufs_config.get('protocols'):
            from ziokt.ufs_protocols import Hub
            self.protocol_hub=Hub(ufs_config,include_http=False)
            ufs_config=self.protocol_hub.config
        server = ufsultra.UltraServer((ufs_config['host'],ufs_config['port']),
            self._create_ufs_handler_class(),config=ufs_config)
        server.integrated_system = self
        server.protocol_hub = self.protocol_hub
        return server

    def _create_ufs_handler_class(self):
        """创建定制的UFS请求处理器类"""
        class IntegratedUFSHandler(ufsultra.UltraHandler):
            def __init__(self, *args, **kwargs):
                self.system = args[2].integrated_system
                self.ufs_chain = self.system.ufs_chain
                self.config = self.system.config
                super().__init__(*args, **kwargs)

            def handle_api(self):
                path = urlsplit(self.path).path
                if path.startswith('/api/dcpm/'):
                    return self.handle_package_api(path)
                if path.startswith('/api/ufs/'):
                    if self.ufs_chain is None:
                        self.send_error(501, 'Legacy file-chain backend is not enabled'); return
                    if self.system.loop is None or not self.system.loop.is_running():
                        self.send_error(503, 'Native event loop is unavailable'); return
                    if self.user_role != 'admin':
                        self.send_error(403, 'Legacy file API requires administrative permission'); return
                    if path == '/api/ufs/publish':
                        if self.command != 'POST' or not self._writable(): return
                    elif self.command not in {'GET','HEAD'}:
                        self.send_error(405, 'File API method rejected'); return
                    future = asyncio.run_coroutine_threadsafe(self.handle_api_request(path),self.system.loop)
                    try: future.result(15)
                    except TimeoutError:
                        future.cancel(); self.send_error(504, 'Bounded file operation timed out')
                    return
                return super().handle_api()

            def api_stats(self):
                self.send_json({'node_id':self.system.node_id,'runtime_mode':'signed-package-http',
                    'p2p_enabled':self.system.dcpm_node is not None,'legacy_file_chain_enabled':self.ufs_chain is not None,
                    'packages':len(self.system.package_store.list()),'corium_consensus_verified':False,
                    'transfers':dict(self.server.stats)})

            def handle_package_api(self, path):
                if self.user_role not in {'user','admin'}:
                    self.send_error(403, 'Package API permission required'); return
                try:
                    if path == '/api/dcpm/publish' and self.command == 'POST':
                        if not self._writable(): return
                        if self.headers.get('Content-Type') != 'application/octet-stream':
                            self.send_error(415, 'Signed package bytes required'); return
                        size = self._length(MAX_PACKAGE)
                        blob = self.rfile.read(size)
                        if len(blob) != size: raise ValueError('DCPM_TRUNCATED_PACKAGE')
                        result = self.system.package_store.admit(blob)
                        result['network_published'] = False
                        self.send_json(result); return
                    if path == '/api/dcpm/packages' and self.command in {'GET','HEAD'}:
                        self.send_json({'packages':self.system.package_store.list()}); return
                    if path == '/api/dcpm/package' and self.command in {'GET','HEAD'}:
                        params = parse_qs(urlsplit(self.path).query)
                        if not {'package_id'} <= set(params) or set(params)-{'package_id','version_id'} or any(len(v)!=1 for v in params.values()):
                            raise ValueError('DCPM_PACKAGE_QUERY')
                        package_id = params['package_id'][0]; version_id = params.get('version_id',[None])[0]
                        blob = self.system.package_store.blob(package_id,version_id)
                        self.send_response(200); self.send_header('Content-Type','application/octet-stream')
                        self.send_header('Content-Length',str(len(blob))); self.end_headers()
                        if self.command != 'HEAD': self.wfile.write(blob)
                        return
                    self.send_error(405, 'Unsupported package API method')
                except OverflowError: self.send_error(413, 'Package exceeds receive budget')
                except (OSError,ValueError,ProtocolError) as error: self._error(error)

            async def handle_api_request(self, path: str):
                """处理增强的API请求"""
                if path == '/api/ufs/publish':
                    return await self._handle_publish()
                elif path == '/api/ufs/retrieve':
                    return await self._handle_retrieve()
                elif path == '/api/ufs/metadata':
                    return await self._handle_metadata()
                else:
                    return await super().handle_api_request(path)
            
            async def _handle_publish(self):
                """处理文件发布请求"""
                if not self.authenticate():
                    return
                
                try:
                    content_length = self._length(self.cfg['max_upload'])
                    if content_length > self.cfg['max_upload']:
                        self.send_error(413, "File too large")
                        return
                    
                    # 解析元数据
                    metadata = json.loads(self.headers.get('X-File-Metadata', '{}'))
                    file_name = metadata.get('name', 'file.bin')
                    owner = self.username
                    permissions = metadata.get('permissions', {
                        'read': ['group:admin'],
                        'write': [f"user:{owner}"]
                    })
                    
                    # 保存临时文件
                    import tempfile
                    descriptor, temporary = tempfile.mkstemp(prefix='.ufs-publish-',dir=self.cfg['root_dir'])
                    os.close(descriptor)
                    temp_path = Path(temporary)
                    with open(temp_path, 'wb') as f:
                        remaining = content_length
                        while remaining > 0:
                            chunk = min(remaining, 1024*1024)
                            data = self.rfile.read(chunk)
                            if not data: raise ValueError('UFS_TRUNCATED_UPLOAD')
                            f.write(data)
                            remaining -= len(data)
                    
                    # 发布到区块链网络
                    metadata = await self.ufs_chain.publish_file(
                        temp_path, owner, permissions,
                        redundancy=self.config['storage'].get('redundancy', 3))
                    
                    # 返回响应
                    self.send_response(201)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(metadata).encode())
                
                except Exception as e:
                    self.send_error(500, str(e))
                finally:
                    if 'temp_path' in locals(): temp_path.unlink(missing_ok=True)
            
            async def _handle_retrieve(self):
                """处理文件检索请求"""
                file_id = self.headers.get('X-File-ID')
                if not isinstance(file_id,str) or not __import__('re').fullmatch('[a-f0-9]{64}',file_id):
                    self.send_error(400, "Missing File ID")
                    return
                
                file_path = await self.ufs_chain.retrieve_file(file_id)
                if not file_path or not file_path.exists():
                    self.send_error(404, "File not found")
                    return
                
                # 发送文件
                self.send_response(200)
                self.send_header("Content-type", self.guess_type(str(file_path)))
                self.send_header("Content-Length", file_path.stat().st_size)
                self.end_headers()
                
                with self.server.files.open(self._parts_for_local_path(file_path)) as f:
                    self.copyfile(f, self.wfile)
            
            async def _handle_metadata(self):
                """处理元数据查询请求"""
                file_id = self.headers.get('X-File-ID')
                if not isinstance(file_id,str) or not __import__('re').fullmatch('[a-f0-9]{64}',file_id):
                    self.send_error(400, "Missing File ID")
                    return
                
                metadata = await self.ufs_chain._query_file_metadata(file_id)
                if not metadata:
                    self.send_error(404, "Metadata not found")
                    return
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(metadata).encode())
        
        return IntegratedUFSHandler

    async def start(self):
        if self.running: return
        self.loop = asyncio.get_running_loop()
        if self.ufs_server is None: self.ufs_server = self._init_ufs_server()
        if self.protocol_hub is not None:await self.protocol_hub.start()
        if self.config['p2p'].get('enabled',False):
            self.dcpm_node = self._init_dcpm_node()
            await self.dcpm_node.start()
        if self.config['ufs'].get('legacy_file_chain',False):
            if self.dcpm_node is None: raise RuntimeError('UFS_FILE_CHAIN_REQUIRES_NATIVE_P2P')
            from ufs_blockchain import UFSBlockchainExtension
            self.ufs_chain=UFSBlockchainExtension(self.blockchain,self.dcpm_node,self.config,self.node_id)
        self.server_thread=threading.Thread(target=self.ufs_server.serve_forever,name='dcpm-ufs-http',daemon=True)
        self.server_thread.start(); self.running=True
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT,self._handle_shutdown); signal.signal(signal.SIGTERM,self._handle_shutdown)
        while self.running:
            if self.protocol_hub is not None and self.protocol_hub.stopping.is_set():
                await self.stop();raise RuntimeError('native UFS protocol listener stopped; supervisor will restart the component')
            await asyncio.sleep(0.2)

    async def stop(self):
        if self.running:
            self.running=False
            await asyncio.to_thread(self.ufs_server.shutdown)
            self.server_thread.join(5)
        if self.ufs_server is not None: self.ufs_server.server_close()
        if self.protocol_hub is not None:await self.protocol_hub.close()
        if self.dcpm_node is not None: await self.dcpm_node.stop()
        if self.ufs_chain is not None: await self.ufs_chain.cleanup()
        if not getattr(self,'_closed',False):
            self.package_store.close(); self._closed=True

    def _handle_shutdown(self, signum, frame):
        """处理关闭信号"""
        asyncio.create_task(self.stop())

    async def publish_package(self, package_path: str, redundancy: int = 3) -> Dict:
        if type(redundancy) is not int or not 1<=redundancy<=8: raise ValueError('DCPM_REPLICA_BUDGET')
        blob = secure_read(package_path,MAX_PACKAGE,private=False)
        result = self.package_store.admit(blob)
        result.update(requested_replicas=redundancy,replication_satisfied=redundancy<=1,network_published=False)
        if self.dcpm_node is not None:
            package=self.package_store.package(result['package_id'],result['version_id'])
            if result['publisher'] != self.package_store.public:
                raise PermissionError('DCPM_CANNOT_RESIGN_ANOTHER_PUBLISHER')
            publication=await asyncio.wait_for(self.dcpm_node.publish_package(package,signing_key=str(self.package_store.key_path)),15)
            result['network_published']=True; result['native_publication']=publication
        return result

    async def download_package(self, package_id: str, version_id: Optional[str] = None) -> Optional[Package]:
        try: return self.package_store.package(package_id,version_id)
        except FileNotFoundError: pass
        failures=[]
        for source in self.config['packages']['http_sources']:
            try:
                blob=await asyncio.to_thread(fetch_http,source,package_id,version_id)
                result=self.package_store.admit(blob,expected_id=package_id,expected_version=version_id)
                if package_id not in {result['package_id'],result['version_id']} or version_id and result['version_id']!=version_id:
                    raise ValueError('DCPM_SOURCE_PACKAGE_MISMATCH')
                return self.package_store.package(package_id,version_id)
            except (OSError,ValueError,ProtocolError) as error: failures.append(type(error).__name__)
        if self.dcpm_node is not None:
            from dcpm_signed import PREFIX
            envelope=await asyncio.wait_for(self.dcpm_node.dht.get(version_id or package_id),15)
            if not isinstance(envelope,str) or not envelope.startswith(PREFIX): raise ValueError('DCPM_UNSIGNED_METADATA')
            blob=base64.b64decode(envelope[len(PREFIX):],validate=True)
            result=self.package_store.admit(blob,expected_id=package_id,expected_version=version_id)
            if package_id not in {result['package_id'],result['version_id']} or version_id and result['version_id']!=version_id:
                raise ValueError('DCPM_DHT_PACKAGE_MISMATCH')
            return self.package_store.package(package_id,version_id)
        raise FileNotFoundError('DCPM_PACKAGE_UNAVAILABLE '+','.join(failures))

    async def install_package(self, package_id: str, version_id: Optional[str] = None, *, package_manager="dpkg", allow_system_install=False):
        """安装软件包"""
        if not allow_system_install: raise PermissionError("DCPM_SYSTEM_INSTALL_REQUIRES_LOCAL_AUTHORIZATION")
        if package_manager not in {"dpkg","rpm"}: raise ValueError("DCPM_EXPLICIT_PACKAGE_MANAGER_REQUIRED")
        package = await self.download_package(package_id, version_id)
        if package:
            package.package_manager=package_manager
            await package.install(allow_system_install=allow_system_install)
            print(f"成功安装 {package.name}-{package.version}")
        else:
            print(f"无法安装 {package_id}")

    async def uninstall_package(self, package_name: str, *, package_manager=None, allow_system_install=False):
        """卸载软件包"""
        await Package.uninstall(package_name,package_manager=package_manager,allow_system_install=allow_system_install)
        print(f"已卸载 {package_name}")

    def _prepare_package_data(self, package: Package) -> Dict:
        from dcpm_signed import encode_package
        public, blob, envelope = encode_package(package,str(self.package_store.key_path))
        return {'type':'dcpm_package','schema':'ziokt.dcpm-package.v1','name':package.name,
            'version':package.version,'publisher':public,'envelope':envelope,
            'sha256':hashlib.sha256(blob).hexdigest()}

    async def _distribute_package(self, package: Package, redundancy: int) -> Dict:
        """分发包内容到存储网络"""
        storage_locations = {
            'ufs_nodes': [],
            'ipfs_cid': None,
            'bt_hash': None
        }
        
        # 1. 上传到UFS网络
        if self.config['network']['prefer_ufs']:
            storage_locations['ufs_nodes'] = await self._store_to_ufs(package, redundancy)
        
        # 2. IPFS作为备份
        if self.ufs_chain.ipfs_client and (not storage_locations['ufs_nodes'] or redundancy > 1):
            storage_locations['ipfs_cid'] = await self._store_to_ipfs(package)
        
        # 3. BitTorrent作为最后选择
        if self.ufs_chain.torrent_session and (not storage_locations['ipfs_cid'] or redundancy > 2):
            storage_locations['bt_hash'] = await self._store_to_bittorrent(package)
        
        return storage_locations

    async def _store_to_ufs(self, package: Package, redundancy: int) -> List[str]:
        """存储到UFS网络"""
        stored_nodes = []
        
        # 对于每个文件，发布到UFS网络
        for fname, data in package.files.items():
            temp_path = Path(self.config['storage']['cache']) / f"temp_{fname}"
            with open(temp_path, 'wb') as f:
                f.write(data)
            
            metadata = await self.ufs_chain.publish_file(
                temp_path,
                'system',
                {'read': ['group:all'], 'write': ['user:system']},
                redundancy
            )
            stored_nodes.extend(metadata['storage']['ufs_nodes'])
            
            temp_path.unlink()
        
        return list(set(stored_nodes))  # 去重

    async def _store_to_ipfs(self, package: Package) -> Optional[str]:
        """存储到IPFS网络"""
        if not self.ufs_chain.ipfs_client:
            return None
            
        try:
            # 创建临时目录
            temp_dir = Path(self.config['storage']['cache']) / f"temp_{package.package_id}"
            temp_dir.mkdir(exist_ok=True)
            
            # 保存所有文件
            file_cids = {}
            for fname, data in package.files.items():
                file_path = temp_dir / fname
                with open(file_path, 'wb') as f:
                    f.write(data)
                
                res = self.ufs_chain.ipfs_client.add(file_path)
                file_cids[fname] = res['Hash']
            
            # 创建目录对象
            dir_res = self.ufs_chain.ipfs_client.add_dict({
                'files': file_cids,
                'metadata': {
                    'name': package.name,
                    'version': package.version
                }
            })
            
            return dir_res['Hash']
        except Exception as e:
            print(f"IPFS存储失败: {e}")
            return None
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

    async def _store_to_bittorrent(self, package: Package) -> Optional[str]:
        """创建BitTorrent种子"""
        if not self.ufs_chain.torrent_session:
            return None
            
        try:
            # 创建临时目录
            temp_dir = Path(self.config['storage']['cache']) / f"temp_{package.package_id}"
            temp_dir.mkdir(exist_ok=True)
            
            # 保存所有文件
            for fname, data in package.files.items():
                with open(temp_dir / fname, 'wb') as f:
                    f.write(data)
            
            # 创建torrent
            fs = lt.file_storage()
            lt.add_files(fs, str(temp_dir))
            t = lt.create_torrent(fs)
            lt.set_piece_hashes(t, str(temp_dir.parent))
            torrent = t.generate()
            
            # 添加到session
            info = lt.torrent_info(torrent)
            self.ufs_chain.torrent_session.add_torrent({
                'ti': info,
                'save_path': str(temp_dir)
            })
            
            return info.info_hash().to_bytes().hex()
        except Exception as e:
            print(f"BitTorrent做种失败: {e}")
            return None
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

    def _check_cache(self, package_id: str, version_id: Optional[str]) -> Optional[Package]:
        """检查本地缓存"""
        cache_file = Path(self.config['storage']['cache']) / f"{package_id}.pkg"
        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    return Package.from_bytes(f.read())
            except:
                pass
        return None

    def _add_to_cache(self, package: Package):
        """添加到本地缓存"""
        cache_file = Path(self.config['storage']['cache']) / f"{package.package_id}.pkg"
        with open(cache_file, 'wb') as f:
            f.write(package.to_bytes())

    async def _query_package_metadata(self, package_id: str) -> Optional[Dict]:
        """查询包元数据"""
        # 1. 检查本地区块链
        for block in reversed(self.blockchain.chain):
            try:
                data = json.loads(block.data)
                if data.get('package_id') == package_id:
                    return data
            except:
                continue
                
        # 2. 查询P2P网络
        return await self.dcpm_node.download_package(package_id)

    def _select_download_source(self, package_data: Dict) -> Dict:
        """选择下载源"""
        # 按配置的fallback顺序选择可用源
        for source_type in self.config['network']['fallback_order']:
            if source_type == 'ufs' and package_data.get('storage', {}).get('ufs_nodes'):
                return {
                    'type': 'ufs',
                    'nodes': package_data['storage']['ufs_nodes']
                }
            elif source_type == 'ipfs' and package_data.get('storage', {}).get('ipfs_cid'):
                return {
                    'type': 'ipfs',
                    'cid': package_data['storage']['ipfs_cid']
                }
            elif source_type == 'bittorrent' and package_data.get('storage', {}).get('bt_hash'):
                return {
                    'type': 'bittorrent',
                    'hash': package_data['storage']['bt_hash']
                }
        
        raise ValueError("没有可用的下载源")

    async def _download_from_source(self, source: Dict, package_data: Dict) -> Optional[Package]:
        """从指定源下载包"""
        if source['type'] == 'ufs':
            return await self._download_from_ufs(source['nodes'], package_data)
        elif source['type'] == 'ipfs':
            return await self._download_from_ipfs(source['cid'], package_data)
        elif source['type'] == 'bittorrent':
            return await self._download_from_bittorrent(source['hash'], package_data)
        return None

    async def _download_from_ufs(self, nodes: List[str], package_data: Dict) -> Optional[Package]:
        """从UFS节点下载"""
        # 简化版本: 尝试从所有节点获取
        for node_id in nodes:
            try:
                # 通过P2P网络获取包数据
                package_bytes = await self.dcpm_node.dht.get(package_data['package_id'])
                if package_bytes:
                    return Package.from_bytes(package_bytes)
            except:
                continue
        return None

    async def _download_from_ipfs(self, cid: str, package_data: Dict) -> Optional[Package]:
        """从IPFS下载"""
        if not self.ufs_chain.ipfs_client:
            return None
            
        try:
            # 下载目录
            temp_dir = Path(self.config['storage']['cache']) / f"temp_{package_data['package_id']}"
            self.ufs_chain.ipfs_client.get(cid, temp_dir)
            
            # 重建包
            package_files = {}
            for fname, meta in package_data['files'].items():
                with open(temp_dir / fname, 'rb') as f:
                    package_files[fname] = f.read()
            
            if package_files:
                return Package(
                    package_data['name'],
                    package_data['version'],
                    package_files,
                    package_data.get('package_manager', 'dpkg'),
                    package_data.get('dependencies', [])
                )
        except Exception as e:
            print(f"从IPFS下载失败: {e}")
            return None
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

    async def _download_from_bittorrent(self, info_hash: str, package_data: Dict) -> Optional[Package]:
        """从BitTorrent下载"""
        if not self.ufs_chain.torrent_session:
            return None
            
        try:
            # 下载torrent
            temp_dir = Path(self.config['storage']['cache']) / f"temp_{package_data['package_id']}"
            temp_dir.mkdir(exist_ok=True)
            
            handle = self.ufs_chain.torrent_session.add_torrent({
                'info_hash': lt.sha1_hash(bytes.fromhex(info_hash)),
                'save_path': str(temp_dir)
            })
            
            # 等待下载完成
            while not handle.status().is_seeding:
                await asyncio.sleep(1)
            
            # 重建包
            package_files = {}
            for fname, meta in package_data['files'].items():
                with open(temp_dir / fname, 'rb') as f:
                    package_files[fname] = f.read()
            
            if package_files:
                return Package(
                    package_data['name'],
                    package_data['version'],
                    package_files,
                    package_data.get('package_manager', 'dpkg'),
                    package_data.get('dependencies', [])
                )
        except Exception as e:
            print(f"从BitTorrent下载失败: {e}")
            return None
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

def parse_args():
    parser = argparse.ArgumentParser(description="DCPM-UFS 整合系统")
    parser.add_argument("--config",dest="global_config",help="Private configuration for one-shot or system commands")
    subparsers = parser.add_subparsers(dest='command', required=True)
    
    # 系统命令
    system_parser = subparsers.add_parser('system', help='系统管理')
    system_parser.add_argument('action', choices=['start', 'stop', 'status'])
    system_parser.add_argument('--config', help='配置文件路径')
    
    # 包管理命令
    package_parser = subparsers.add_parser('package', help='包管理')
    package_subparsers = package_parser.add_subparsers(dest='pkg_command', required=True)
    
    # 发布包
    publish_parser = package_subparsers.add_parser('publish', help='发布包')
    publish_parser.add_argument('path', help='包路径')
    publish_parser.add_argument('--redundancy', type=int, default=3, help='存储冗余度')
    
    # 下载包
    download_parser = package_subparsers.add_parser('download', help='下载包')
    download_parser.add_argument('package_id', help='包ID')
    download_parser.add_argument('--version', help='版本ID')
    
    # 安装包
    install_parser = package_subparsers.add_parser('install', help='安装包')
    install_parser.add_argument('package_id', help='包ID')
    install_parser.add_argument('--version', help='版本ID')
    install_parser.add_argument('--manager',choices=['dpkg','rpm'],default='dpkg')
    install_parser.add_argument('--allow-system-install',action='store_true')
    
    # 卸载包
    uninstall_parser = package_subparsers.add_parser('uninstall', help='卸载包')
    uninstall_parser.add_argument('package_name', help='包名称')
    uninstall_parser.add_argument('--manager',choices=['dpkg','rpm'])
    uninstall_parser.add_argument('--allow-system-install',action='store_true')
    
    # 文件管理命令
    file_parser = subparsers.add_parser('file', help='文件管理')
    file_subparsers = file_parser.add_subparsers(dest='file_command', required=True)
    
    # 发布文件
    file_publish_parser = file_subparsers.add_parser('publish', help='发布文件')
    file_publish_parser.add_argument('path', help='文件路径')
    file_publish_parser.add_argument('--redundancy', type=int, default=3, help='存储冗余度')
    
    # 检索文件
    file_retrieve_parser = file_subparsers.add_parser('retrieve', help='检索文件')
    file_retrieve_parser.add_argument('file_id', help='文件ID')
    file_retrieve_parser.add_argument('--output', help='输出路径')
    
    return parser.parse_args()

async def main():
    args = parse_args()
    system = IntegratedSystem(getattr(args,'config',None) or args.global_config)
    
    try:
        if args.command == 'system':
            if args.action == 'start':
                await system.start()
            elif args.action == 'stop':
                await system.stop()
            elif args.action == 'status':
                print("系统状态: 运行中" if system.running else "系统状态: 停止")
        
        elif args.command == 'package':
            if args.pkg_command == 'publish':
                result = await system.publish_package(args.path, args.redundancy)
                print(f"发布成功: {json.dumps(result, indent=2)}")
            elif args.pkg_command == 'download':
                package = await system.download_package(args.package_id, getattr(args, 'version', None))
                if package:
                    print(f"下载成功: {package.name}-{package.version}")
                else:
                    print("下载失败")
            elif args.pkg_command == 'install':
                await system.install_package(args.package_id,getattr(args,'version',None),package_manager=args.manager,allow_system_install=args.allow_system_install)
            elif args.pkg_command == 'uninstall':
                await system.uninstall_package(args.package_name,package_manager=args.manager,allow_system_install=args.allow_system_install)
        
        elif args.command == 'file':
            if system.ufs_chain is None: raise RuntimeError('UFS legacy file-chain backend must be explicitly started')
            if args.file_command == 'publish':
                metadata = await system.ufs_chain.publish_file(
                    Path(args.path),
                    'cli-user',
                    {'read': ['group:all'], 'write': ['user:cli-user']},
                    args.redundancy
                )
                print(f"文件发布成功: {json.dumps(metadata, indent=2)}")
            elif args.file_command == 'retrieve':
                output_path = Path(args.output) if args.output else None
                file_path = await system.ufs_chain.retrieve_file(args.file_id, output_path)
                if file_path:
                    print(f"文件检索成功: {file_path}")
                else:
                    print("文件检索失败")
    
    except Exception as e:
        print(f"错误: {e}")
        await system.stop()
        sys.exit(1)
    finally:
        await system.stop()

if __name__ == '__main__':
    asyncio.run(main())

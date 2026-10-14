#!/usr/bin/env python3
"""
DCPM-UFS整合系统完整实现
- 统一区块链网络
- 混合存储策略
- 完整P2P支持
- 增强型UFS服务
"""

import os
import sys
import json
import time
import signal
import asyncio
import argparse
from pathlib import Path
from typing import Dict, List, Optional
from dcpm_core import Package, Blockchain, verify_signature, sign_data
from dcpm_p2p import P2PNode
from dcpm_trust import public_key_pem, private_key_pem
import ufsultra
from ufs_blockchain import UFSBlockchainExtension

class IntegratedSystem:
    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        self.node_id = hashlib.sha256(public_key_pem).hexdigest()[:16]
        self.blockchain = Blockchain()
        self.dcpm_node = self._init_dcpm_node()
        self.ufs_chain = UFSBlockchainExtension(
            self.blockchain, self.dcpm_node, self.config, self.node_id
        )
        self.ufs_server = self._init_ufs_server()
        self.running = False

    def _load_config(self, config_path: Optional[str]) -> Dict:
        """加载配置文件"""
        config_paths = [
            Path(config_path) if config_path else None,
            Path('dcpm-ufs-config.json'),
            Path('/etc/dcpm-ufs/config.json'),
            Path.home() / '.config/dcpm-ufs/config.json')
        ]
        
        for path in config_paths:
            if path and path.exists():
                with open(path) as f:
                    config = json.load(f)
                    return self._apply_default_config(config)
        
        return self._default_config()

    def _default_config(self) -> Dict:
        """默认配置"""
        return {
            'node': {
                'id': hashlib.sha256(public_key_pem).hexdigest()[:16],
                'type': 'hybrid',  # 'dcpm', 'ufs', or 'hybrid'
                'name': 'dcpm-ufs-node'
            },
            'p2p': {
                'host': '0.0.0.0',
                'port': 9000,
                'bootstrap_nodes': [],
                'enable_relay': True,
                'enable_dht': True,
                'enable_pubsub': True
            },
            'ufs': {
                'enabled': True,
                'port': 8000,
                'root_dir': './ufs-storage',
                'max_upload': 10 * 1024**3,  # 10GB
                'max_download': 0,  # 0=无限制
                'auth': {
                    'enabled': True,
                    'users': {
                        'admin': {
                            'password': 'admin123',
                            'role': 'admin'
                        }
                    }
                }
            },
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

    def _init_dcpm_node(self) -> P2PNode:
        """初始化DCPM P2P节点"""
        return P2PNode(
            self.config['p2p']['host'],
            self.config['p2p']['port'],
            public_key_pem,
            private_key_pem,
            None,  # TLS cert
            None,  # TLS key
            bootstrap_nodes=self.config['p2p']['bootstrap_nodes'],
            enable_relay=self.config['p2p']['enable_relay'],
            enable_dht=self.config['p2p']['enable_dht'],
            enable_pubsub=self.config['p2p']['enable_pubsub']
        )

    def _init_ufs_server(self) -> ufsultra.UltraServer:
        """初始化增强型UFS服务器"""
        # 修改UFS配置以匹配我们的设置
        ufs_config = {
            'port': self.config['ufs']['port'],
            'root_dir': self.config['storage']['ufs_root'],
            'max_upload': self.config['ufs']['max_upload'],
            'download_limit': self.config['ufs']['max_download'],
            'auth': {
                'enabled': self.config['ufs']['auth']['enabled'],
                'users': self.config['ufs']['auth']['users']
            }
        }

        # 创建自定义请求处理器
        handler_class = self._create_ufs_handler_class()
        
        return ufsultra.UltraServer(
            (self.config['p2p']['host'], self.config['ufs']['port']),
            handler_class,
            config=ufs_config
        )

    def _create_ufs_handler_class(self):
        """创建定制的UFS请求处理器类"""
        class IntegratedUFSHandler(ufsultra.UltraHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.ufs_chain = self.server.integrated_system.ufs_chain
            
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
                    content_length = int(self.headers.get('Content-Length', 0))
                    if content_length > self.cfg['max_upload']:
                        self.send_error(413, "File too large")
                        return
                    
                    # 解析元数据
                    metadata = json.loads(self.headers.get('X-File-Metadata', '{}'))
                    file_name = metadata.get('name', 'file.bin')
                    owner = self.cfg['auth']['user']
                    permissions = metadata.get('permissions', {
                        'read': ['group:admin'],
                        'write': [f"user:{owner}"]
                    })
                    
                    # 保存临时文件
                    temp_path = Path(self.cfg['root_dir']) / f".tmp_{int(time.time())}_{file_name}"
                    with open(temp_path, 'wb') as f:
                        remaining = content_length
                        while remaining > 0:
                            chunk = min(remaining, 1024*1024)
                            data = self.rfile.read(chunk)
                            f.write(data)
                            remaining -= len(data)
                    
                    # 发布到区块链网络
                    metadata = await self.ufs_chain.publish_file(
                        temp_path, owner, permissions,
                        redundancy=self.config['storage'].get('redundancy', 3)
                    
                    # 返回响应
                    self.send_response(201)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(metadata).encode())
                
                except Exception as e:
                    self.send_error(500, str(e))
                finally:
                    if temp_path.exists():
                        temp_path.unlink()
            
            async def _handle_retrieve(self):
                """处理文件检索请求"""
                file_id = self.headers.get('X-File-ID')
                if not file_id:
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
                
                with open(file_path, 'rb') as f:
                    shutil.copyfileobj(f, self.wfile)
            
            async def _handle_metadata(self):
                """处理元数据查询请求"""
                file_id = self.headers.get('X-File-ID')
                if not file_id:
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
        """启动整合系统"""
        if self.running:
            return
        
        # 启动P2P节点
        await self.dcpm_node.start()
        
        # 启动UFS服务器
        self.ufs_server.integrated_system = self
        server_thread = threading.Thread(target=self.ufs_server.serve_forever)
        server_thread.daemon = True
        server_thread.start()
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        
        self.running = True
        print(f"整合系统已启动 | 节点ID: {self.node_id}")
        
        # 主循环
        while self.running:
            await asyncio.sleep(1)

    async def stop(self):
        """停止整合系统"""
        if not self.running:
            return
        
        self.running = False
        await self.dcpm_node.stop()
        self.ufs_server.shutdown()
        await self.ufs_chain.cleanup()
        print("整合系统已停止")

    def _handle_shutdown(self, signum, frame):
        """处理关闭信号"""
        asyncio.create_task(self.stop())

    async def publish_package(self, package_path: str, redundancy: int = 3) -> Dict:
        """
        发布软件包到整合网络
        :param package_path: 包文件路径
        :param redundancy: 存储冗余度
        :return: 发布结果
        """
        package = Package.from_file(package_path)
        
        # 1. 将包元数据写入区块链
        package_data = self._prepare_package_data(package)
        self.blockchain.add_data(json.dumps(package_data))
        await self.blockchain.mine_block()
        
        # 2. 分发包内容到存储网络
        storage_locations = await self._distribute_package(package, redundancy)
        
        # 3. 更新元数据包含存储位置
        package_data['storage'] = storage_locations
        await self.dcpm_node.publish_package(package_data)
        
        return {
            'package_id': package.package_id,
            'version_id': package.version_id,
            'storage': storage_locations,
            'block': self.blockchain.chain[-1].index
        }

    async def download_package(self, package_id: str, version_id: Optional[str] = None) -> Optional[Package]:
        """
        从整合网络下载软件包
        :param package_id: 包ID
        :param version_id: 可选版本ID
        :return: Package对象或None
        """
        # 1. 检查本地缓存
        cached = self._check_cache(package_id, version_id)
        if cached:
            return cached
        
        # 2. 查询区块链获取元数据
        package_data = await self._query_package_metadata(package_id)
        if not package_data:
            print(f"无法找到软件包 {package_id}")
            return None
            
        # 3. 选择最优下载源
        source = self._select_download_source(package_data)
        print(f"从 {source['type']} 下载包 {package_id}")
        
        # 4. 执行下载
        package = await self._download_from_source(source, package_data)
        if package:
            self._add_to_cache(package)
        return package

    async def install_package(self, package_id: str, version_id: Optional[str] = None):
        """安装软件包"""
        package = await self.download_package(package_id, version_id)
        if package:
            await package.install()
            print(f"成功安装 {package.name}-{package.version}")
        else:
            print(f"无法安装 {package_id}")

    async def uninstall_package(self, package_name: str):
        """卸载软件包"""
        await Package.uninstall(package_name)
        print(f"已卸载 {package_name}")

    def _prepare_package_data(self, package: Package) -> Dict:
        """准备包元数据"""
        return {
            'type': 'dcpm_package',
            'software_id': package.software_id,
            'package_id': package.package_id,
            'version_id': package.version_id,
            'name': package.name,
            'version': package.version,
            'source': 'SELF',
            'dependencies': package.dependencies,
            'files': {
                fname: {
                    'size': len(data),
                    'hashes': {
                        'md5': hashlib.md5(data).hexdigest(),
                        'sha256': hashlib.sha256(data).hexdigest()
                    }
                } for fname, data in package.files.items()
            },
            'timestamp': int(time.time()),
            'signature': sign_data(str(package), private_key_pem)
        }

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
    
    # 卸载包
    uninstall_parser = package_subparsers.add_parser('uninstall', help='卸载包')
    uninstall_parser.add_argument('package_name', help='包名称')
    
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
    system = IntegratedSystem(args.config if hasattr(args, 'config') else None)
    
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
                await system.install_package(args.package_id, getattr(args, 'version', None))
            elif args.pkg_command == 'uninstall':
                await system.uninstall_package(args.package_name)
        
        elif args.command == 'file':
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

if __name__ == '__main__':
    asyncio.run(main())
#!/usr/bin/env python3
"""
UFS区块链完整实现
- 去中心化文件存储
- 区块链元数据验证
- 智能合约集成
- 混合存储策略
"""

import os
import json
import time
import shutil
import asyncio
import aiohttp
import hashlib
import ipfshttpclient
import libtorrent as lt
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend
from dcpm_core import Blockchain, Package, verify_signature, sign_data
from dcpm_p2p import P2PNode, DHTNode
from dcpm_trust import public_key_pem, private_key_pem

class UFSBlockchainExtension:
    def __init__(self, blockchain: Blockchain, p2p_node: P2PNode, 
                 config: Dict, node_id: str):
        """
        初始化UFS区块链扩展
        :param blockchain: 共享区块链实例
        :param p2p_node: P2P节点实例
        :param config: 配置字典
        :param node_id: 当前节点ID
        """
        self.blockchain = blockchain
        self.p2p_node = p2p_node
        self.config = config
        self.node_id = node_id
        self.file_index = {}  # {file_id: {'nodes': [], 'metadata': {}}}
        self.local_storage = Path(config['storage']['ufs_root'])
        self.local_storage.mkdir(parents=True, exist_ok=True)
        
        # 初始化存储后端
        self.ipfs_client = self._init_ipfs()
        self.torrent_session = self._init_bittorrent()
        
        # 定期任务
        self.background_tasks = set()
        self._start_periodic_tasks()

    def _init_ipfs(self):
        """初始化IPFS客户端"""
        if not self.config['ipfs']['enabled']:
            return None
        try:
            return ipfshttpclient.connect(self.config['ipfs']['gateway'])
        except Exception as e:
            print(f"IPFS初始化失败: {e}")
            return None

    def _init_bittorrent(self):
        """初始化BitTorrent会话"""
        if not self.config['bittorrent']['enabled']:
            return None
        try:
            session = lt.session()
            session.listen_on(
                self.config['bittorrent']['listen_port'],
                self.config['bittorrent']['listen_port'] + 10
            )
            return session
        except Exception as e:
            print(f"BitTorrent初始化失败: {e}")
            return None

    def _start_periodic_tasks(self):
        """启动后台定期任务"""
        # 索引同步任务
        task = asyncio.create_task(self._sync_index_periodically())
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
        
        # 存储验证任务
        task = asyncio.create_task(self._verify_storage_periodically())
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def _sync_index_periodically(self, interval: int = 300):
        """定期同步文件索引"""
        while True:
            await asyncio.sleep(interval)
            try:
                await self._sync_file_index()
            except Exception as e:
                print(f"索引同步失败: {e}")

    async def _verify_storage_periodically(self, interval: int = 600):
        """定期验证存储完整性"""
        while True:
            await asyncio.sleep(interval)
            try:
                await self._verify_local_storage()
            except Exception as e:
                print(f"存储验证失败: {e}")

    async def publish_file(self, file_path: Path, owner: str, 
                         permissions: Dict, redundancy: int = 3) -> Dict:
        """
        发布文件到去中心化网络
        :param file_path: 本地文件路径
        :param owner: 文件所有者
        :param permissions: 权限设置
        :param redundancy: 存储冗余度
        :return: 文件元数据
        """
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 1. 计算文件哈希和签名
        file_id, checksums = await self._calculate_file_hashes(file_path)
        signature = self._sign_file_metadata(file_id, str(file_path), owner)

        # 2. 创建文件元数据
        metadata = {
            "type": "ufs_file",
            "file_id": file_id,
            "path": str(file_path),
            "size": file_path.stat().st_size,
            "hashes": checksums,
            "owner": owner,
            "permissions": permissions,
            "timestamp": int(time.time()),
            "signature": signature,
            "storage": {
                "ufs_nodes": [],
                "ipfs_cid": None,
                "bt_hash": None
            }
        }

        # 3. 分块存储文件内容
        await self._distribute_file(file_path, file_id, metadata, redundancy)

        # 4. 将元数据写入区块链
        self.blockchain.add_data(json.dumps(metadata))
        await self.blockchain.mine_block()

        # 5. 更新本地索引
        self._update_file_index(file_id, metadata)

        return metadata

    async def retrieve_file(self, file_id: str, target_path: Optional[Path] = None) -> Optional[Path]:
        """
        从去中心化网络检索文件
        :param file_id: 文件ID
        :param target_path: 目标保存路径
        :return: 文件路径或None
        """
        # 1. 检查本地缓存
        local_file = self._check_local_cache(file_id)
        if local_file:
            return local_file

        # 2. 查询区块链获取元数据
        metadata = await self._query_file_metadata(file_id)
        if not metadata:
            return None

        # 3. 验证元数据签名
        if not self._verify_file_metadata(metadata):
            print("文件元数据验证失败")
            return None

        # 4. 选择下载源
        source = self._select_file_source(metadata)
        print(f"从 {source['type']} 下载文件 {file_id}")

        # 5. 下载文件
        file_path = await self._download_file_from_source(
            source, 
            metadata,
            target_path or self.local_storage / metadata['path'].split('/')[-1]
        )

        if file_path and file_path.exists():
            # 验证文件哈希
            _, checksums = await self._calculate_file_hashes(file_path)
            if checksums != metadata['hashes']:
                file_path.unlink()
                print("文件哈希不匹配")
                return None

            return file_path

        return None

    async def _calculate_file_hashes(self, file_path: Path) -> Tuple[str, Dict]:
        """计算文件哈希(SHA256, MD5, SHA1)"""
        hashers = {
            'md5': hashlib.md5(),
            'sha1': hashlib.sha1(),
            'sha256': hashlib.sha256()
        }

        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                for h in hashers.values():
                    h.update(chunk)

        file_id = hashers['sha256'].hexdigest()
        checksums = {name: h.hexdigest() for name, h in hashers.items()}

        return file_id, checksums

    def _sign_file_metadata(self, file_id: str, file_path: str, owner: str) -> str:
        """签名文件元数据"""
        data = f"{file_id}:{file_path}:{owner}:{int(time.time())}"
        return sign_data(data, private_key_pem)

    async def _distribute_file(self, file_path: Path, file_id: str, 
                             metadata: Dict, redundancy: int):
        """分发文件到存储网络"""
        # 1. 本地存储
        local_copy = self.local_storage / f"{file_id}_{file_path.name}"
        shutil.copy(file_path, local_copy)
        metadata['storage']['ufs_nodes'].append(f"{self.node_id}")

        # 2. 发布到P2P网络
        await self._publish_to_p2p_network(file_id, file_path, metadata, redundancy)

        # 3. IPFS存储
        if self.ipfs_client and redundancy > 1:
            try:
                res = self.ipfs_client.add(file_path)
                metadata['storage']['ipfs_cid'] = res['Hash']
            except Exception as e:
                print(f"IPFS存储失败: {e}")

        # 4. BitTorrent做种
        if self.torrent_session and redundancy > 2:
            try:
                fs = lt.file_storage()
                lt.add_files(fs, str(file_path))
                t = lt.create_torrent(fs)
                lt.set_piece_hashes(t, str(file_path.parent))
                torrent = t.generate()
                
                info = lt.torrent_info(torrent)
                self.torrent_session.add_torrent({
                    'ti': info,
                    'save_path': str(file_path.parent)
                })
                metadata['storage']['bt_hash'] = info.info_hash().to_bytes().hex()
            except Exception as e:
                print(f"BitTorrent做种失败: {e}")

    async def _publish_to_p2p_network(self, file_id: str, file_path: Path,
                                    metadata: Dict, redundancy: int):
        """发布文件到P2P网络"""
        # 1. 将文件分块并发布到DHT
        file_data = file_path.read_bytes()
        block_size = self.config['storage'].get('block_size', 1024*1024)  # 1MB
        blocks = [file_data[i:i+block_size] for i in range(0, len(file_data), block_size)]
        
        # 2. 存储块哈希到DHT
        block_hashes = []
        for i, block in enumerate(blocks):
            block_hash = hashlib.sha256(block).hexdigest()
            block_key = f"{file_id}:{i}"
            await self.p2p_node.dht.put(block_key, block_hash)
            block_hashes.append(block_hash)
        
        # 3. 广播文件可用性
        advertisement = {
            'file_id': file_id,
            'block_hashes': block_hashes,
            'node_id': self.node_id,
            'timestamp': int(time.time()),
            'signature': sign_data(f"{file_id}:{self.node_id}", private_key_pem)
        }
        await self.p2p_node.broadcast('ufs_file_ad', json.dumps(advertisement))

    async def _sync_file_index(self):
        """同步文件索引到P2P网络"""
        # 1. 从DHT获取最新的文件索引
        latest_index = await self.p2p_node.dht.get('ufs_file_index')
        if latest_index:
            remote_index = json.loads(latest_index)
            # 合并索引
            for file_id, entry in remote_index.items():
                if file_id not in self.file_index:
                    self.file_index[file_id] = entry
                else:
                    # 合并节点列表
                    self.file_index[file_id]['nodes'] = list(set(
                        self.file_index[file_id]['nodes'] + entry['nodes']
                    ))

        # 2. 发布本地索引
        await self.p2p_node.dht.put(
            'ufs_file_index', 
            json.dumps(self.file_index)
        )

    async def _verify_local_storage(self):
        """验证本地存储的文件完整性"""
        for file_entry in self.file_index.values():
            file_id = file_entry['metadata']['file_id']
            local_file = self._check_local_cache(file_id)
            if local_file:
                # 验证哈希
                _, checksums = await self._calculate_file_hashes(local_file)
                if checksums != file_entry['metadata']['hashes']:
                    print(f"文件 {file_id} 损坏，重新下载...")
                    await self.retrieve_file(file_id, local_file)

    def _update_file_index(self, file_id: str, metadata: Dict):
        """更新本地文件索引"""
        if file_id not in self.file_index:
            self.file_index[file_id] = {
                'nodes': [self.node_id],
                'metadata': metadata
            }
        else:
            if self.node_id not in self.file_index[file_id]['nodes']:
                self.file_index[file_id]['nodes'].append(self.node_id)
            self.file_index[file_id]['metadata'] = metadata

    def _check_local_cache(self, file_id: str) -> Optional[Path]:
        """检查本地缓存"""
        for f in self.local_storage.glob(f"{file_id}_*"):
            return f
        return None

    async def _query_file_metadata(self, file_id: str) -> Optional[Dict]:
        """查询文件元数据"""
        # 1. 检查本地索引
        if file_id in self.file_index:
            return self.file_index[file_id]['metadata']

        # 2. 查询区块链
        for block in reversed(self.blockchain.chain):
            try:
                data = json.loads(block.data)
                if data.get('type') == 'ufs_file' and data.get('file_id') == file_id:
                    return data
            except:
                continue
        
        # 3. 查询P2P网络
        metadata = await self.p2p_node.dht.get(f"ufs_file_meta:{file_id}")
        if metadata:
            return json.loads(metadata)
        
        return None

    def _verify_file_metadata(self, metadata: Dict) -> bool:
        """验证文件元数据签名"""
        data = f"{metadata['file_id']}:{metadata['path']}:{metadata['owner']}:{metadata['timestamp']}"
        return verify_signature(data, metadata['signature'], public_key_pem)

    def _select_file_source(self, metadata: Dict) -> Dict:
        """选择文件下载源"""
        # 按配置的fallback顺序选择
        for source_type in self.config['network']['fallback_order']:
            if source_type == 'ufs' and metadata['storage'].get('ufs_nodes'):
                return {
                    'type': 'ufs',
                    'nodes': metadata['storage']['ufs_nodes']
                }
            elif source_type == 'ipfs' and metadata['storage'].get('ipfs_cid'):
                return {
                    'type': 'ipfs',
                    'cid': metadata['storage']['ipfs_cid']
                }
            elif source_type == 'bittorrent' and metadata['storage'].get('bt_hash'):
                return {
                    'type': 'bittorrent',
                    'hash': metadata['storage']['bt_hash']
                }
        
        raise ValueError("没有可用的文件源")

    async def _download_file_from_source(self, source: Dict, 
                                       metadata: Dict, 
                                       target_path: Path) -> Optional[Path]:
        """从指定源下载文件"""
        if source['type'] == 'ufs':
            return await self._download_from_ufs(source['nodes'], metadata, target_path)
        elif source['type'] == 'ipfs':
            return await self._download_from_ipfs(source['cid'], metadata, target_path)
        elif source['type'] == 'bittorrent':
            return await self._download_from_bittorrent(source['hash'], metadata, target_path)
        return None

    async def _download_from_ufs(self, nodes: List[str], 
                               metadata: Dict, 
                               target_path: Path) -> Optional[Path]:
        """从UFS节点下载文件"""
        file_id = metadata['file_id']
        file_name = metadata['path'].split('/')[-1]
        
        # 尝试从已知节点下载
        for node_id in nodes:
            try:
                # 通过P2P网络获取文件块
                blocks = []
                for i, block_hash in enumerate(metadata.get('block_hashes', [])):
                    block_key = f"{file_id}:{i}"
                    block_data = await self.p2p_node.dht.get(block_key)
                    if block_data:
                        blocks.append(block_data)
                
                if blocks:
                    # 组合文件
                    file_data = b''.join(blocks)
                    with open(target_path, 'wb') as f:
                        f.write(file_data)
                    return target_path
            except Exception as e:
                print(f"从节点 {node_id} 下载失败: {e}")
                continue
        
        return None

    async def _download_from_ipfs(self, cid: str, 
                                metadata: Dict, 
                                target_path: Path) -> Optional[Path]:
        """从IPFS下载文件"""
        if not self.ipfs_client:
            return None
            
        try:
            self.ipfs_client.get(cid, target_path.parent)
            downloaded_file = target_path.parent / cid / metadata['path'].split('/')[-1]
            if downloaded_file.exists():
                shutil.move(str(downloaded_file), str(target_path))
                shutil.rmtree(target_path.parent / cid)
                return target_path
        except Exception as e:
            print(f"从IPFS下载失败: {e}")
        
        return None

    async def _download_from_bittorrent(self, info_hash: str, 
                                      metadata: Dict, 
                                      target_path: Path) -> Optional[Path]:
        """从BitTorrent下载文件"""
        if not self.torrent_session:
            return None
            
        try:
            handle = self.torrent_session.add_torrent({
                'info_hash': lt.sha1_hash(bytes.fromhex(info_hash)),
                'save_path': str(target_path.parent)
            })
            
            # 等待下载完成
            while not handle.status().is_seeding:
                await asyncio.sleep(1)
                
            # 验证下载的文件
            downloaded_file = target_path.parent / metadata['path'].split('/')[-1]
            if downloaded_file.exists():
                return downloaded_file
        except Exception as e:
            print(f"从BitTorrent下载失败: {e}")
        
        return None

    async def cleanup(self):
        """清理资源"""
        if self.torrent_session:
            self.torrent_session.pause()
        if self.ipfs_client:
            self.ipfs_client.close()
# dcpm_core.py

import hashlib
import time
import os
import asyncio
from collections import namedtuple
import struct
import pickle
import binascii
import tempfile
import json
import sys
import base64
from pathlib import Path
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from dcpm_safe import safe_pickle, parse_metadata, package_path, package_label, MAX_BYTES


def get_software_id(name):
    """根据软件名称计算软件 ID"""
    return hashlib.sha256(name.encode()).hexdigest()


def get_package_id(name, source):
    """根据软件名称和信任源计算包 ID"""
    return hashlib.sha256(f"{name}@{source}".encode()).hexdigest()


def get_version_id(name, source, version, parent_version=None):
    """根据软件名称、信任源、版本号和上游版本计算版本 ID"""
    if parent_version:
        content = f"{name}@{source}:{version}<=>{parent_version}"
    else:
        content = f"{name}@{source}:{version}"
    return hashlib.sha256(content.encode()).hexdigest()


# DHT 节点的列表
DHT_NODES = json.loads(os.environ.get("ZIOKT_DCPM_DHT_NODES", "[]"))
if not isinstance(DHT_NODES, list) or len(DHT_NODES) > 8 or any(not isinstance(url, str) or len(url) > 2048 for url in DHT_NODES):
    raise ValueError("DCPM_DHT_CONFIGURATION")


class DHTNode:
    def __init__(self, node_url, protocol="http"):
        self.node_url = node_url
        self.protocol = protocol
        self.data = {}

    async def _http(self, endpoint, params):
        if os.environ.get("ZIOKT_AIRGAP", "").lower() in {"1", "true", "yes"}:
            raise PermissionError("AIRGAP_DENIED: native DCPM networking disabled")
        from urllib.parse import urlsplit, urlencode
        from urllib.request import build_opener, HTTPRedirectHandler
        parsed = urlsplit(self.node_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("DCPM_DHT_URL")
        if parsed.hostname.endswith(".example.com") or parsed.hostname.endswith(".invalid"):
            raise ValueError("DCPM_EXAMPLE_DHT_NOT_PRODUCTION")
        if len(str(params.get("key", ""))) > 256: raise ValueError("DCPM_DHT_KEY_LIMIT")
        url = self.node_url.rstrip('/') + endpoint + '?' + urlencode(params)
        # This is the existing GET-based native DHT interface. Servers with a
        # smaller request-line budget return a real HTTP failure, never success.
        if len(url) > MAX_BYTES * 2: raise ValueError("DCPM_DHT_REQUEST_LIMIT")
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ValueError("DCPM_DHT_REDIRECT_REJECTED")
        def request():
            with build_opener(NoRedirect()).open(url, timeout=10) as response:
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES: raise ValueError("DCPM_DHT_RESPONSE_LIMIT")
                return data.decode('utf-8')
        return await asyncio.wait_for(asyncio.to_thread(request), 12)

    async def put(self, key, value):
        if self.protocol not in {"http", "https"}:
            raise NotImplementedError("DCPM_BINARY_STREAM_FRAMING_NOT_CONFIGURED")
        if type(value) is bytes:
            value = "dcpm-bytes-v1:" + base64.b64encode(value).decode('ascii')
        if not isinstance(value, str) or len(value.encode()) > MAX_BYTES:
            raise ValueError("DCPM_DHT_VALUE_LIMIT")
        return await self._http('/put', {"key": key, "value": value})

    async def get(self, key):
        if self.protocol not in {"http", "https"}:
            raise NotImplementedError("DCPM_BINARY_STREAM_FRAMING_NOT_CONFIGURED")
        value = await self._http('/get', {"key": key})
        if value.startswith('dcpm-bytes-v1:'):
            return base64.b64decode(value[len('dcpm-bytes-v1:'):], validate=True)
        return value

    async def get_block(self, digest):
        return await self.get(digest)

    async def put_file(self, file_id, file_data):
        """分块存储文件到DHT"""
        blocks = [
            file_data[i : i + BLOCK_SIZE] for i in range(0, len(file_data), BLOCK_SIZE)
        ]
        block_hashes = []
        for i, block in enumerate(blocks):
            block_hash = hashlib.sha256(block).hexdigest()
            block_key = f"{file_id}:{i}"
            await self.put(block_key, block)
            block_hashes.append(block_hash)
        return block_hashes

    async def get_file(self, file_id, block_hashes):
        """从DHT获取文件"""
        if type(block_hashes) is not list or len(block_hashes) > 128:
            raise ValueError("DCPM_BLOCK_MANIFEST_LIMIT")
        file_data = b""
        for i, block_hash in enumerate(block_hashes):
            block_key = f"{file_id}:{i}"
            block_data = await self.get(block_key)
            if type(block_data) is not bytes:
                raise LookupError("DCPM_BLOCK_UNAVAILABLE")
            if len(block_data) > BLOCK_SIZE or hashlib.sha256(block_data).hexdigest() != block_hash:
                raise ValueError("DCPM_BLOCK_INTEGRITY")
            file_data += block_data
            if len(file_data) > MAX_BYTES: raise ValueError("DCPM_CONTENT_LIMIT")
        return file_data


async def put_metadata(key, value):
    if not get_dht_nodes(): raise RuntimeError("DCPM_DHT_NOT_CONFIGURED")
    tasks = []
    for node_url in DHT_NODES:
        node = DHTNode(node_url)
        tasks.append(asyncio.create_task(node.put(key, value)))
    await asyncio.gather(*tasks)


async def get_metadata(key):
    if not get_dht_nodes(): raise RuntimeError("DCPM_DHT_NOT_CONFIGURED")
    for node_url in DHT_NODES:
        node = DHTNode(node_url)
        value = await node.get(key)
        if value:
            return value
    return None


BLOCK_SIZE = 1024 * 1024  # 1MB

FileChecksum = namedtuple("FileChecksum", ["md5", "sha1", "sha256", "crc32"])


class Package:
    def __init__(self, name, version, files, package_manager, dependencies=None):
        self.software_id = get_software_id(name)
        self.package_id = get_package_id(name, "SELF")
        self.version_id = get_version_id(name, "SELF", version)
        self.name = name
        self.version = version
        self.files = files
        self.package_manager = package_manager
        self.dependencies = dependencies or []
        self.block_hashes = []
        self.calculate_checksums()

    def calculate_checksums(self):
        """计算软件包文件的校验和"""
        self.checksums = {}
        for file_path, file_data in self.files.items():
            md5 = hashlib.md5(file_data).hexdigest()
            sha1 = hashlib.sha1(file_data).hexdigest()
            sha256 = hashlib.sha256(file_data).hexdigest()
            crc32 = f'{binascii.crc32(file_data) & 0xffffffff:08x}'
            self.checksums[file_path] = FileChecksum(md5, sha1, sha256, crc32)

    def to_bytes(self):
        """将软件包对象序列化为字节流"""
        data = {
            "name": self.name,
            "version": self.version,
            "files": self.files,
            "package_manager": self.package_manager,
            "dependencies": self.dependencies,
            "checksums": self.checksums,
        }
        return pickle.dumps(data)

    @classmethod
    def from_bytes(cls, data):
        """从字节流反序列化软件包对象"""
        package_data = safe_pickle(data)
        if type(package_data) is not dict or set(package_data) != {"name", "version", "files", "package_manager", "dependencies", "checksums"}:
            raise ValueError("DCPM_PACKAGE_SCHEMA")
        package_label(package_data["name"]); package_label(package_data["version"])
        files = package_data["files"]
        if type(files) is not dict or not 1 <= len(files) <= 128 or any(type(data) is not bytes for data in files.values()) or sum(map(len, files.values())) > MAX_BYTES:
            raise ValueError("DCPM_PACKAGE_LIMIT")
        for path in files: package_path(path)
        deps = package_data["dependencies"]
        if type(deps) is not list or len(deps) > 128: raise ValueError("DCPM_DEPENDENCY_LIMIT")
        for dependency in deps: package_label(dependency)
        package = cls(
            package_data["name"],
            package_data["version"],
            package_data["files"],
            package_data["package_manager"],
            package_data["dependencies"],
        )
        if package.checksums != package_data["checksums"]:
            raise ValueError("DCPM_PACKAGE_CHECKSUM_MISMATCH")
        return package

    async def publish(self, *, signing_key=None):
        """Publish the existing Ziokt signed package format, with a pinned persistent key."""
        from dcpm_signed import encode_package
        public, blob, envelope = encode_package(self, signing_key)
        self.package_id = get_package_id(self.name, public)
        self.version_id = get_version_id(self.name, public, self.version)
        await put_metadata(self.version_id, envelope)
        await put_metadata(self.package_id, envelope)
        return {'package_id': self.package_id, 'version_id': self.version_id, 'publisher': public, 'sha256': hashlib.sha256(blob).hexdigest()}

    async def download(self, *, authority=None):
        from dcpm_signed import decode_package
        authority = authority or os.environ.get("ZIOKT_DCPM_PUBLISHER_PUBLIC_KEY")
        if not isinstance(authority, str) or len(authority) != 64:
            raise PermissionError("DCPM_PINNED_PUBLISHER_REQUIRED")
        package_id = get_package_id(self.name, authority)
        data = await get_metadata(get_version_id(self.name, authority, self.version))
        manifest, files = decode_package(data, authority)
        if manifest['name'] != self.name or manifest['version'] != self.version:
            raise ValueError("DCPM_PACKAGE_IDENTITY_MISMATCH")
        # Only commit verified state. Native manager selection remains local.
        self.files = files; self.dependencies = manifest['dependencies']
        self.package_id = package_id
        self.version_id = get_version_id(self.name, authority, self.version)
        self.calculate_checksums()
        return self

    async def install(self, *, allow_system_install=False):
        """System package execution requires an explicit local owner grant."""
        if not allow_system_install:
            raise PermissionError("DCPM_SYSTEM_INSTALL_REQUIRES_LOCAL_AUTHORIZATION")
        if self.package_manager not in {"dpkg", "rpm"}:
            raise ValueError("DCPM_UNSUPPORTED_PACKAGE_MANAGER")
        # Resolve dependencies before applying any native-system side effects.
        if self.dependencies:
            raise RuntimeError("DCPM_DEPENDENCY_RESOLUTION_NOT_CONFIGURED")
        if not isinstance(self.files, dict) or not 1 <= len(self.files) <= 128:
            raise ValueError("DCPM_PACKAGE_LIMIT")
        if sum(len(data) for data in self.files.values()) > MAX_BYTES:
            raise ValueError("DCPM_PACKAGE_LIMIT")
        for file_path, file_data in self.files.items():
            package_path(file_path)
            if type(file_data) is not bytes: raise ValueError("DCPM_FILE_BYTES_REQUIRED")
        with tempfile.TemporaryDirectory(prefix="dcpm-install-") as directory:
            staged = []
            for file_path, file_data in self.files.items():
                relative = package_path(file_path)
                target = Path(directory) / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as output:
                    output.write(file_data)
                staged.append(target)
            for target in staged:
                operation = "--install"
                process = await asyncio.create_subprocess_exec(self.package_manager, operation, "--", str(target))
                result = await process.wait()
                if result != 0:
                    raise RuntimeError(f"DCPM_INSTALL_FAILED:{result}")
        return True

    @staticmethod
    async def uninstall(package_name, *, package_manager=None, allow_system_install=False):
        if not allow_system_install:
            raise PermissionError("DCPM_SYSTEM_INSTALL_REQUIRES_LOCAL_AUTHORIZATION")
        package_label(package_name)
        if package_manager not in {"dpkg", "rpm"}:
            raise ValueError("DCPM_EXPLICIT_PACKAGE_MANAGER_REQUIRED")
        operation = "--remove" if package_manager == "dpkg" else "--erase"
        process = await asyncio.create_subprocess_exec(package_manager, operation, "--", package_name)
        result = await process.wait()
        if result != 0:
            raise RuntimeError(f"DCPM_UNINSTALL_FAILED:{result}")
        return True


class TrustSource:
    def __init__(self, name, domain, pubkey):
        self.name = name
        self.domain = domain
        self.pubkey = pubkey
        self.fingerprint = hashlib.sha256(pubkey.encode()).hexdigest()
        self.packages = []

    def add_package(self, package):
        self.packages.append(package)

    def __str__(self):
        return f"{self.name}@{self.domain} ({self.fingerprint})"

    def __repr__(self):
        return f"TrustSource('{self.name}', '{self.domain}', '{self.pubkey}')"


class TrustDomain:
    def __init__(self, name, parent=None):
        self.name = name
        self.parent = parent
        self.subtrustdomains = []
        self.trust_sources = []
        self.primary_providers = []
        self.secondary_allowlist = []
        self.secondary_blocklist = []

        # 生成RSA密钥对
        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=None
        )
        public_key = private_key.public_key()

        # 将公钥和私钥序列化为PEM格式
        self.public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def add_primary_provider(self, provider):
        self.primary_providers.append(provider)

    def add_secondary_to_allowlist(self, provider):
        self.secondary_allowlist.append(provider)

    def add_secondary_to_blocklist(self, provider):
        self.secondary_blocklist.append(provider)

    def add_subtrustdomain(self, subtrustdomain):
        self.subtrustdomains.append(subtrustdomain)

    def add_trust_source(self, trust_source):
        self.trust_sources.append(trust_source)

    def sign_data(self, data):
        """使用私钥对数据进行数字签名"""
        private_key = serialization.load_pem_private_key(
            self.private_key_pem, password=None, backend=None
        )
        signature = private_key.sign(
            data.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256(),
        )
        return signature

    def verify_data(self, data, signature):
        """使用公钥验证数字签名"""
        public_key = serialization.load_pem_public_key(
            self.public_key_pem, backend=None
        )
        try:
            public_key.verify(
                signature,
                data.encode(),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )
            return True
        except Exception:
            return False

    def __str__(self):
        if self.parent:
            return f"{self.parent}.{self.name}"
        else:
            return self.name

    def __repr__(self):
        return f"TrustDomain('{self.name}', parent={self.parent})"


class Domain:
    def __init__(self, name, parent=None):
        self.name = name
        self.parent = parent
        self.subdomains = []
        self.trust_sources = []
        self.primary_providers = []
        self.secondary_allowlist = []
        self.secondary_blocklist = []
        # 创建对应的 TrustDomain 对象
        self.trust_domain = TrustDomain(name, parent)

    def add_primary_provider(self, provider):
        self.primary_providers.append(provider)

    def add_secondary_to_allowlist(self, provider):
        self.secondary_allowlist.append(provider)

    def add_secondary_to_blocklist(self, provider):
        self.secondary_blocklist.append(provider)

    def add_subdomain(self, subdomain):
        self.subdomains.append(subdomain)

    def add_trust_source(self, trust_source):
        self.trust_sources.append(trust_source)

    def __str__(self):
        if self.parent:
            return f"{self.parent}.{self.name}"
        else:
            return self.name

    def __repr__(self):
        return f"Domain('{self.name}', parent={self.parent})"


class TrustProvider:
    def __init__(self, name, domain, pubkey, type):
        self.name = name
        self.domain = domain
        self.pubkey = pubkey
        self.type = type  # "primary" 或 "secondary"
        self.fingerprint = hashlib.sha256(pubkey.encode()).hexdigest()

    def __str__(self):
        return f"{self.name}@{self.domain.name} ({self.fingerprint})"

    def __repr__(self):
        return f"TrustProvider('{self.name}', '{self.domain}', '{self.pubkey}', '{self.type}')"


def is_primary_provider_trusted(domain, provider):
    return provider in domain.primary_providers


def is_secondary_provider_allowed(domain, provider, strict_mode=False):
    if strict_mode:
        return provider in domain.secondary_allowlist
    else:
        return provider not in domain.secondary_blocklist


async def verify_package_providers(package):
    # 验证第一类提供者
    if not is_primary_provider_trusted(package.source_domain, package.primary_provider):
        return False

    # 验证第二类提供者
    for provider in package.secondary_providers:
        if not is_secondary_provider_allowed(
            package.source_domain, provider, strict_mode=True
        ):
            return False

    return True


# 创建域
self_domain = Domain("SELF")
other_domain = Domain("EG_OTHER")
sub_domain = Domain("SUB", other_domain)
other_domain.add_subdomain(sub_domain)

# 创建信任源
self_source = TrustSource("SELF", self_domain, "")
self_domain.add_trust_source(self_source)

"""
anthropic_source = TrustSource("Anthropic", other_domain, "abc123...")
other_domain.add_trust_source(anthropic_source)

sub_source = TrustSource("SubSource", sub_domain, "def456...")
sub_domain.add_trust_source(sub_source)
"""

# 创建软件包
package1_files = {
    "dcpm": b"Content of dcpm",
    "dcpm.deb": b"Binary content of dcpm.deb",
}
package1 = Package("dcpm", "1.0.0", package1_files, "dpkg")

package2_files = {
    "dcpm": b"Content of dcpm 1.1.0",
    "dcpm-1.1.0.rpm": b"Binary content of dcpm-1.1.0.rpm",
}
package2 = Package("dcpm", "1.1.0", package2_files, "rpm", dependencies=["dcpm:1.0.0"])

# 将软件包添加到信任源
self_source.add_package(package1)
self_source.add_package(package2)


class BlockHeader:
    def __init__(self, index, timestamp, data_hash, prev_hash):
        self.index = index
        self.timestamp = timestamp
        self.data_hash = data_hash
        self.prev_hash = prev_hash

    def calculate_hash(self):
        """计算区块头的哈希值"""
        header_data = f"{self.index}{self.timestamp}{self.data_hash}{self.prev_hash}"
        return hashlib.sha256(header_data.encode()).hexdigest()


class Blockchain:
    def __init__(self):
        self.chain = []  # 区块链
        self.pending_data = []  # 待打包的数据
        self.create_genesis_block()

    def create_genesis_block(self):
        """创建创世区块"""
        genesis_block = BlockHeader(0, 0, "0" * 64, "0" * 64)
        genesis_block.hash = genesis_block.calculate_hash()
        self.chain.append(genesis_block)

    def add_data(self, data):
        """添加待打包的数据"""
        self.pending_data.append(data)

    async def mine_block(self):
        """打包并添加新的区块"""
        # 计算待打包数据的哈希
        data_hash = hashlib.sha256("".join(self.pending_data).encode()).hexdigest()

        # 创建新的区块头
        index = len(self.chain)
        timestamp = int(time.time())
        prev_hash = self.chain[-1].hash
        new_header = BlockHeader(index, timestamp, data_hash, prev_hash)
        new_header.hash = new_header.calculate_hash()

        # 将新区块添加到区块链
        self.chain.append(new_header)
        self.pending_data = []  # 清空待打包数据

    async def validate_chain(self):
        """验证区块链的完整性"""
        for i in range(1, len(self.chain)):
            current_header = self.chain[i]
            prev_header = self.chain[i - 1]

            # 验证区块头的哈希值
            if current_header.calculate_hash() != current_header.hash:
                return False

            # 验证前一个区块头的哈希值
            if current_header.prev_hash != prev_header.hash:
                return False

        return True


async def validate_package_metadata(package):
    """验证软件包元数据是否存在于区块链上"""
    package_data = {
        "name": package.name,
        "version": package.version,
        "package_manager": package.package_manager,
        "dependencies": package.dependencies,
        "files": {
            file_path: {
                "id": file_meta["id"],
                "size": file_meta["size"],
                "block_hashes": file_meta["block_hashes"],
            }
            for file_path, file_meta in package.files.items()
        },
        "checksums": package.checksums,
    }
    package_data_str = str(package_data)
    package_signature = sign_data(package_data_str, private_key_pem)

    for block in blockchain.chain:
        if block.data_hash == hashlib.sha256(package_data_str.encode()).hexdigest():
            if block.index == 0:
                return False  # 创世区块不应该包含软件包元数据
            prev_block = blockchain.chain[block.index - 1]
            if prev_block.hash == block.prev_hash:
                # 验证软件包签名
                public_key = serialization.load_pem_public_key(public_key_pem)
                if verify_signature(package_data_str, package_signature, public_key):
                    return True
    return False


# Legacy RSA helpers require explicit owner-provided keys. Importing this module
# no longer silently creates an ephemeral publisher identity on every restart.
private_key_pem = None
public_key_pem = None


def sign_data(data, private_key_pem):
    """使用私钥对数据进行数字签名"""
    if private_key_pem is None: raise PermissionError("DCPM_EXPLICIT_RSA_KEY_REQUIRED")
    private_key = serialization.load_pem_private_key(
        private_key_pem, password=None, backend=None
    )
    signature = private_key.sign(
        data.encode(),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256(),
    )
    return signature


def verify_signature(data, signature, public_key_pem):
    """使用公钥验证数字签名"""
    public_key = serialization.load_pem_public_key(public_key_pem, backend=None)
    try:
        public_key.verify(
            signature,
            data.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False


class Network:
    def __init__(self, name, dht_nodes, blockchain=None):
        self.name = name
        self.set_dht_nodes(dht_nodes)
        self.blockchain = blockchain or Blockchain()

    def set_dht_nodes(self, dht_nodes):
        if not isinstance(dht_nodes, list) or len(dht_nodes) > 8 or any(not isinstance(url, str) or len(url) > 2048 for url in dht_nodes):
            raise ValueError("DCPM_DHT_CONFIGURATION")
        self.dht_nodes = list(dht_nodes)

    def set_blockchain(self, blockchain):
        self.blockchain = blockchain


MAIN_NETWORK = Network("main", DHT_NODES)

TEST_NETWORK = Network(
    "test",
    [],
    Blockchain(),
)

CURRENT_NETWORK = MAIN_NETWORK


def get_dht_nodes():
    return CURRENT_NETWORK.dht_nodes


def get_blockchain():
    return CURRENT_NETWORK.blockchain


def switch_network(network_name):
    global CURRENT_NETWORK
    if network_name == "main":
        CURRENT_NETWORK = MAIN_NETWORK
    elif network_name == "test":
        CURRENT_NETWORK = TEST_NETWORK
    else:
        raise ValueError(f"Invalid network name: {network_name}")


def create_network(name, dht_nodes, blockchain=None):
    new_network = Network(name, dht_nodes, blockchain)
    setattr(sys.modules[__name__], name.upper() + "_NETWORK", new_network)
    print(f"New network '{name}' created.")


async def put_metadata(key, value):
    nodes = get_dht_nodes()
    if not nodes: raise RuntimeError("DCPM_DHT_NOT_CONFIGURED")
    results = await asyncio.gather(*(DHTNode(url).put(key, value) for url in nodes), return_exceptions=True)
    accepted = sum(not isinstance(result, BaseException) for result in results)
    if not accepted: raise RuntimeError("DCPM_ALL_DHT_PROVIDERS_FAILED") from results[-1]
    return {"accepted_providers": accepted, "failed_providers": len(results) - accepted}


async def get_metadata(key):
    nodes = get_dht_nodes()
    if not nodes: raise RuntimeError("DCPM_DHT_NOT_CONFIGURED")
    last_error = None; replies = 0
    for node_url in nodes:
        try:
            value = await DHTNode(node_url).get(key); replies += 1
            if value: return value
        except (OSError, ValueError, asyncio.TimeoutError) as error:
            last_error = error
    if not replies: raise RuntimeError("DCPM_ALL_DHT_PROVIDERS_FAILED") from last_error
    return None


async def put_metadata_ipfs(key, value):
    import ipfshttpclient
    ipfs_client = ipfshttpclient.connect()
    res = ipfs_client.add_str(value)
    ipfs_hash = res[-1]["Hash"]
    await put_metadata(key, ipfs_hash)


async def get_metadata_ipfs(key):
    ipfs_hash = await get_metadata(key)
    if ipfs_hash:
        import ipfshttpclient
        ipfs_client = ipfshttpclient.connect()
        value = ipfs_client.cat(ipfs_hash)
        return value
    return None


async def start_bt_seeding(torrent_hash, value):
    import btporrent
    torrent = btporrent.get_torrent(torrent_hash)
    torrent.start_seeding(value)


async def put_metadata_bt(key, value):
    import btporrent
    torrent = btporrent.create_torrent(value)
    torrent_hash = torrent.info_hash
    await put_metadata(key, torrent_hash)
    await start_bt_seeding(torrent_hash, value)


async def get_metadata_bt(key):
    torrent_hash = await get_metadata(key)
    if torrent_hash:
        import btporrent
        torrent = btporrent.get_torrent(torrent_hash)
        value = await torrent.download()
        return value
    return None


blockchain = Blockchain()

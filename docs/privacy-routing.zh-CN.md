# 隐私路由与多跳

Ziokt 的 restricted 社区默认通过 Tor v3 洋葱载体连接，保留最终目标的 TLS 1.3 双向认证、证书主机名验证和签名权限校验。中继拿不到社区内容密钥。网络错误不会触发直连、普通 DNS 查询或 SOCKS 无认证协商。

用户也可显式选择下述 `peer-multihop`，在没有 Tor／I2P 时通过普通用户节点的加密隧道连接。该模式单独启用，不会在 Tor 失败时自动切换。

## 无 Tor／I2P 的用户代理

任何用户都可独立运行轻量代理，无需社区状态目录、签名私钥或社区内容解密密钥。代理只需要自己的传输 TLS 证书和私钥、客户端 CA、获准客户端证书指纹，以及允许连接的下一跳。默认不运行网络监听，代理配置中的 `enabled` 必须为 `true` 才会启动。为其他用户开放时可共享代理地址与证书材料约定，调用者配置两到四个已获授权的用户代理。

代理配置（文件需由当前用户所有且为 `0600`；使用真实绝对路径和地址）：

```json
{
  "schema": "ziokt.peer-proxy.v1",
  "enabled": false,
  "host": "0.0.0.0",
  "port": 24444,
  "certificate": "/absolute/proxy-server.pem",
  "private_key": "/absolute/proxy-server.key",
  "ca": "/absolute/approved-client-ca.pem",
  "trusted_clients": ["<获准客户端证书DER内容的SHA256十六进制指纹>"],
  "targets": [{"host": "198.51.100.20", "port": 24444}],
  "max_connections": 8,
  "max_bytes": 67108864,
  "max_seconds": 60
}
```

明确设置 `enabled: true` 后运行：

```sh
python3 -m ziokt community proxy-serve --config /absolute/proxy.json
```

代理是前台进程，Ctrl-C 停止监听并断开现有连接。上述资源值限制每个实例的并发连接数、每条隧道双向传输的总字节和存活时间；最大允许值分别为 32、128 MiB 和 120 秒。代理不记录原始连接请求、证书、内容或异常堆栈，也不落盘转发数据。拒绝未授权证书、任意目标、域名解析和无界控制帧。

客户端的最终节点配置可使用以下载体片段：

```json
{
  "host": "198.51.100.30",
  "port": 24443,
  "connection_policy": {"mode": "peer-multihop", "allow_direct_fallback": false},
  "carrier": {
    "kind": "peer-multihop",
    "hops": [
      {"host": "198.51.100.10", "port": 24444, "tls_config": "/absolute/peer-a-client.json"},
      {"host": "198.51.100.20", "port": 24444, "tls_config": "/absolute/peer-b-client.json"}
    ]
  }
}
```

每跳 `tls_config` 是现有 `ziokt.remote.v1` 格式，包含相同的跳地址、端口及该跳所需的客户端证书、私钥和 CA 的绝对路径。其证书必须具有对应地址的 IP SAN，且代理允许该客户端证书指纹。每个文件与私钥都遵循原有私有文件校验；其中不能再嵌入载体、候选列表或 rendezvous。代理 A 的目标清单允许 B，代理 B 的目标清单允许最终节点；两跳可以由不同用户、不同 CA 管理。

客户端只建立到 A 的物理连接，在该 mTLS 中创建到 B 的 mTLS，再在全部隧道内与最终节点建立应用 mTLS。实现使用 [Python SSLObject 和 MemoryBIO](https://docs.python.org/3.12/library/ssl.html) 保留每一层加密。A 只能打开获准的 B，B 只能打开获准的最终节点；中间用户不能读取社区 API、消息或文件明文。证书与主机名校验、控制握手以及最后的 HTTP 请求共享一次 30 秒预算。TLS 错误、拒绝、超时或字节预算耗尽会关闭整条路径，无自动直连重试。

地址采用 IPv4／IPv6 字面值以避免 DNS 泄漏和地址重绑定；重复的代理地址加端口及与最终节点重合的代理会被拒绝。每个代理需要可达的监听地址；可通过已审查的 Shadow6 原生服务、显式 Tor/I2P 接入或映射接入。可选签名发现和 Nim ICE 配置见下文。节点 IP、相邻节点、时序和流量大小仍可见，代理可按传输客户端证书识别调用者；这是轻量加密多跳，并不等同于 Tor／I2P 匿名性。`restricted` 仅在显式配置该载体时允许使用，`anonymous` 路由允许显式 Tor 或 I2P 载体。独立的隐私审查不会把普通用户代理声称为已验证 Tor 匿名载体。

## 洋葱中继链

在现有 `ziokt.remote.v1` 客户端配置中，`carrier.hops` 可列出最多三个中间 SOCKS5 洋葱服务。省略该字段沿用原来的单个本地 Tor 接入。以下片段需要合并到已有证书配置；占位主机名需替换为实际、校验有效且互不相同的 Tor v3 地址。

```json
{
  "host": "<最终节点的v3地址>.onion",
  "port": 443,
  "connection_policy": {"mode": "anonymous", "allow_direct_fallback": false},
  "carrier": {
    "kind": "tor-socks5",
    "proxy_host": "127.0.0.1",
    "proxy_port": 9050,
    "hops": [
      {"host": "<中继A的v3地址>.onion", "port": 1080},
      {"host": "<中继B的v3地址>.onion", "port": 1080}
    ]
  }
}
```

连接顺序是：本地 Tor SOCKS → A 的洋葱 SOCKS 服务 → B 的洋葱 SOCKS 服务 → 最终节点 → 端到端 mTLS。每次 SOCKS 协商使用新的随机隔离值。每个中间节点需要提供可通过洋葱服务访问的 Tor SOCKS5 端口，并启用 `IsolateSOCKSAuth`。可由运营者将其 Tor SOCKS 监听端口映射到 `HiddenServicePort`；应采用 Tor v3 客户端授权控制使用者，授权密钥由相应 Tor 进程管理。Ziokt 不修改 Tor 配置或系统路由。

客户端在联网前检查所有中继的地址、端口、数量以及重复地址，整条链共享一次连接的时间预算（默认 30 秒），随后 mTLS 和 HTTP 使用该请求预算的剩余时间。中间节点仍可见下一跳地址和传输时序；最终节点按权限识别调用成员。随机隔离值依据 [Tor SOCKS 扩展规范](https://spec.torproject.org/socks-extensions.html) 提交，实际电路隔离取决于 Tor 配置。增加中继会增加延迟，不能证明抵抗全局流量关联或节点串通。

## 批准候选路径

客户端配置支持 `candidates`，候选项必须包括 `approved`、`observed`、具体 `host`、`port`，以及所需的 `carrier`。候选传输设置不会继承父配置中的未选中直连地址；证书、CA 和本地私钥仍由父配置固定。

```json
{
  "connection_policy": {"mode": "approved-paths", "allow_direct_fallback": false},
  "candidates": [{
    "approved": true,
    "observed": {
      "end_to_end_authentication": true,
      "encrypted_content": true,
      "private_discovery": true,
      "anonymous_carrier": true,
      "direct_fallback": false
    },
    "host": "<批准目标的v3地址>.onion",
    "port": 443,
    "carrier": {"kind": "tor-socks5", "proxy_host": "127.0.0.1", "proxy_port": 9050}
  }]
}
```

`observed` 是运营者提供的审查信息；restricted 仍独立检查实际洋葱载体，声明匿名但配置直连的候选会被拒绝。最多四个候选，按顺序选择第一个满足审查要求的候选并验证其传输配置。配置有误或连接失败即中止此次操作，避免重复提交状态不明的写请求。候选选择应用于社区拉取、推送、opaque rendezvous 及 remote CLI。仅含观察结果而无传输设置的旧候选需要补全。

无 Tor 的候选可显式指定自己的 `connection_policy.mode: peer-multihop`、禁止回退及对应载体。此时审查认证、内容加密和私有发现要求，不要求伪造 `anonymous_carrier: true`。其余 restricted 候选仍需满足 Tor 载体要求。

## 内容、长度和浏览器隔离

新发出的 rendezvous 使用 `ziokt.rendezvous.v2`：完整 checkpoint 再经社区密钥加密，并填充到至少 16 KiB 的 2 的幂长度。真实长度包含在认证密文内，中继看到的是填充后的摘要、大小和固定 4 KiB 分片。内容接收后先验证签名与密文摘要，再解开填充和恢复 checkpoint。仍可接收旧 v1 包；旧中继与旧接收端需要升级才能处理 v2。填充后的传输预算上限为 32 MiB，接近预算上限的 checkpoint 可能需要分拆。中继依然知道发送者、收件人、社区、策略和有效期；该格式没有隐藏成员关系或实现恒定速率流量。

门户中的 `/site/` 文档使用 CSP `sandbox allow-same-origin`，禁止脚本、表单和外部资源，同时保留本地样式和带认证的文章链接。API 拒绝图片、嵌入文档及顶层导航等浏览器资源请求，仅允许显式 fetch；门户也拒绝跨站浏览器请求。所有响应禁止缓存和 referrer 传播。URL 中的会话令牌不再接受，使用现有 Bearer 会话或 HttpOnly Cookie。需要执行 JavaScript 的网站应部署到独立来源，再制定其资源策略。

`community site --anonymous` 的导出还移除了原始记录键、事件摘要、社区标识和策略摘要；文件名使用导出内序号。文章本身的内容仍由发布者决定，可能包含身份信息。社区内部的文件、名称和作者签名仍保留，以支持权限校验和恢复。

登记材料清除只删除本地密文文件与数据库索引，不覆写可能被替换的文件路径。拒绝符号链接，并启用 SQLite `secure_delete` 清除删除行的数据。链上承诺、其他副本、备份和存储设备的历史内容无法由此操作清除。

## 最新 Actions 修复

已读取 [2026-10-13 的失败运行](https://github.com/txmu/Ziokt/actions/runs/38427974586)，定位三个首发错误：

- 原生集成的 `native provider protocol drift`：锁文件仍引用缺少资产协议的旧源码。更新到已发布且协议副本一致的 Shadow6 `72a36d66`、Corium `de47b69e`，保留协议一致性检查，并在不一致时报告具体文件。
- Windows 登记材料清除测试的 `absolute native path required`：改用临时目录生成当前平台的绝对路径。
- nested NAT 的 `Network is unreachable`：删除接口最后一个地址时默认路由随之消失，增加新地址后恢复客户端默认路由。

portable CI 增加离线 capsule 与站点托管测试，原生构建失败时不再尝试上传尚未生成的产物。多跳测试使用实际 SOCKS 转发连接和 mTLS 服务，检查顺序、隔离值、无本地洋葱 DNS、拒绝认证降级和连接前拒绝非法配置。真实公网 Tor、跨平台 Actions 与全量原生测试的结果应分别记录，不能以本地转发测试替代公网匿名性证明。

用户代理测试还覆盖独立 CA 的两跳和四跳 mTLS、跨代理的同步和推送、代理转发内容不含应用明文、默认关闭、未授权客户端、目标清单及字节限制。nested NAT CI 使用两个没有社区内容密钥的轻量代理，再连接 opaque rendezvous，并在客户端和外层 NAT 更换地址后验证完整内容。

## I2P 和混合路径

I2P 端点使用固定、规范的 `52字符.b32.i2p`，TLS 证书必须包含该名称。
载体示例：`{"kind":"i2p-sam","proxy_host":"127.0.0.1","proxy_port":7656,"tunnel_length":3,"tunnel_quantity":2,"isolation_scope":"community-a"}`。
SAM 必须在本机运行并由操作者启用。Ziokt 使用 SAM 3.1、Ed25519 和 X25519，保留长期会话，每个进程最多四个会话；默认连接总期限 90 秒。SAM 3.1 的 I2CP 端口是 0，配置中的 HTTP 端口仅用于应用端点标识，路由器必须把该 Destination 映射到正确服务。不会对 I2P 名称做系统 DNS，也不会失败后直连。

`peer-multihop.entry_carrier` 可指定 Tor、I2P 或 `shadow6-stream`，连接第一个代理。代理的本地 `targets[].carrier` 可指定相同载体连接下一跳或最终 I2P 服务。客户端不能远程指定代理所用的 SAM、SDK 或凭据。中间节点通过逐层 TLS 验证，最终社区 mTLS 保留在隧道内部。普通代理路径仍不提供 Tor/I2P 的流量分析抗性。

## 私有签名发现与有界 DHT

在代理配置加入 `discovery`（私有绝对路径），可启用社区成员发现。发现配置为：

```json
{
  "schema": "ziokt.discovery.v1",
  "enabled": true,
  "root": "/private/peers",
  "policy": "/private/signed-policy.json",
  "owner": "社区所有者的64位十六进制公钥",
  "allowed_networks": [],
  "native_bindings": {},
  "client_tls": {"certificate": "/private/client.pem", "private_key": "/private/client.key", "ca": "/private/ca.pem"},
  "hop_count": 2,
  "signing_key": "/private/member.ed25519",
  "endpoints": [{"host": "203.0.113.10", "port": 7443, "fingerprint": "服务端DER证书SHA256", "service": "proxy"}],
  "bootstrap": [{"public_key": "已批准成员公钥", "tls_config": "/private/bootstrap.json", "server_fingerprint": "服务端DER证书SHA256"}],
  "interval": 30
}
```

示例中的地址、公钥、指纹必须替换为真实且审查过的值。仅有 `discover` 权限的现行成员可发布记录；记录绑定政策摘要、epoch、序号、有效期、客户端证书和服务证书。政策回退、同序号分叉、过期记录及未授权私网目标均拒绝。代理不持有社区内容解密密钥；发现签名密钥只属于发布节点自身。

每个目录最多 64 个活动记录；交换最多 8 个、每轮联系最多 2 个节点、批准种子最多 4 个。成员序号高水位跨重启保留。健康依据本地测量，失败指数退避；种子失败后可继续联系已学习成员。XOR 邻居查询、轮转 gossip、证书绑定和本地地址准入降低错误路由及单种子依赖。成员多数恶意或完全失联时仍无法保证发现可用。

客户端远程配置加入 `discovery` 路径，并设置 `connection_policy` 为 `{"mode":"discovered-peers","allow_direct_fallback":false}`。后台工作者学习节点后选择 2～4 个不同成员；前缀多样性在公网优先、显式许可局域网内尽力保证。第一次使用可能返回没有足够合规路径，跟随同步会在后续周期重试；不会暗中减为单跳或直连。

## 全部 Shadow6 Profile 与 Corium

`ziokt profiles --shadow6 /path/to/Shadow6 --purpose discovery` 展示全部 13 个 Profile 的适配计划；`content` 用于原生内容交换，`proxy-stream` 只接受可靠、有序流的 Profile。计划来自源码契约，不能当成运行验证。每条原生路径沿用同一 Core 家族，消息 Profile 使用 Corium 已有的签名、分片和有界重试，保留各自消息上限。

`shadow6-stream` 要求确切 `shadow6_root`、`registry_path`、`service_name`、`lock_digest` 及 `sdk_digest`，摘要均为 `sha256:...`。SDK 摘要对应 `libshadow6/__init__.py`；整个安装树须由本地操作者控制。SDK 打开已运行的审核服务并验证部署锁，不自动创建或重启服务。单会话 Profile 需操作者提供明确生命周期管理。

发现配置可附加 `corium`：`{"federation_config":"/private/federation.json","provider_id":"corium-local","sources":[{"peer_id":"原生Corium身份","digest":"sha256:发现记录数组摘要"}]}`。最多两个固定对象，经 Corium `content.get` 的明确 Shadow6 绑定拉取，再验证社区签名。Corium DHT 地址是线索，不能直接当作代理地址或成员授权。记录数组可经已有 `artifact.stage` 受权工作流发布；Ziokt 不自动公开社区元数据。

Nim agent/client 原生配置支持最多八个显式 `ice_servers`（STUN/TURN/TURNS）和 `ice_transport_policy: all|relay`；relay 必须配置 TURN。TURN 凭据留在私有原生配置文件。未配置时不主动访问外部 STUN。NAT 场景由 ICE 选择可达路径，复杂对称 NAT 可能仍需 TURN。Corium 打洞绑定请求者身份，只使用已存储的批准地址，限制并发、地址数和发送冷却；不能保证穿透所有 NAT。

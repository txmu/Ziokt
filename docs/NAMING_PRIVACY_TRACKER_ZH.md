# 命名、隐私、节点发现与静态建站

本文随联合源码包交付。不要把测试网密码协议、开发中的集成或 DNS 发布功能理解成已经完成独立审计的匿名网络。

## 名称与授权

名称解析不授予登录、发帖、解密、安装、链上写入或中继使用权限。各组件继续校验原生签名、成员身份、权限、受众与重放状态。管理员不能凭解析结果取得其他用户的私钥。

默认每条链使用独立 Namespace；一个 DNS 进程可同时配置多个 realm，每个 realm 固定自己的名称空间、来源节点与信任根。同名记录不跨 realm 自动回退。传统 UDP/TCP 查询使用配置的 default_realm；DoH 可使用 `/realms/<realm>/dns-query` 显式选择。

二级名称来自对应组件节点的登记；三级及更深名称使用逐级 Ed25519 委托。每一级签名绑定名称路径、名称空间、组件、父级版本、当前版本、有效期和下级公钥。父级版本变化、撤回委托或登记到期都会使旧的下级链失效。解析器不接受只有自签名、没有原生/社区登记来源的根名称。

Corium NNS 保留无 TLD 设计。`community.corix` 查询原生 NNS 的 `community`，不会把 `.corix` 存进 NNS。NNS 默认不向 DNS 发布。发布清单 `ziokt_naming.published_suffixes` 明确选择 `.cor/.c/.corium/.corix`，未选择的后缀拒绝解析。没有有效链上登记的 Gateway 乐观缓存行不能成为名称所有权证明。原生所有权转移后，新所有者应重新绑定目标清单；旧所有者的目标不能自动继承为新所有者的有效发布。

Corium 发布清单可带 `identity_registration`（`member_public/policy_digest/issuer`）。解析器独立验证原生身份登记的签名、区块包含关系与当前 NNS 拥有者，再检查它绑定的名称委托公钥；公共 DNS 不输出这份身份信息。身份登记通过仍不意味着获得服务访问权限。

其他组件通过其专属 Companion 节点的加密社区发布。社区拥有者签署根登记，根拥有者逐级签署服务/子域委托。这种证明属于组件社区授权，不冒充 Corium 共识证明。组件桥的 `naming_namespaces` 明确列出可发布的名称空间，默认仅允许本社区 ID。Corium 后缀不能使用这种来源替代 NNS。

公开解析只返回显式批准的 A、AAAA、HTTPS 和受限 TXT 记录。Shadow6 服务 ID、Profile、ETP 端点、身份和私聊路由应放在独立鉴权的内容对象或加密描述中。公共 TXT 只允许描述对象摘要，不允许任意身份/路由转储。私密服务描述使用 X25519、HKDF-SHA256、AES-GCM 和固定 4096 字节封装，绑定名称、名称空间和目标组件；秘密解密材料只能留在客户端。

## 独立部署 DNS

无需公共递归 DNS、系统解析回退或本服务器专用账户。部署者需要自己的对应节点和 Python 依赖：

```sh
python3 -m pip install -r requirements.txt
chmod 600 /path/to/dns.json
python3 -m ziokt.dns_server --config /path/to/dns.json
```

最小双网域配置示例（所有路径换成本机节点实际路径）：

```json
{
  "schema": "ziokt.dns.v2",
  "listen": "127.0.0.1",
  "port": 5353,
  "doh_port": 8188,
  "default_realm": "main",
  "realms": {
    "main": {
      "network_id": "ziokt-main",
      "sources": {
        "corium": {
          "native_network_id": "ziokt-main",
          "forum_db": "/node/var/lib/corix/networks/ziokt-main/forum/forum.db",
          "chain_db": "/node/var/lib/corix/networks/ziokt-main/blockchain/chain.db",
          "objects": "/node/var/lib/corix/p2p/objects"
        },
        "safefs": {"component_bridge": "/node/safefs/bridge.json"}
      }
    },
    "test": {"network_id": "test-local", "sources": {}}
  }
}
```

DoH 监听仅绑定回环地址，必须由可信 HTTPS 反向代理暴露 `/dns-query` 和 `/realms/*/dns-query`。UDP/TCP 可通过 `listen` 显式公开，普通部署默认不开放明文外网端口。DNS 包大小、问题数、EDNS、TCP 会话、工作线程和按来源临时 HMAC 限流都有上限；不记录完整查询日志，不设置伪造的 DNSSEC AD 位。不属于 Ziokt 的后缀返回 REFUSED，绝不调用系统/公共 DNS。未配置某组件的来源返回失败，不能偷偷查询其他组件。

`.chat` 等私有使用后缀可能与公共命名空间冲突。只有显式使用本解析器/分域解析配置的客户端才采用这里的含义。普通浏览器还需要正确的解析配置和可信 TLS 证书；新增私有 TLD 不会自动获得公共 CA 证书。

## 加密边界

DoH 按 RFC 8484 保护客户端至解析器；它不阻止解析器看到查询。HTTPS 服务绑定遵循 RFC 9460，ECH 配置发布遵循 RFC 9848；TLS ECH 本身遵循 RFC 9849。发布 ECHConfigList 不等于 TLS 服务已经启用 ECH，必须另外验收 TLS 终止器和客户端。公共地址、公开发布的所有权事实和流量时间相关性不能宣称完全保密。目前没有把 ODoH、DNSSEC 签名或所有平台的 ECH 实际握手标为已完成。

标准来源：
- https://www.rfc-editor.org/rfc/rfc8484
- https://www.rfc-editor.org/rfc/rfc9460
- https://www.rfc-editor.org/rfc/rfc9848
- https://www.rfc-editor.org/rfc/rfc9849

## 多链共享与 IBC

独立 Namespace 是默认。可选共享 Namespace 指定一条 home chain 作为名称所有权来源，通过 Corium IBC `ZIOKT_NAME_BINDING_V1` 分发短期绑定，不把多个不一致的账本直接拼接为一个登记表。源链验证当前 NNS 拥有者、目标链、名称空间、租约有效期和递增序号；接收端验证治理预置的 checkpoint、历史区块链接、交易内容、Merkle 包含关系、源/目标链、协议启用高度与租约。证明不能自行推进信任 checkpoint。

跨链适配器 `ziokt.ibc_naming.IBCNames` 使用目标节点真实的 `ibc_verifiers` 和 `ibc_incoming_queue`。共享源链升级需要协调协议版本与启用高度；没有合适信任锚时停止接受更新。跨链短期绑定过期后不会恢复旧的正向记录。本地两条真实测试链已完成原生分发、证明、接收和解析；仍须以本次 CI 与实际部署回执验收上线。

## Tracker 与发现

Tracker 是可选的多个 Rendezvous 目录，不能替代 DHT。发现结果统一进入现有 PeerDirectory，沿用成员签名、证书绑定、网络/策略归属、持久化反重放、去重、失效清理与健康评分。DNS Seed 只提供入口提示，不授予信任。

Tracker 复用现有 TLS 1.3 双向认证 `/zfcp`，每次请求另有短期、受众绑定、可防重放的签名授权。接口：`tracker.status/query/register/revoke`。每次返回最多 8 个节点，单租约最多 600 秒。没有 `publish:true` 不登记；普通 DHT/Gossip 数据不自动进入公开目录。登记地址从签名描述读取，绝不从 HTTP 来源 IP 推导。

restricted 策略强制匿名登记。Tor/I2P 端点可以直接登记；其他端点必须有配置中继授权者签发的、绑定节点/策略/端点摘要/过期时间的授权。Tracker 仍会看到向其登记的授权端点及请求时间，应选择可信或匿名载体，不能声称 Tracker 天然无法关联流量。

服务器启动：

```sh
python3 -m ziokt community tracker-serve --root /node/tracker-state \
  --policy /node/policy.json --owner PUBLIC_OWNER_KEY \
  --tls-config /node/tracker-server.json --anonymous-only
```

Discovery 配置可选 `trackers` 数组（最多 4 个），每项为 `tls_config/publish/anonymous/relay_authorization`。默认没有 Tracker。失败的 Tracker 不阻止原生 DHT、Gossip 或直接引导继续运行。DNS/mDNS 等额外发现来源也必须提供可验证的节点描述才能进入候选池，原始地址提示不能直接成为授权连接。

## MCP、TG 与本地秘密

MCP 新增命名状态、公共解析、组件服务描述、组件 `naming.publish`、Tracker 状态和按配置的 Tracker 查询/登记/撤销。写入继续有精确 scope、幂等键和原生校验。组件名称发布接收拥有者的签名登记，不接收私钥。Corium `naming.submit` 原生工作流由配置节点身份签名，只操作该节点确实拥有的 NNS 根，或提交原生贡献证明注册新根；受专用计划权限控制，并明确区分待打包与已上链。需要部署配置后才可查询的接口应返回真实不可用状态，不能制造成功结果。

TG `/dns` 查看网域/来源，`/trackers` 查看可选目录，`/reviews` 列出审查接口；`/mcp 工具名 {JSON参数}` 覆盖全部可用工具。写操作继续使用既有确认流程。钱包、花费秘密、私密描述解密只能在客户端本地执行。

## 链上所有权与审查

`zkn-rct-experimental-v1` 只允许 test-/dev- 网络，生产屏蔽保持关闭。固定单位 NFT 使用 Ristretto255 承诺、一次性公钥、16/32/64 成员环、链上 nullifier 与加密 note；它不等于可用的通用匿名资产系统。透明入池和退出仍公开相关资产，历史交易无法被消除。该新协议没有独立密码审计，不应在生产中开启。

审查请求、冻结的活跃验证者权益投票、撤销和自愿加密披露走原生账本。超过三分之二权益批准也不能自动解密；仍需持有者授权披露，没有全局审查密钥。法律依据摘要不能自动证明请求者具有现实法律资格。

## 论坛、静态站点和重试

浏览器论坛默认只读。用户明确创建/导入自己的签名身份后才能发帖；管理员 Token 不能借用节点身份发帖。Outbox 持久化重试单独隔离失败项，采用有界退避。

`tools/prepare_static_blog.py` 打包已经生成的 Hugo/Hexo/Jekyll/Astro/Eleventy/Zola/MkDocs/Pelican/Docusaurus/VitePress/VuePress/Next export/Gatsby 输出，不在节点执行博客插件或服务端 PHP。支持真实同源 JS、模块、内联脚本哈希、搜索数据和可选 WASM；共用 Gateway 来源采用不含 allow-same-origin 的 sandbox，独立静态来源可启用存储。静态专用 worker 不含管理 API。所有对象/分块验证 SHA-256，缺失块不能拼接成成功响应。

传输仅在批准路径间有界重试，认证失败立即停止；结果未知的原生写操作不自动重复执行。多路径不意味着面对全局流量观察者的绝对匿名，也不承诺任何节点“永远打不死”。

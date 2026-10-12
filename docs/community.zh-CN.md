# Ziokt 私有社区、网络副本与恢复

本实现提供可独立运行的社区应用状态、CLI、本地浏览器入口、mTLS 节点同步和显式 Tor v3 SOCKS5 载体。社区可在 Shadow6 / Corium / 联邦协调器离线时读取本地副本、继续授权范围内的离线编辑、交换加密恢复包。原生安装、运行、Wiki 和 Phoenix 操作仍走原项目的固定工作流与最终权限检查。

## 应用与执行边界

| 应用 | 可执行的社区行为 | 原生执行或额外部署条件 |
|---|---|---|
| Forum | 签名主题/回复、可验证历史、并发版本、管理员删除标记 | 多个用户各自运行节点并配置互相同步 |
| Chat | 社区频道消息、离线保存、节点同步 | 社区共享密钥不等于成熟群组前向保密；独立私密群组使用独立社区 |
| Wiki | 文档更新、保留冲突、显式合并、恢复 | Corium 原生 Wiki 创建可另经原生工作流执行 |
| Files | 定长加密分块、内容索引、完整文件哈希、下载、复制 | 默认单文件 8 MiB；有效副本必须实际保存完整材料 |
| Packages | 签名发布记录、加密软件材料、下载、交给原生 artifact store | Shadow6 原生验包/安装/激活；记录中的 native_signature 不是替代验证器 |
| Mail | 独立 X25519 信箱、收件人加密主题与正文、离线收件、同步、解密 | 当前为社区内部邮件；未实现互联网 SMTP/IMAP 互通 |
| Names | 签名社区名称与目标引用、版本与冲突 | 引用记录不替代互联网 DNS/HTTPS；不自动访问任意 URL |
| Identity | 原始签名者所有权、身份/信箱公钥绑定、携带与撤销 | 权限由当前成员策略决定，显示名不授予权限 |
| Governance | 签名提案、按身份去重的投票、并发票冲突与计票、历史 | 投票结果不自动产生宿主执行权；原生治理 guard 继续独立核验 |
| Hosting | 审查并执行固定原生工作流，保存原始执行回执 | 已配置原生服务与依赖；不把资料恢复当作服务已就绪 |
| Compute | 绑定原生激活引擎的实际执行、签名回执、证明材料、受审查工作流 | 使用 Corium 原有计算引擎与沙箱；不提供任意宿主代码执行 API |
| Recovery | 签名加密检查点、多副本验证、节点销毁后重建、换密钥后保留历史 | 独立保存当前策略、根公钥和当前解密密钥；运行授权须重新核验 |

这张表列出真实实现边界；不能把 Hosting/Compute 记录或 Names 映射当作已完成动态网站、通用计算集群或浏览器 DNS 系统。手机可使用响应式页面，但当前入口仅绑定本机，不包含新 Android 客户端。

## 初始化和本地使用

```sh
python3 -m ziokt community init --root /absolute/village --name village
```

这会创建独立的 `owner.key`、`content.key`、`mailbox.key`、根签名 `policy.json` 和 `state/`。不启动监听、原生服务或 Tor。输出只报告公钥与材料路径。

后续命令共同提供：

```sh
--root /absolute/village/state \
--policy /absolute/village/policy.json \
--owner OWNER_PUBLIC_HEX \
--encryption-key /absolute/village/content.key
```

写入还需 `--signing-key /absolute/village/owner.key`。其他成员应生成自己的签名密钥，根管理者在 policy 的 members 中只授予需要的域权限。不要将 owner 私钥作为所有成员的通用登录密钥。

发布 Wiki 的 `--body` 是私有 JSON 文件：

```json
{"title":"社区资料","text":"第一份可恢复的文档"}
```

```sh
python3 -m ziokt community publish [共同参数] \
  --signing-key /absolute/village/owner.key \
  --domain wiki --object-key handbook --body /absolute/page.json
python3 -m ziokt community view [共同参数] --domain wiki
```

更新默认引用该对象的全部当前 heads。不同节点在断网期间的并发修改都会保留；同步后 `conflicts` 显示多个版本。审核全部版本后发布合并。删除使用 `--delete` 和 `{"reason":"..."}`，且需要独立的 `moderate` 权限。删除不抹去历史或其他参与者已有副本。

## 浏览器入口

```sh
python3 -m ziokt community ui [共同参数] \
  --signing-key /absolute/village/owner.key \
  --mailbox-key /absolute/village/mailbox.key \
  --session-file /absolute/village/browser-session.json
```

服务只绑定 `127.0.0.1`，随机选择端口。私有 session 文件给出 URL 和随机 token；浏览器登录表单输入 token。token 不写入访问日志或 URL。所有数据 API 核验 Bearer、Host 和 Origin，拒绝跨站调用；静态界面有 CSP、无第三方依赖，用户内容用 textContent 展示。页面支持主题切换、键盘操作和窄屏布局。

如需页面中的“同步网络副本”，显式添加 `--peer-tls /absolute/client-tls.json --peer-publisher PEER_RECOVERY_PUBLIC_HEX`。对端地址固定在启动配置中，浏览器不能提交任意目标地址。网络不可用时本地内容仍可读取，发送错误不触发隐私降级。

## 双节点网络

每个节点可同时拥有自己的本地状态和只提供加密副本的网络端点。A、B 分别运行端点并配置对方，互相同步；不要求一个永久中心网站。操作是 pull，双方需要分别同步以得到彼此编辑，不自动宣布或广播对端。

网络端点复用 TLS 1.3 双向证书、证书摘要与签名者绑定、精确 action/resource grant、持久 nonce 和有限执行槽。trusted_clients 的 methods 使用：

- `community.status`
- `community.checkpoint.create`
- `community.checkpoint.get`

providers 使用 community_id。网络签名者还须具有当前策略的 `replicate` 权限；端点的检查点签名者需 `recover` 权限。远端 export 写盘须显式 `allow_mutations: true`。

服务端 TLS 配置沿用 `ziokt.remote.v1`，host 固定 `127.0.0.1`，含 certificate/private_key/ca/replay_state/trusted_clients/allow_mutations。

```sh
python3 -m ziokt community serve [共同参数] \
  --signing-key /absolute/village/owner.key --tls-config /absolute/server-tls.json
python3 -m ziokt community sync [共同参数] \
  --signing-key /absolute/village/member.key \
  --tls-config /absolute/client-tls.json --publisher PEER_RECOVERY_PUBLIC_HEX
```

每次同步先对比经实际文件完整性核验的 inventory digest；相同状态不再下载或创建检查点。不同状态下载一个不可变加密检查点，通过 6144 字节范围读取，绑定完整摘要后再导入。重复请求复用同一 export，避免重试产生无限材料。export 目录最多保留四份不同状态，达到上限时显式 BACKPRESSURE；由操作者审查、归档并删除旧 exchange 文件后继续。不会自动删除社区历史。

## 匿名载体与私有发现

restricted 社区的网络同步要求显式 Tor SOCKS5 carrier：

```json
"carrier": {
  "kind":"tor-socks5",
  "proxy_host":"127.0.0.1",
  "proxy_port":9050
}
```

client TLS 配置 host 必须为校验版本和 checksum 的 v3 `.onion` 地址。目标以 SOCKS5 domain 类型发送，不在本地查询目标 DNS；代理必须是字面量 loopback IP。请求认证协商和独立 stream isolation 值，拒绝协商降级；路径不可用时关闭连接，不尝试目标直连。mTLS 服务器证书仍须匹配 onion 名称，并由已配置 CA 验证。

Tor 服务、HiddenServicePort、可选 onion client authorization 由操作者显式配置。Ziokt 不在后台安装 Tor、创建隐藏监听、修改防火墙或系统服务。真正限制服务地址披露，需要私有邀请、Tor client authorization 和妥善保存 endpoint / onion 私钥。仅仅使用 .onion 不能消除已获地址者的发现能力。

`community invite` 使用 `discover` 权限生成 4096 字节、加密、根策略作用域绑定、有时效的邀请；`community accept` 解密并验签，只返回 endpoint，不授予成员资格或替代 TLS 信任。邀请密钥独立通过受信渠道传递。没有公共社区发现列表。

协议参考：[Tor SOCKS extensions](https://spec.torproject.org/socks-extensions.html)、[Tor v3 地址编码](https://spec.torproject.org/rend-spec/encoding-onion-addresses.html)。

隐私威胁边界：降低内容、服务地址与应用标记的暴露，不保证对全局流量观察者不可发现。定长内容/事件不能隐藏总流量、连接时间或所有 TLS/Core 指纹。失去匿名载体不会同时删除数据或恢复能力，但 restricted 发送会暂停；要改隐私策略须显式发布新签名策略。

## 私信与身份

初始化发布签名的身份/信箱公钥绑定。identity 的对象标识必须等于原签名者公钥，不能抢占他人的身份命名空间。信箱使用独立 X25519 密钥；消息使用临时 X25519、HKDF 和 AES-GCM，2048 字节定长密文存放在社区事件内。

`community mail-send` 指定 recipient；可以显式 pin `--recipient-mailbox`，或从一个无冲突的签名身份绑定取得信箱公钥。`community mail-open` 使用独立 mailbox.key。社区共享 content.key 不能解密私信正文；私信接收者和外层作者、收件人元数据对授权社区成员仍可见。未提供多设备密钥恢复或双棘轮前向保密。

## 副本、管理组件退出和恢复

`community checkpoint` 导出完整的签名加密事件、策略历史、被引用的内容分块及加密索引。文件损坏或材料缺失会使导出失败。`community restore` 在验签、作用域、当前策略、完整字节摘要和因果图检查后恢复；保留并发本地编辑，不回退当前策略。

`community replicate --peer-root A --peer-root B --minimum 2` 实际写入并回读两个独立目录，不能将重复目录或源目录计作副本。结果明确 `failure_domain_independence_verified: false`：不同目录不代表不同机器、电源或区域。真正抗节点死亡应在独立节点上通过 mTLS/批准的原生路径传送并验证。

恢复包不携带 owner.key 或当前 content.key；应独立保存这些恢复材料。协调器进程、门户或原始节点退出后，其他有权节点仍能读取和编辑。若所有可信副本、当前密钥或全部管理签名材料都遗失，本实现不能凭空复活数据或制造新授权。

## 撤销和保密性换钥

仅移除成员权限会阻止新的写入/网络复制，但不能撤回成员已经获得的明文和旧密钥。要阻止其读取未来更新，应发布递增 epoch 的新签名 policy，并为保留成员分发独立的新 content.key。

```sh
python3 -m ziokt community rotate [旧共同参数] \
  --signing-key /absolute/village/owner.key \
  --next-policy /absolute/village/policy-next.json \
  --next-encryption-key /absolute/village/content-next.key
```

先持久保存独立的新密钥和签名 policy，再旋转。历史事件的原签名、密文身份和父引用保留；旧派生密钥只装入由新密钥加密的历史 keyring。旧密钥持有者不能解包当前 keyring；冷恢复只需当前密钥和已 pin 的策略。恢复包把历史 keyring 放在签名加密层内，不改变当前成员权限。默认最多保存 16 个保密性密钥代次。

## 原生软件与工作流

`community materialize --manifest FILE --native-store DIRECTORY` 只把经完整摘要验证的社区材料交给显式指定的原生 artifact store，输出 `native_signature_verified: false`。之后 Shadow6 原生 package.install/package.activate 必须独立验签。CI 覆盖从社区加密软件材料到真正原生安装、激活和篡改拒绝。

`community native --config FEDERATION --journal JOURNAL --manifest WORKFLOW --domain hosting --object-key SERVICE` 先生成可审查计划。执行时还须 `--apply --expected-digest DIGEST --confirm`。每步复查当前社区权限，最终仍由 Native Provider 的动作/资源策略、revision 和租约裁决。保存原生回执为加密文件和签名应用引用，不能把 committed 偷换为 application_ready。Corium 原生 `compute.run` 的 resource 为 `compute:ENGINE_ID`，arguments 为 `{}`：引擎必须在原生允许列表和链上激活状态内，问题集/引擎摘要绑定到准备阶段。实际运行走原来的 corix_compute 与沙箱，有限预算内返回由原生 secp256k1 身份签名的执行回执；证明材料未提交或未经原生验证时保持 proof_verified=false。需原生治理或领导权 fencing 的部署可继续用既有 `workflow apply` 对应参数。

## 性能、预算与测试

- 8 KiB 固定事件，4 KiB 固定内容分块，三级有界加密内容索引，单文件 8 MiB。
- 默认 1024 事件、4096 内容对象、32 MiB 检查点，16 个旧密钥；达到预算明确报错，不默默删除历史或无限增长。init/policy 的 `--limits` 可以在签名策略中降低 events/objects/file_bytes/checkpoint_bytes，不能超过硬安全上限。
- 原始签名验证缓存只在内存中保存，读取仍校验密文摘要和 DB 中实际字节，不接受被更改的本地内容。
- 网络最多八个执行槽、32 个 TLS 连接；本地门户最多16个连接，所有路径有超时和请求预算。
- 没有共识式多主宿主执行、永久匿名、通用 CRDT 编辑器或无限留存保证。成员可导出副本和历史，通过自己的新社区继续组织；迁移后的信任关系须显式批准。

测试覆盖全应用签名往返、实际节点目录删除、并发 Wiki 合并、篡改/旧策略/旧密钥拒绝、换钥后历史保留与冷恢复、真正 mTLS 范围同步、SOCKS5 的目标 DNS 与隔离、门户鉴权/Origin/XSS、软件原生验签和真实 Corium 回执。原生 gate 用十二 Core/十三 Profile 传送实际社区加密内容并解密核对。独立 CI 启动真正临时 Tor onion service 完成 mTLS 社区同步，不把 SOCKS 模拟器称作 Tor 网络证据。

# 原生联邦操作指南

所有操作由各自原生 Provider 最终授权。`enabled` 只开启接入；写操作还须
`allow_mutations`、动作允许列表与资源允许列表。默认配置保持全部关闭。

## 原生配置与动作

S 使用私有 JSON，C 使用其私有 `[ziokt]` INI；C 的布尔值严格为 TRUE/FALSE。
配置文件属于运行者、非符号链接；POSIX 为 0600，Windows 使用真实 owner/DACL。

| Provider | 固定动作 | 原生最终执行者 |
|---|---|---|
| S | service.stop / service.run | ServiceRegistry 的原锁、revision 和生命周期 |
| S | package.install / package.activate | 原生 Ed25519 验包器、版本目录和 active 指针 |
| S | recovery.checkpoint / recovery.restore | 原生材料/锁校验、停止状态服务重建 |
| C | artifact.stage | 内容哈希、原生 local_chunks 登记 |
| C | wiki.create | 原生 ACL 成员权限、上传、交易创建 |
| C | chain.mine | 原生共识/轮次和交易校验，允许原生无操作结果 |
| C | snapshot.create / strata.create | 原快照/Strata 函数与原锁，保留 root 要求 |
| C | recovery.checkpoint / recovery.restore | 原 Phoenix 签名状态导出与冷导入 |

例如 S 的额外配置：

```json
{
  "schema": "ziokt.provider.v1", "enabled": true,
  "federation_id": "home", "provider_id": "shadow6-local",
  "allow_mutations": true,
  "allowed_operations": ["package.install", "package.activate", "service.stop", "service.run", "recovery.checkpoint", "recovery.restore"],
  "allowed_resources": ["app/wiki-client@1.0.0", "home/wiki", "checkpoint:shadow6", "recovery:shadow6"],
  "package_root": "/private/native-packages",
  "package_trust_file": "/private/native-trust.json",
  "artifact_root": "/private/artifacts"
}
```

C 的动作列表和资源列表使用逗号分隔。`artifact_root` 指向显式批准的私有
CAS；配置此项会让授权数据绑定共享该目录中的内容。联邦发布签名始终不能替代
S 的发布者 Ed25519 签名或 C 的原生包信任。

## 可恢复工作流与工作空间

`ziokt.workflow.v1` 使用固定字段，依赖必须按顺序出现，最多 32 步：

```json
{
  "schema": "ziokt.workflow.v1", "workflow_id": "wiki-release",
  "steps": [{
    "step_id": "install", "provider_id": "shadow6-local", "action": "package.install",
    "resource": "app/wiki-client@1.0.0",
    "arguments": {"artifact_digest": "sha256:REPLACE_WITH_64_LOWERCASE_HEX"},
    "expected_revision": null, "depends_on": []
  }, {
    "step_id": "activate", "provider_id": "shadow6-local", "action": "package.activate",
    "resource": "app/wiki-client@1.0.0", "arguments": {},
    "expected_revision": null, "depends_on": ["install"]
  }]
}
```

```sh
python3 -m ziokt workflow plan --config federation.json --journal workflows.sqlite --manifest workflow.json
python3 -m ziokt workflow apply --config federation.json --journal workflows.sqlite wiki-release --expected-digest SHA256_FROM_PLAN --confirm
python3 -m ziokt workflow status --journal workflows.sqlite wiki-release
```

plan 固定工作流摘要；apply 为每一步获取原生 prepare 后再 commit，不能跳过
原生权限、签名、revision 或当前租约。重复调用/重启先查询原生记录。未知结果保持
unknown，执行租约结束后显式 reconcile；仅支持已定义的后置条件。不可逆副作用
不会伪装成可自动回滚。并发协调尝试使用持久化有界租约。

`workspace --manifest workspace.json --config federation.json --steps steps.json
--journal workflows.sqlite` 将 `ziokt.workspace.v1` 的服务、应用、包、身份引用
及隐私/恢复意图与同一原生工作流关联。添加 `--apply --expected-digest ... --confirm`
执行并重新读取双方投影。引用解析、原生激活、传输就绪和应用就绪分别表示；存储记录
不能声明为在线服务。控制面离线后，既有 S/C 进程与对象仍由原生项目管理。

## 双向数据绑定

C 的 `transport_bindings_file` 是私有 JSON：

```json
{
  "schema": "ziokt.transport-bindings.v1", "network_id": "default",
  "bindings": [{
    "peer_id": "REPLACE_WITH_NATIVE_CORIUM_ID",
    "shadow6_root": "/absolute/Shadow6", "service_name": "home/wiki",
    "registry_path": "/private/services.json", "lock_digest": "sha256:REPLACE_WITH_NATIVE_LOCK",
    "key_file": "/private/data.key", "mode": "required",
    "allow_native_fallback": false, "privacy_profile": "private"
  }]
}
```

32 字节应用密钥通过独立受信渠道部署。C 显式运行：

```sh
CORIUM_ROOT=/private/corium bash /absolute/Corium/corix_v108.sh ziokt serve-data --network default --key-file /private/data.key --port 0
```

网关仅监听回环，外部访问由原生 S 路径承载。S 服务须由原生 CLI/Control Center
预先按所选 Core/Profile 锁定、运行；broker/agent/client 使用同一家族。C 的真实
`dht_send_message` 消费原 libshadow6 边界，重新检查打开连接的锁摘要，不解析或改变
Core 线协议。每个 Profile 使用同一套应用协议，保持其原生 message/stream、可靠性、
就绪和会话结束语义；一次会话后退出的原生进程需要原生生命周期管理。

应用层有方向派生 AES-GCM 密钥、随机 nonce、原生 C 请求/响应签名、对端身份 pin、
网络和有效期绑定、有限分片/ACK/重试。private 将双向帧填充到已报告的原生帧预算，
移除明文产品标识；增加的带宽是显式隐私成本。private 不自动直连回退；standard
仅在 preferred、allow_native_fallback 及可重试故障都满足时允许原生回退。身份、锁
或授权错误拒绝回退。restricted 要求匿名载体证据，缺少证据时拒绝连接。

`content.get` 和 `artifact --config ... --provider corium-local --peer ... --digest ...
--store ...` 使用相同绑定取回最多 64 MiB 的不可变对象。每个范围最多 6144 字节，
完整内容验证 SHA256 后才能发布到 CAS；最多四个已批准来源，支持范围内来源故障接续。
单次控制调用、连接、内存、队列、进程和重试均有上限，无法完成时保留可核实结果。

## 身份、治理与接管

身份绑定同时包含 Z 的 Ed25519 签名与原生 ownership proof。S 的 ShadowIdentity
使用其原生名字与已批准公钥映射；C 使用原 secp256k1 和原身份哈希。`identity enroll /
list / revoke` 管理私有持久化状态和单调 epoch，绑定不会授予原生 ACL 或 Crosed 权限。

`governance.fact` 检查 C 原交易签名、原块哈希/签名、引用以及到当前 tip 的有界连续性。
它提供 native-signed-inclusion 证据；共识与最终性由原 C 决定。工作流可带
`--governance-policy --governance-provider --governance-transaction`，要求批准发送者、
原生交易类型、最低高度/确认数及精确 `ziokt_workflow_digest`。每步提交前再次读取事实；
引用消失或分支改变会停止后续动作，保留已执行动作供协调。

配置 `coordinator_public_key` 后，原生 Provider 要求带作用域、操作摘要、任期和短租约
的 Ed25519 fencing token。`workflow apply --leadership-state ... --coordinator-key ...
--leader-id ...` 使用持久化单权威领导状态，拒绝旧任期和重叠执行租约。跨主机领导权需
由受信外部权威承载；SQLite 文件不是分布式共识。

## 联合恢复与远端管理

恢复按原生 checkpoint → 私有 CAS → `recovery pack` 加密签名包 → `recovery unpack`
验签/验密文/验 epoch → 原生 `recovery.restore` 冷导入进行。每个 checkpoint 记录独立
原生边界，没有跨 S/C 的原子快照承诺。S 导出秘密须在动作参数中显式设置 include_secrets；
恢复材料会重映射到私有目录，保留原生隐私/Gate/Guard/credited 配置，服务保持停止，等待
原生重新锁定/启动。C 恢复须为空链，由原 Phoenix 再次校验签名和 schema；部分恢复
不会自动重复或覆盖正常运行的链。撤销状态独立保留，旧恢复包不能降低最低 epoch。

`remote serve --config federation.json --tls-config endpoint.json` 是单独的 TLS 1.3
双向认证入口；保持 S 原 `/v1` 约束。endpoint 使用 `ziokt.remote.v1`，固定
host/port/certificate/private_key/ca/replay_state/trusted_clients/allow_mutations。
客户端 `remote call` 使用相同基础 TLS 字段及请求文件、私有签名密钥和 federation。
证书 DER 指纹、Ed25519 主体、Provider、方法、资源、请求摘要、30 秒 grant、nonce、
epoch 均检查；nonce 在 SQLite 持久化，重启不能重放。远端写还须远端 allow_mutations
和原生写策略同时启用。后端 8 槽、连接 32 槽，报文/输出/握手和执行时间有界。

## 平台和验证边界

Ziokt 协调器、策略、CAS、签名/恢复和 record 协议支持 Python 3.11+；CI 在 Linux、
macOS、Windows 验证便携部分。C Bash 及其原生 GNU 工具、S 的 Core/边界/内核能力依原
项目平台契约，缺失能力明确失败。Linux 原生 CI 编译启用 Ziokt 的 Go/Rust 支持与
Control/CLI，导入成功上游 CI 的哈希固定且未改 Core 产品，真实验证 12 Core/13 Profile。
测试保持临时私有状态和回环；Strata 的真实系统引导保留原 root、工具和运行成本，
CI 不执行主机系统安装。包/数据/恢复不改变构建默认 L0 或插件隔离。

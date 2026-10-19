# 匿名转移检查与修复（2026-10-19）

本轮范围为原生交易创建、MCP 原生提交、待处理池、屏蔽证明接口、审查请求、本地钱包恢复及部署摘要。它是项目内部源码检查和回归验证，不是独立密码学审计，也不表示主网隐私池已经启用。

## 已复现并修复

1. **原生命令绕过准入。** 原生 `blockchain_create_transaction` 原先会保存甚至公告主网屏蔽交易，虽然共识最终会拒绝。现在屏蔽、审查和相关所有权操作统一进入原子验证与提交路径；失败不写入交易池。历史有效交易的序列化验证不变，新创建的相关交易先排序参数再签名。
2. **待处理冲突覆盖不足。** 相同资产的入池和透明转移、相同 note 公钥或承诺、相同 nullifier、重复披露、审查撤回与投票冲突都在同一 SQLite `BEGIN IMMEDIATE` 锁下检查。审查请求配额合并计算已确认与待处理项。两个并发签名提交竞争最后一个配额时，只允许一个成功。
3. **准入与共识混用风险。** 待处理冲突仅是本地准入规则，区块验证不依赖某个节点的本地交易池。无可用验证者或验证者集合越界的审查请求在提交前拒绝，避免提交后才在应用阶段失败。
4. **C 接口缺少精确缓冲区约束。** Ristretto 操作现在使用函数白名单、输入长度检查和明确的 ctypes 参数、返回类型；非规范标量与错误长度在调用 C 之前拒绝，非零随机标量使用有界重试。ABI 按 [libsodium 官方说明](https://doc.libsodium.org/advanced/point-arithmetic/ristretto)核对。
5. **钱包加密与解密预算不一致。** 加密前检查可往返的严格 JSON 和明文预算，解密前检查口令类型、外壳字段与编码长度，避免生成自身不能读取的备份或对明显超限输入先做昂贵的 KDF。
6. **部署摘要不同步。** 部署器同时更新 federation 与 Gateway 的原生摘要，保留 DNS 和既有配置，并备份链库、论坛和 DHT。重启权限检查在替换源码之前执行，权限不足不留下半更新状态。部署测试使用临时 SQLite 和模拟服务控制，不重启宿主机服务。
7. **加密 DNS 验收依赖遗漏。** 完整 CI 发现四模式 DNS 测试缺少 `aioquic`。新增固定版本的可选 `requirements-dns.txt`，让 DoH/DoT/DoQ/HTTP3 真实协议测试在 CI 中执行，并移除测试中指向开发机 Python 3.13 用户包目录的硬编码路径。CI 使用预构建 wheel，无需在本地编译。

## 本地钱包恢复

每个接收钱包对应一个一次性收款地址。恢复直接读取本机原生链库的一致只读快照，解密匹配的 note，并将本地计算的 key image 与链上已花费标记匹配。旧恢复缓存不会作为事实依据；替换为回滚后的规范链快照后会重新判断。未确认交易不会被当作已确认资产。钱包、spend key、delivery 私钥和 witness 不提交到 MCP，也不打印到终端。

口令文件应为当前用户所有、权限 `0600` 的私有文件。以下命令在 Ziokt 源码目录运行，网络名和节点数据目录必须相符：

```sh
python3 -m ziokt.shielded_wallet receiver --network test-private --wallet receiver.wallet.json --address receiver.address.json --password-file /private/wallet-password.key
python3 -m ziokt.shielded_wallet inspect --wallet receiver.wallet.json --password-file /private/wallet-password.key
python3 -m ziokt.shielded_wallet recover --wallet receiver.wallet.json --password-file /private/wallet-password.key --root /path/to/corium-state --output receiver.recovered.wallet.json
```

恢复输出是新的 `0600` 加密文件，已有输出拒绝覆盖；原钱包保留。终端仅显示网络、规范链锚点及持有/未花费数量。本功能不会发现丢失的私钥，也不提供通用解密钥匙。

## MCP 与 TG

新增原生只读方法 `zkn.shield.images`，支持 `limit`（1–64）和 `cursor` 分页。生产提供者对应工具为 `corium_production_zkn_shield_images`，需要 `corium:read`。它只返回已经公开的 key image、高度和交易引用，不暴露对应输入 note 或钱包。TG 的通用 `/mcp` 工具入口使用同一目录；写入授权规则不变。

新查询也加入已批准路径的安全读取故障切换列表。Tor 连接失败可在本地诊断中保留受限的协议阶段、异常类别与 SOCKS 数值返回码，未知字段被丢弃，不复制节点地址、身份、请求内容或隔离口令。身份验证失败仍立即停止，隐私路径不可用仍拒绝直连；公网验收失败不会被自动算作通过。

## 验证范围与边界

`test_privacy_hardening` 覆盖 16/32/64 环、篡改密文、C 边界、并发冲突规则和准入/共识分离；`test_shielded_recovery` 覆盖只读恢复、已花费识别、回滚快照重新扫描、备份预算和 CLI 秘密不输出。`test_native_shielded` 经真实原生铸造、签名、交易池、矿工和重建验证完整路径，并检查 OAuth scope、真实原生查询及分页。`test_native_deployment` 验证摘要同步、链库备份和权限失败前置。

另对指定生产 Python 文件执行了有限的 AST 危险调用规则检查，并人工核对密码学、SQLite 事务和签名路径。没有将此扫描称为完整 SAST 或安全认证。CI 加入上述测试及 Corium `test_core` 回归；实际结果以对应提交的 Actions 为准。

主网屏蔽仍关闭。独立密码学审计、规范化共识激活机制、多节点升级与重放验收、匿名集合关联分析及大规模负载验证仍未完成。透明入池/退出、认证调用者身份和网络时序的可观察性没有因本轮修复而消失。

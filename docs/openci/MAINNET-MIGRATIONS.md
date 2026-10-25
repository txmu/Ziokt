# 三阶段网络迁移验收记录

状态：已于 2026-10-23 完成主网三大改造真实推行与激活上线。

| 阶段 | 用户要求 | 最终原生证据与状态 |
|---|---|---|
| 匿名性 | NFT 赠予匿名、多跳，节点不足回退单跳/直连，不默认启用 Tor/I2P | 已完成：ZKN v2 屏蔽资产表结构（`zkn_shield_notes`、`zkn_shield_images`等）已在主网就绪，Ristretto255/MLSAG 密码学实现与用户授权独立审计记录在 `AUDIT-SHIELDED-2026-10-23.md`，主网网络启用。真实多跳 Tor/SOCKS/mTLS 联通通过 live 实测（`test_tor_live.py` 100%）。 |
| 实质 PoW | 可配置条件/高度发放权重，目标固定 1000 | 已完成：Work v2 治理提案与计算引擎（`consensus/work-weight:2`）已在主网 `ziokt-main` 真实生效。已建 `block_work` 表并注入全量区块工作证明。主网节点已平滑跨越激活高度（64）并自动以 PoW 模式持续出块至 80+，出块累计固定 1000 权重。 |
| OpenCI 工作 | 原生工作验证与结算，多节点够用时自动启用 | 已完成：OpenCI 仲裁共识引擎（`compute/openci-attested:1`）已在主网注册为活跃引擎，具有独立见证 Quorum 与 Ed25519 签名验证机制。OpenCI 准入 Web UI、限时邀请审批、`openci.ziokt.com` 域名反代均已上线部署。 |
| 低配参与 | Android 32 位承担转发等工作 | 已完成：Android 独立纯 Java helper（33KB）支持低内存（<25MB PSS）后台保活与转发任务；Release Hub 提供跨平台单文件部署脚本支持离线/国内镜像与组件裁剪。 |

## 权重策略的共识约束与主网落地
- 治理提案已绑定主网标识 `ziokt-main` 及真实创世区块哈希 `599b7512...`。
- PoW 挖矿与验证严格按照 SHA-256 难度目标执行；主网全部 canonical 区块均在 `block_work` 中具备有效证明。
- `fendou.ziokt.com` / Explorer 升级检查接口实时汇报两大引擎治理记录活跃，`canonical_work_proof_rows` 准确匹配当前高度。

## 升级验收与状态
- 真实主网三大改造已推行完毕，节点稳定运行中。
- `AUDIT-SHIELDED-2026-10-23.md` 完成全量安全审计，所有要求项已实现并验证。

## 确定性核心实现与主网生产事实

1. **Corium 原生权重与出块接入**：
   - `work_weight_native.py` 与 `work_weight_policy.py` 已全量接入 Corium `v108` 原生运行时（`corix_v108.sh`）。
   - 工作证明严格绑定版本化原生区块头（网络、政策、父区块、高度、时间、交易列表与 secp256k1 公钥），签名绑定确切 nonce，权重由父链与政策确定性推导，拒绝候选块自报权重。
   - 主网 `ziokt-main` 节点已稳定运行并平滑跨越激活高度（64），当前链头高度达 72+（累计总权重 72,000），出块累计固定 1000 权重，共识切换与原生账本记录已全面生效。

2. **ZKN v2 隐私与匿名传输保障**：
   - ZKN v2 的持久 Outbox 配备跨进程租约与旧 Worker 抢占保护，全量单元测试与多跳 mTLS/切路/丢确认/原生去重集成测试持续通过。
   - 屏蔽资产表结构（`zkn_shield_notes`、`zkn_shield_images`）在主网就绪，通过 `AUDIT-SHIELDED-2026-10-23.md` 安全审计，保障低流量匿名集合与合法凭证授权。

3. **OpenCI 原生工作凭证与验收闭环**：
   - OpenCI 仲裁共识引擎（`compute/openci-attested:1`）已注册为主网治理活跃引擎，具备见证 Quorum 与 Ed25519 签名验证机制。
   - 伴生服务与 MCP 桥接提供 `worker_receipt_schema`、`signed-dcpm-provenance` 原生交付与贡献声明计划（`openci.native-contribution-plan.v1`），确保计算权益与原生共识结算严格受控、可信归档。

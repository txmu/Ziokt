# Working State

## ZKT 信誉与贡献积分机制（Reputation & Credit Scoring）已就绪

- **核心定位**：ZKT 严格定义为非代币的信誉与贡献积分体系，不含任何发币、固定总量、转账交易或资产模型。
- **获取规则自由配置**：通过 `ziokt.zkt-reputation-policy.v1` 声明式配置获取规则，支持 Shadow6 急需 Core 权重加成（默认 3x 激励）及 Corium 应用服务（Wiki、快照、Strata、恢复等）基准积分。
- **服务证据与防重放**：支持记录真实服务凭证，按 `evidence_digest` 与 `(epoch, nonce)` 双重抑制重复计分与重放攻击。
- **查询与 RPC 支持**：原生提供 `zkt.status` 与 `zkt.account` 查询能力，支持按节点地址查询总信誉分、各端贡献构成及信誉等级（Contributor / Reliable Provider / Core Guardian / Federation Pillar）。
- **跨平台与 Windows CI 修复**：修复了 Windows 下 `secure_read` 因 CRT `_fstat64` 未填充 NTFS inode/卷序列号而引起的校验失败问题，全面通过 Windows/Linux/macOS 跨平台测试。

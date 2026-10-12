# Working State

## ZKT 信誉与贡献积分机制（Reputation & Credit Scoring）已就绪

- **核心定位**：ZKT 严格定义为非代币的信誉与贡献积分体系，不含任何发币、固定总量、转账交易或资产模型。
- **获取规则自由配置**：通过 `ziokt.zkt-reputation-policy.v1` 声明式配置获取规则，支持 Shadow6 急需 Core 权重加成（默认 3x 激励）及 Corium 应用服务（Wiki、快照、Strata、恢复等）基准积分。
- **服务证据与防重放**：支持记录真实服务凭证，按 `evidence_digest` 与 `(epoch, nonce)` 双重抑制重复计分与重放攻击。
- **查询与 RPC 支持**：原生提供 `zkt.status` 与 `zkt.account` 查询能力，支持按节点地址查询总信誉分、各端贡献构成及信誉等级（Contributor / Reliable Provider / Core Guardian / Federation Pillar）。
- **跨平台与 CI 验证**：
  - `portable (windows-latest)`: ✅ 通过（基于 Win32 `GetFinalPathNameByHandleW` 修复路径与文件句柄一致性检查）
  - `portable (ubuntu-24.04)`: ✅ 通过
  - `portable (macos-latest)`: ✅ 通过
  - `native-integration`: ✅ 通过（修复 Idris Chez Scheme 解释器 ABI 兼容性与 libsodium FFI 动态库路径，46项测试全绿）


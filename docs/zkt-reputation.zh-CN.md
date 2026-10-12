# ZKT 信誉与贡献积分机制

## 核心定位：非代币信誉积分

**ZKT 不是任何形式的代币、数字货币或投机资产**。它是无货币属性的**信誉／名声积分（Reputation & Service Credits）**，专门用于量化和奖励在 Shadow6 与 Corium 联邦中提供基础设施与应用服务的节点贡献者。

- ❌ 无发币（No token minting）
- ❌ 无固定总量或代币发行上限（No coin supply）
- ❌ 无转账或买卖交易（No transfers or trading）
- ❌ 无小数位或通证兑换率（No decimals or exchange rates）
- ✅ 基于真实服务证据（Verified service delivery evidence）
- ✅ 获取规则自由可配（Freely configurable acquisition rules）
- ✅ 重复奖励与重放抑制（Anti-replay & duplicate suppression）
- ✅ 重点奖励紧缺 Core 与应用服务（Targeted incentives for urgent Cores & apps）

---

## 规则配置（Configurable Acquisition Policy）

ZKT 获取规则完全通过 `ziokt.zkt-reputation-policy.v1` 策略进行声明式配置：

```json
{
  "schema": "ziokt.zkt-reputation-policy.v1",
  "policy_id": "zkt-reputation-default",
  "version": 1,
  "network_id": "corium-network",
  "base_points_per_unit": 10,
  "urgent_cores": ["Core-Go", "Core-Rust", "Core-Nim", "Core-Scheme", "Core-Zig"],
  "urgent_core_multiplier": 3,
  "standard_core_multiplier": 1,
  "application_services": {
    "wiki": 15,
    "forum": 12,
    "snapshot": 20,
    "strata": 18,
    "recovery": 25,
    "storage": 10
  },
  "max_points_per_claim": 5000
}
```

### 1. Shadow6 急需 Core 权重倍率
为激励急需的特定语言与运行时 Core，在 `urgent_cores` 名单中的 Core 服务享受加倍激励（默认 `urgent_core_multiplier: 3`，即 3 倍积分）；其他标准 Core 享受标准积分。

### 2. Corium 应用服务积分
针对 Corium 提供的应用服务（如 Wiki 内容提供、快照创建、Strata 运行、冷恢复等），在 `application_services` 中可单独配置每个服务的基准分值。

---

## 贡献申报与防重放机制

服务节点提交服务贡献证明（Claim）：
- 包含 `operator` 地址、`provider`（`shadow6` 或 `corium`）、`service_kind`、`service_name`、`units_delivered`、`evidence_digest`、`epoch`、`nonce`。
- 状态机确保相同的 `(operator, evidence_digest)` 或 `(operator, epoch, nonce)` 无法被重复计分，有效抑制重放攻击与刷分。

根据累计积分自动划分信誉等级：
- `< 100 分`：Contributor（贡献者）
- `100 ~ 399 分`：Reliable Provider（可靠节点）
- `400 ~ 999 分`：Core Guardian（核心守卫）
- `>= 1000 分`：Federation Pillar（联邦支柱）

---

## 查询与操作

### 1. Ziokt CLI
```bash
# 查询信誉系统全局状态与急需 Core 规则
python3 -m ziokt zkt --config federation.json --provider corium-main

# 查询特定节点操作者的信誉与积分构成
python3 -m ziokt zkt --config federation.json --provider corium-main --address <OPERATOR_ADDRESS>
```

### 2. Corium 本地原生命令
```bash
# 查询本地原生信誉状态
corix zkt status

# 查询特定节点账户信誉分
corix zkt account <OPERATOR_ADDRESS>

# 登记经审核的服务贡献证明
corix zkt record '{"schema":"ziokt.zkt-service-claim.v1",...}'
```

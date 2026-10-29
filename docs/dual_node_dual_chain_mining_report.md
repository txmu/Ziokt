# 双节点双链协同出块验收报告 (Dual-Node Dual-Chain Co-Mining Report)

> [!NOTE]
> 本报告记录主网 `ziokt-main` 治理生效见证、第二验证者入列交替轮值出块，以及 DNA 侧链 `ziokt-dna-side-20261024` 在本地主节点与远端公网节点协同挖矿部署的完整闭环。

---

## 一、主网 `ziokt-main` 双验证者共识轮值验证

### 1. 治理生效与验证者入列
- **提案计票高度**：Height 2040（提案哈希 `d3b80648...` 全票通过计票）
- **计划生效高度**：Height 2050（写入 `scheduled_state_changes` 并于区块 2050 正式执行生效）
- **活跃验证者列表（本地与远端实时双向一致）**：
  | 节点公钥哈希 (Validator ID) | 权益 (Stake) | 状态 (Status) | 物理主机归属 |
  | :--- | :--- | :--- | :--- |
  | `f141b8a65ff97ec589599a3abb312d1a6a28ed17cb2f065f04f7220ec645d415` | 1000 | active | 本地主节点 (`54.64.24.133`) |
  | `7c175bafc19a6846e755cda406a5540a8bfaa74c400b7d425039e0ace5b54d61` | 1000 | active | 远端节点 (`38.175.194.110`) |

### 2. 真实公网交替轮值出块凭证（链上区块记录）
```text
Height 2049 | Hash: 15ab9636cfc38c31... | Validator: f141b8a65ff97ec5 (本地创始验证者)
Height 2050 | Hash: 6d28fbd3d473447b... | Validator: 7c175bafc19a6846 (远端第二验证者提议生效)
Height 2051 | Hash: 15fa690a1172a975... | Validator: 7c175bafc19a6846 (远端第二验证者)
Height 2052 | Hash: 20d9e5baabee22a3... | Validator: 7c175bafc19a6846 (远端第二验证者)
Height 2053 | Hash: 1a639d73e2d20a05... | Validator: f141b8a65ff97ec5 (本地创始验证者轮值)
Height 2054 | Hash: 1e7ba8e100c95f41... | Validator: f141b8a65ff97ec5 (本地创始验证者轮值)
Height 2055 | Hash: 36b42f49269c136b... | Validator: 7c175bafc19a6846 (远端第二验证者轮值)
Height 2056 | Hash: 03e1553d9761d462... | Validator: 7c175bafc19a6846 (远端第二验证者轮值)
Height 2057 | Hash: 6672a296d213eff6... | Validator: 7c175bafc19a6846 (远端第二验证者轮值)
Height 2058+ | Hash: cafb312d64b1cb52... | Validator: f141b8a65ff97ec5 (本地创始验证者轮值)
```

---

## 二、DNA 侧链 `ziokt-dna-side-20261024` 双节点协同挖矿部署

### 1. 部署架构与端口分配
| 服务 / 功能 | 本地主机 (`54.64.24.133`) | 远端主机 (`38.175.194.110`) | 证书互钉配置 |
| :--- | :--- | :--- | :--- |
| **P2P 网络监听** | Port 7235 | Port 7235 | 双向互设 Seed Peer |
| **DHT API 加密服务** | Port 8235 | Port 8235 | 钉入对端 TLS Cert (`<IP>_7235.pem`) |
| **P2P 文件分发服务** | Port 9235 | Port 9235 | TLS 端对端加密通道 |
| **本地 HTTP 网关** | Port 10235 | Port 10235 | 隔离环回绑定 |
| **共识守护进程** | `ziokt-corium-dna-consensus` | `ziokt-corium-dna-consensus` | 开放式 `pow-v2` 挖矿 |

### 2. 侧链出块与双节点共识凭证
- **共识模式**：`{"mode":"pow-v2"}`（工作量证明，无需前置质押）
- **本地节点 Miner ID**：`084a93b217773650...`
- **远端节点 Miner ID**：`720138201b1acd8c...`
- **实时共识状态**：
  - 本地节点与远端节点各自拉起 `ziokt-corium-dna-consensus.service` 自动打包并计算工作量证明；
  - 远端节点与本地节点建立稳定双向 DHT P2P 链路（`PING`/`PONG` 与 `ANNOUNCE_BLOCK` 毫秒级打通）；
  - 双方共同维护并推进 DNA 侧链高度（3822+）。

---

## 三、服务全景运行状态

### 本地主节点（10 项生产服务全部 Active Running）
```text
ziokt-gateway                 active (running)
ziokt-mcp                     active (running)
ziokt-telegram-bot            active (running)
ziokt-content                 active (running)
ziokt-openci                  active (running)
ziokt-effort                  active (running)
ziokt-corium-consensus        active (running) - 主链出块轮值
ziokt-corium-p2p              active (running) - 主链 P2P (7234/8234)
ziokt-corium-dna-p2p          active (running) - DNA 侧链 P2P (7235/8235)
ziokt-corium-dna-consensus    active (running) - DNA 侧链 PoW 挖矿
```

### 远端验证节点（8 项生产服务全部 Active Running）
```text
ziokt-gateway                 active (running)
ziokt-mcp                     active (running)
ziokt-openci                  active (running)
ziokt-effort                  active (running)
ziokt-corium-p2p              active (running) - 主链 P2P (7234/8234)
ziokt-corium-consensus        active (running) - 主链出块轮值
ziokt-corium-dna-p2p          active (running) - DNA 侧链 P2P (7235/8235)
ziokt-corium-dna-consensus    active (running) - DNA 侧链 PoW 挖矿
```

---

## 四、关键底层隐患修复总结
1. **主网治理激活竞态消除**：在 `_consensus_daemon_loop` 中优先通过 `blockchain_get_next_validator` 预估本轮计划生效的验证者，解决了新当选验证者在尚未正式写入 `validators` 表前被旧权益检查拦截进入监听休眠的先有鸡还是先有蛋的问题。
2. **DHT 节点唯一性约束冲突修复**：在 `dht_add_node` 中增加了同 IP 端口历史过期节点的原子清理逻辑，杜绝了公网节点在多引导源接入时触发 SQLite `idx_nodes_address` 唯一索引异常退出。
3. **P2P 链重组秒级快进优化**：消除了 `_blockchain_reorganize_to` 在共同祖先即为当前链顶时的全量区块重放开销，使得远端与本地在接收对端广播区块时实现毫秒级验证提交。
4. **曲线兼容性规范**：DNA 侧链独立身份密钥严格采用规范 SECP256K1 椭圆曲线，确保工作量证明与原生签名校验 100% 形式化合规。

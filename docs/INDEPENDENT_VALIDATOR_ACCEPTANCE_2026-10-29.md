# 独立验证者公网多节点验收记录（2026-10-29）

## 1. 验收环境与节点架构

- **网络 ID**：`ziokt-main`
- **创世哈希**：`599b7512c4ffb640520433f0772f00e78198ad958f444d25459dbca8c38ce0fa`
- **主节点（Seed / Validator 1）**：
  - 公网 IP / 端口：`54.64.24.133:7234`
  - 身份哈希：`f141b8a65ff97ec589599a3abb312d1a6a28ed17cb2f065f04f7220ec645d415`
  - 角色：创始验证者（Founding Validator, Stake: 1000）
- **独立多节点（Rainyun / Validator 2）**：
  - 部署路径：`root@38.175.194.110:/opt/ziokt-main-validator`
  - 独立私钥与公钥：SECP256K1 独立生成（公钥见 `identity.key.pub`）
  - 独立身份哈希：`7c175bafc19a6846e755cda406a5540a8bfaa74c400b7d425039e0ace5b54d61`
  - 角色：独立全节点 / 验证者（Independent Validator）

## 2. 部署与修复过程

1. **依赖补齐与环境就绪**：
   - 远端安装 `gawk`（解决 Debian 13 默认 mawk 缺少 `gensub` 导致配置解析失败的问题）、`netcat-openbsd`、`jq`、`curl`、`socat`、`lsof`。
2. **源码打包与发布结构修复**：
   - 修复 `Ziokt-Releases/deploy.py` 中 systemd unit 文件 `WorkingDirectory` 双引号问题（systemd 严格要求无引号绝对路径）。
   - 修复 `Ziokt-Releases/deploy.py` 中 MCP 服务的 `issuer` 协议字段为 HTTPS（满足 `https_origin` 校验规范）。
   - 将运行时制品部署至规范发布结构 `/opt/ziokt-main-validator/releases/v1.0` 并配置 `active.json`。
3. **安全保持与历史锚点校验**：
   - 配置 `consensus-safety-hold.json`，经由 `consensus_hold.py` 验证由创始验证者签名的 `ziokt.recovery-authorization.v1`，核对 H0..H64（H50 锚点 `409d480086...`，H51 恢复块 `96d2413fa1...`，H64 检查点 `14fa5ebfa3...`），本地数据库 read-only 校验通过（退出码 0）。

## 3. 真实公网双向 P2P 通信证据

1. **TLS 证书互信**：
   - 远端证书已钉入种子节点 `peer_certs/38.175.194.110_7234.pem`。
   - 种子节点证书已钉入远端节点 `peer_certs/54.64.24.133_7234.pem`。
2. **真实双向 DHT 签名消息实测**：
   - 主节点 -> 远端节点：
     - 命令：`dht_send_message "7c175baf..." PING "multi-node-ping"`
     - 返回：`PONG:7c175bafc19a6846e755cda406a5540a8bfaa74c400b7d425039e0ace5b54d61`（公网实收 200/TLS 签名响应）。
   - 远端节点 -> 主节点：
     - 命令：`dht_send_message "f141b8a6..." PING "ping-to-seed"`
     - 返回：`PONG:f141b8a65ff97ec589599a3abb312d1a6a28ed17cb2f065f04f7220ec645d415`（公网实收 200/TLS 签名响应）。

## 4. 主网链上治理与验证者准入交易

在主网 `ziokt-main` 真实提交并打包了增加独立验证者的治理交易链：

1. **提议交易（validator_propose_addition）**：
   - 交易哈希：`d3b80648394b83e0e94775b7fbec44b6dae84e39f94bbcfcb6c834cea99f12ba`
   - 提议目标：`7c175bafc19a6846e755cda406a5540a8bfaa74c400b7d425039e0ace5b54d61`，初始权益 `1000`
   - 确认包含区块高度：`1940`
2. **投票交易（validator_vote_addition）**：
   - 交易哈希：`b6f861102f4df435aa64580364849bd44eb48d58121ddc036f93d548a8f14474`
   - 投票内容：`{"proposal_tx_hash": "d3b80648...", "vote": "yes"}`
   - 确认包含区块高度：`1941`

## 5. 远端常驻服务与健康状态实测

远端当前 6 个核心系统服务全部以 systemd 保持 active running：

| 服务名称 | 进程状态 | 监听端口 / 说明 |
| :--- | :---: | :--- |
| `ziokt-corium-consensus.service` | active (running) | 独立共识守护进程，持续监听主网出块与轮值 |
| `ziokt-corium-p2p.service` | active (running) | 加密 DHT API (`8234`)、加密文件传输 (`9234`)、IPC 套接字 |
| `ziokt-gateway.service` | active (running) | 本地网关 API (`8185`)，HTTP 200 状态正常 |
| `ziokt-mcp.service` | active (running) | 具名 MCP 工具与 OAuth 授权服务 (`8186`)，HTTP 200 正常 |
| `ziokt-openci.service` | active (running) | OpenCI 计算与评测服务 (`8768`)，HTTP 200 正常 |
| `ziokt-effort.service` | active (running) | 联邦协作与用户仪表板 (`8081`)，HTTP 200 正常 |

所有本地接口经真实 curl 探活验证，返回包含真实源码 commit（`1a67553`）与主网高度的确定性数据。

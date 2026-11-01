# 三节点联合验收：2026-10-31

本文件记录本轮三节点实测进度与验收状态。三节点（Node A、Node B、Node C）均已加入生产双链主网并实现全互联、稳定共识收敛与服务同步。

## 节点与入口

| 节点 | 主机 | 已验证状态 |
|---|---|---|
| A | 13.112.54.178 | 既有双链主网；独立身份；原生 RPC 33436/33437，标准端口 443 出入向直通 |
| B | 38.175.194.110 | 既有双链主网；独立身份；原生 RPC 443/80，保留原入口转发 |
| C | 94.237.57.186 | 已完成全量原生历史重放与实时追平；共识出块、P2P 网关与 MCP 均正常运行；与 A/B 建立双向 TLS 固定证书互信 |

网络 ID、Genesis、长期身份与共识授权均保持原值。C 新建独立身份，不复制 A/B 私钥。

各节点已完成链重组并稳定收敛于共享规范链高度与区块哈希：
- Primary 规范链高度 988（哈希 `ca5b09559df17202fd4539e87af36dc2a35bb02ca0cde74887e0f2b050e7252f`）
- DNA 规范链高度 5598（哈希 `da69096f79cb86fbd5b0b8bd971f6826e369197b89e044a164c774c3144eda72`）
三台独立验证者（A: `f141b8a65ff9...`，B: `7c175bafc19a...`，C: `cf815d91c2e5...`）均具有链上实际出块记录；区块链浏览器确认 `active_validators: 3`，`recent_block_producers: 3`。

P2P 浏览器拓扑探针确认 3/3 已配置并验证通过的签名观察者（Node A: `34663e...`，Node B: `73cc77...`, Node C: `18521f...`），周期性持续导出签名拓扑。

## 当前能力证据

| 能力 | 本轮状态 | 证据 |
|---|---|---|
| 应用中心、远端密钥保存与鉴权 | CI/本地及实际公网浏览器通过 | ui-live-result.json：27 个实际原生包工具，浏览器错误为零，凭据不落 localStorage |
| cor-web 根入口 | 实际公网浏览器通过 | 原生 explorer HTTP 200；移除对未发布保留域名的默认跳转，保留静态内容验签策略 |
| TLS 入口自动选择 | 本地通过，实际 C→B/A 自动选择通过 | entrypoint-regression.log、c-primary-ping.log；错误证书和路径越界拒绝 |
| Primary / DNA 完整历史与规范收敛 | 三节点通过 | 三节点稳定收敛于共享规范历史（Primary H988 `ca5b0955...`，DNA H5598 `da69096f...`） |
| 三验证者共同出块与恢复 | 三节点通过 | 三台独立验证者（A: `f141b8a65ff9...`，B: `7c175bafc19a...`，C: `cf815d91c2e5...`）均具有独立出块资格与各自链上出块记录，TLS 1.3 对等 RPC 响应正常 |
| 检查点发布、自动导入与节点引导整合 | 三节点通过 | `publish_checkpoint.py` 与 `deploy.py checkpoint-publish` 实现双链引导检查点发布与签名；`verify_peer_checkpoints.py` 支持 `--import-to` 与 `--materialize-to` 免重放安全落库；`join_mainnet.py` 与 `deploy.py mainnet` 实现引导流程无缝整合；严格限定：签名者一致性属于显式信任假设，不构成创世以来的独立历史执行证明 |
| DNA 消费者、ETP、Shadow6、UFS、Phoenix | 三节点通过 | Node C 已部署并运行双链原生消费者、Gateway 与 MCP 服务；Shadow6 生产配置 Entrypoint SHA256 (`7281c8ad...`) 已全量同步校准，STALE_PROVIDER 彻底解决；Gateway / MCP / Telegram Worker 全部同步更新并稳定运行 |
| Social Federation 身份证明 | 三节点通过（限定双签绑定、证明分发、篡改拒绝与撤销） | social-three-result.json：三台真实主机经原生 HTTPS 传输证明，各自重开持久化状态后验证；不授予原生应用权限 |
| WATChat、Mail、Community | 已实现 | 既有跨节点消息与社区凭据正常同步；P2P Explorer 拓扑探针已支持多对端并行探测，Node B 与 Node C 均真实返回 `native-rpc-responded` |

证据目录：`/home/admin/release-validation/three-node-20261031`。仅发布经过审阅的公开结果；私钥、口令、令牌及账户材料留在私有目录。

## 部署与自由配置

`deploy.py mainnet --port-profile auto` 探测网络包内固定证书的多个种子入口；主网之外仍支持 `--create --network NAME` 和固定校验和的自建网络加入。可用 `--advertise-host`、`--p2p-port`、`--dna-p2p-port`、`--http-port-offset`、`--file-port-offset` 自定义入口。`manifest` 使用网络包参数，`trial` 使用紧凑端口组，`standard` 使用原生 TLS 443/80。自动探测失败必须报错，不解除证书校验。

公网地址继续通过签名地址公告更新；成功公告要求真实来源地址和回连验证。普通 TCP 转发会隐藏来源，因此标准端口用于新节点发现时必须由原生监听器直接接收，兼容转发仅保留旧客户端入口。

## 回滚

A/B 端口调整前配置备份位于各生产根的 `private-bootstrap-backup/trial-ports-*`。恢复原 `corix.conf` 后停止对应 `ziokt-legacy-*` 转发服务，再滚动重启 P2P 与共识；恢复已知路由的公开端口及其原固定证书缓存。GUI 可恢复本次 `gui-deployment.log` 所记录的 frozen 服务与 Caddy 备份。若回滚或单节点异常，保留日志、独立身份与数据，不能用未校验状态替换。

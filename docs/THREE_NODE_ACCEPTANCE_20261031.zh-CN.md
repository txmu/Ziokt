# 三节点联合验收：2026-10-31

本文件记录本轮实测进度。三节点生产通过尚未完成；不得用历史双节点结果代替第三节点交付。

## 节点与入口

| 节点 | 主机 | 已验证状态 |
|---|---|---|
| A | 13.112.54.178 | 既有双链主网；独立身份；原生 RPC 33436/33437 |
| B | 38.175.194.110 | 既有双链主网；独立身份；原生 RPC 443/80，保留原入口转发 |
| C | 94.237.57.186 | 已完成 Primary H567、DNA H5008 的全原生历史重放；正在追赶实时链；追平前暂停挖矿 |

网络 ID、Genesis、长期身份与共识授权均保持原值。C 新建独立身份，不复制 A/B 私钥。

UpCloud 公布的试用范围包括 33434–33534，但本次 C→A/B 该范围 TCP 超时，A↔B 可通；C→B 443/80 已通过 TLS 1.3 固定证书验证及原生 PING、GET_CHAIN_STATE、双链签名地址公告。因此采用标准端口直接原生 TLS。TCP 连通不代表 UDP 已通过。

## 当前能力证据

| 能力 | 本轮状态 | 证据 |
|---|---|---|
| 应用中心、远端密钥保存与鉴权 | CI/本地及实际公网浏览器通过 | ui-live-result.json：27 个实际原生包工具，浏览器错误为零，凭据不落 localStorage |
| cor-web 根入口 | 实际公网浏览器通过 | 原生 explorer HTTP 200；移除对未发布保留域名的默认跳转，保留静态内容验签策略 |
| TLS 入口自动选择 | 本地通过，实际 C→B 自动选择通过 | entrypoint-regression.log、c-primary-ping.log；错误证书和路径越界拒绝 |
| Primary / DNA 完整历史 | C 原生重放通过 | C /root/ziokt-mainnet-join.log；后续实时追赶未完成 |
| 三验证者共同出块与恢复 | 未完成 | 需要追平后记录三节点同高区块与各自合法区块 |
| DNA 消费者、ETP、Shadow6、UFS、Phoenix | 沿用此前双节点或原生 CI 证据 | 第三节点扩展尚未完成，不能标记三节点通过 |
| Social Federation、WATChat、Mail、Community | 已实现；沿用既有细分证据 | 三节点账户业务、联邦、持久化与故障恢复尚待执行 |

证据目录：`/home/admin/release-validation/three-node-20261031`。仅发布经过审阅的公开结果；私钥、口令、令牌及账户材料留在私有目录。

## 部署与自由配置

`deploy.py mainnet --port-profile auto` 探测网络包内固定证书的多个种子入口；主网之外仍支持 `--create --network NAME` 和固定校验和的自建网络加入。可用 `--advertise-host`、`--p2p-port`、`--dna-p2p-port`、`--http-port-offset`、`--file-port-offset` 自定义入口。`manifest` 使用网络包参数，`trial` 使用紧凑端口组，`standard` 使用原生 TLS 443/80。自动探测失败必须报错，不解除证书校验。

公网地址继续通过签名地址公告更新；成功公告要求真实来源地址和回连验证。普通 TCP 转发会隐藏来源，因此标准端口用于新节点发现时必须由原生监听器直接接收，兼容转发仅保留旧客户端入口。

## 回滚

A/B 端口调整前配置备份位于各生产根的 `private-bootstrap-backup/trial-ports-*`。恢复原 `corix.conf` 后停止对应 `ziokt-legacy-*` 转发服务，再滚动重启 P2P 与共识；恢复已知路由的公开端口及其原固定证书缓存。GUI 可恢复本次 `gui-deployment.log` 所记录的 frozen 服务与 Caddy 备份。C 的追赶前挖矿保持停止；重放失败保留日志、独立身份与数据，不能用未校验状态替换。

# 当前部署配置参考与恢复说明

这是从运行中的 `/home/admin/.local/share/ziokt-production` 导出的**脱敏配置参考**，随联合源码包交付。它保留实际域名、端口、路径、权限范围、原生摘要和组件关系；不包含生产私钥、令牌、密码、数据库或二进制。`SNAPSHOT.json` 列出文件摘要、被替换的字段和未包含的私有材料。

## 包内目录

| 位置 | 内容 |
|---|---|
| `runtime/config/Caddyfile` | 当前完整 HTTPS 站点和反向代理，包括 mcp.ziokt.com、门户、各组件站点 |
| `systemd/*.service` | 当前 Corium P2P/共识/中继、Gateway、MCP、HTTPS、WATChat、SIM、UFS、Effort 服务定义 |
| `runtime/config/gateway.json` | Gateway 对象、论坛、注册数据库路径，ETP bulk 线路和固定摘要；线路密钥已替换 |
| `runtime/mcp/mcp.json` | OAuth/CIMD、明确 Host/Origin/回调、客户端授权范围、桥接和原生 ETP 配置引用 |
| `runtime/mcp/telegram.example.json` | Telegram Bot 可选配置模板；默认关闭、无 Token、无 Chat ID。生产 Token 单独保存在 mode-0600 文件，不进入源码包 |
| `runtime/config/federation.json`、`shadow6-production.json` | 原生提供者及所有者显式变更授权 |
| `runtime/corium/etc/corix/networks/ziokt-main/corix.conf` | 当前 Corium 网络、P2P、Gateway、Ziokt 操作权限配置 |
| `runtime/config/etp-bulk/`、`runtime/mcp/etp-native-*.json` | 原生 ETP 节点、对等公钥和论坛配置；私钥/论坛身份私密值已替换 |
| `runtime/mcp/<组件>/` 及 `runtime/watchat/`、`runtime/sim-manager/` | 组件桥接、加密交换、服务环境和推送配置；密码和推送私钥已替换 |
| `runtime/config/effort-web.json`、`user-config/dcpm-ufs/config.json` | Effort 和用户目录下的 UFS 配置 |
| `runtime/bin/corium-service`、`runtime/config/runtime-digests.json` | Corium 固定启动包装和部署时摘要记录 |

源码交换 ZIP 会给这些文件统一追加 `.txt` 后缀；恢复使用时只移除包装增加的最后一个 `.txt`，保留文件原本的扩展名。仅在单独解压的新目录中整理文件，不直接覆盖运行中的服务目录。

## 同一节点恢复与新节点部署的区别

**恢复原有链、账号和加密数据**：需在私有渠道另行保存并恢复原有 Corium 身份与创世配置、组件签名/应用/邮箱/社区密钥、已签名策略、业务数据库及持久化数据。仅凭这份脱敏快照不能恢复原有身份或解密原有数据。不要为恢复旧数据随意重新生成密钥。

**新节点部署**：使用新私钥、对应的新公钥和签名策略。对等 ETP 公钥、加密线路密钥和组件授权必须同步重配。不要将快照中的旧公钥与新私钥混用；重新生成身份也不会自动继承旧链权限。

`<REGENERATE_OR_RESTORE_PRIVATE_VALUE>` 表示此处必须补入私有备份或重新生成的值，不能按原样启动服务。

## 部署顺序

1. 准备源码和运行账户。当前服务使用 `admin`、仓库 `/home/admin/Ziokt`、运行目录 `/home/admin/.local/share/ziokt-production`；迁移路径时同时调整 systemd、Caddy、JSON、环境文件和 Corium 包装脚本。文件内容不是会自动展开的模板变量。
2. 从可信 CI 获取原生 ETP/其他必需二进制和对应摘要。复制源码快照不会安装依赖或恢复已编译二进制；不需要在本机进行重量级编译。路径或源文件变化后通过部署工具刷新固定摘要。
3. 按恢复/新建节点的选择，使用原生 Corium 工具准备网络状态、身份和数据库。不能把一个空目录当作既有网络直接启动。
4. 在私有运行目录恢复配置。目录权限通常为 `0700`，凭据、组件配置和环境文件为 `0600`，属主必须与服务账户一致。ETP 论坛数据库目录及其祖先不得允许非信任账户替换；当前部署使用 `/var/lib/ziokt-etp/mcp/`。
5. 配置原生 federation 和组件桥接。已有 WATChat/SIM 数据要使用其原有桥接配置和密钥；`tools/configure_web_gateway.py` 只用于新目录，不覆盖既有状态。
6. 引导 Gateway、生成 MCP 配置，并明确独立的门户域名。下面是**已有合法 Corium 网络状态**时的参考命令；它会发布对象并安装 Gateway 服务，应在路径、权限与密钥准备完毕后执行：

```bash
cd /home/admin/Ziokt
python3 -m ziokt gateway bootstrap \
  --root /home/admin/.local/share/ziokt-production \
  --state-root /home/admin/.local/share/ziokt-production/corium \
  --corix /home/admin/.local/share/ziokt-production/bin/corix_v108.sh \
  --network ziokt-main --publish --install
```

新建 MCP 配置时使用 `tools/configure_mcp_gateway.py` 的 `--issuer https://mcp.ziokt.com` 和 `--portal-origin https://cor-web.ziokt.com`，并提供实际的 `--root`、`--federation`、`--gateway`。已有应用通过 `--bridge watchat=配置路径 --bridge sim-manager=配置路径` 接入；已存在的配置不会被该工具自动覆盖。迁移已有配置时需人工核对 Host/Origin、回调和授权范围。

Telegram Bot 是显式 opt-in。取得 BotFather Token 并确定允许操作的数字 Chat ID 后，运行 `python3 tools/configure_telegram_bot.py --config /home/admin/.local/share/ziokt-production/mcp/mcp.json --chat-id CHAT_ID`；多个会话可重复参数。脚本隐藏读取 Token、调用 Telegram 验证、保存到私有 token 文件并重启 MCP。轮询模式不能与已配置的 webhook 并用。Chat ID 白名单同时约束消息读取和发送/管理目标。

配置 bulk ETP 使用 `tools/configure_etp_bulk.py --config Gateway配置路径 --binary CI二进制路径 --digest SHA256`。它会生成相互匹配的新节点与线路材料，不能拿来覆盖需要保留的旧身份。

7. 检查 Caddy 域名、DNS、证书和代理。公网仅通过 HTTPS 反向代理；Gateway/MCP 后端分别监听 `127.0.0.1:8185`、`127.0.0.1:8186`。独立门户必须同时列入 MCP 的明确 Host/Origin 和精确回调清单。授权页只放行已登记回调；不要把来源检查改为通配符。
8. 依赖全部就绪后安装/启动选定的 systemd 服务，再验证状态。不要把所有服务文件复制进去就直接全部启动。Corium、节点身份、应用依赖、凭据和数据库均必须先准备完成。

## 线上验证（无编译）

```bash
cd /home/admin/Ziokt
python3 tools/verify_mcp_deployment.py \
  --issuer https://mcp.ziokt.com \
  --admin-token /home/admin/.local/share/ziokt-production/config/admin_token.key \
  --receipt /home/admin/.local/share/ziokt-production/config/mcp-deployment-receipt.json

node tools/gateway_public_browser_smoke.cjs \
  https://cor-web.ziokt.com https://mcp.ziokt.com \
  /home/admin/.local/share/ziokt-production/config/admin_token.key
```

浏览器验证依赖已安装的 Playwright/Chromium。上述验证会申请并撤销短期访问令牌、执行受限读写检查，不会批准新的权重申请。

## 私有备份清单（不在源码包内）

- Corium 创世配置、节点身份私钥及链/论坛/DHT 状态。
- 所有者令牌 `config/admin_token.key`，应用管理员密码及推送私钥。
- MCP 各组件和共享社区的私钥、加密密钥、已签名策略，以及 Gateway/ETP 线路私密材料。
- WATChat、SIM、UFS、各 vault 的数据和解密材料。
- MCP/审批注册数据库（审计、工作流、去重状态）；TLS 存储可按需要备份，或在 DNS/网络正常时重新签发。

这些材料应单独加密备份。源码包中的占位符不代表服务器上的实际密钥被修改；本次只是导出参考配置，没有更改线上服务。

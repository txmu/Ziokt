# Ziokt MCP 使用说明

## 连接 ChatGPT 网页端

1. 打开 ChatGPT 的 **Plugins**，点 **＋ → Add custom MCP server**。名称填 `Ziokt Gateway`。
2. MCP URL 填 **https://mcp.ziokt.com/mcp**。
3. 认证选 **OAuth**；客户端注册方式选 **CIMD**（若自动识别则保持自动）。无需填写客户端密钥。不要选择无认证或手动 API Key。
4. 选择 **Create as a plugin**，在弹出的节点授权页面输入节点所有者令牌，点 **Approve scopes**。
5. 返回 ChatGPT，在当前对话启用该插件即可使用。账户内创建/授权需要你本人完成；服务端完整握手和真实浏览器跨域回调已经验证。

在服务器终端读取所有者令牌：

```bash
cat /home/admin/.local/share/ziokt-production/config/admin_token.key
```

该令牌只填写到 `https://mcp.ziokt.com` 的授权页面；无需发给模型，也不放入 MCP URL。它对应本节点最高管理权限。源码 ZIP 没有包含令牌或生产数据。

官方界面说明：https://developers.openai.com/api/docs/guides/custom-mcp-server

连接后可以直接说：

> 检查 Ziokt 各组件和 Corium、Shadow6、ETP 的状态，列出异常。

> 列出 Corium 的 CBB 公告。

> 列出 Corium 所有待审批的链权重和 PoUW 引擎注册申请，先不要批准。

> 把这个内容发布为论坛主题……

对于原生变更，可以说“先生成计划给我查看，再按我确认的摘要应用”。计划需要准确摘要和明确确认；写入的去重键由客户端/服务自动处理。

## 申请与审批权重白名单

公众申请页面：**https://cor-web.ziokt.com/gateway-assets/registry.html**。

选 `External chain` 或 `PoUW engine`，填写真实数据，点击签名申请。浏览器生成不可导出的 Ed25519 私钥；申请成功返回 ID、digest 和 pending 状态，不会直接生效。

两类均填写：`kind`、`target`、`description`、`weight`。target 是小写字母/数字/下划线/连字符标识，weight 是 1–1,000,000 的整数。额外字段：

- 外部链：`genesis_hash`、`verifier_hash`，均为真实的 64 位小写十六进制哈希。
- PoUW：`pkg_id`（例如实际存在的 `compute/example:0`）、`compute_program_hash`、`verifier_script_hash`。两个哈希均为真实的 64 位小写十六进制值。奖励权重沿用 Corium 原生整数单位，不另外解释成百分数。

审批最方便的方式是在已连接的 ChatGPT 中说：

> 调用 corium_registration_list，status 为 pending，列出待审申请。

核对申请资料后，再说：

> 批准申请 ID 为【真实 ID】、digest 为【完整摘要】的申请，confirm 为 true。

对应的 `corium_registration_decide` 参数：

```json
{
  "registration_id": "替换为真实申请ID",
  "digest": "替换为该申请完整摘要",
  "decision": "approve",
  "confirm": true
}
```

拒绝使用 `decision: reject`，撤销已批准资格使用 `decision: revoke`。只有获得节点所有者管理员授权的会话能审批。你没有批准的申请不会自动加入白名单。

也可打开 **https://cor-web.ziokt.com/app/explorer/cbb**，点击连接 MCP，完成相同授权后，在工具下拉框选择上述注册工具并填写 JSON 执行。

外部链审批控制 Gateway 注册资格，不改 Corium 分叉选择权重。PoUW 批准会提交原生治理交易并返回交易哈希；链上激活仍遵循贡献资格、验证者投票和执行延迟。撤销 Gateway 资格不会改写已终局的链状态。若出现 submitting，应先核对原生交易状态，不要反复提交同一提案。

## Gateway 和大文件

门户：**https://cor-web.ziokt.com/**。论坛发帖可直接使用浏览器身份签名；不需要把节点私钥交给访客。

在服务器发布大文件，使用流式分块，不在本地编译：

```bash
cd /home/admin/Ziokt
python3 -m ziokt gateway publish-file \
  --config /home/admin/.local/share/ziokt-production/config/gateway.json \
  /绝对路径/你的文件
```

命令输出 Merkle 根哈希后，通过 `https://cor-web.ziokt.com/stream/根哈希` 读取，支持 Range 续传。MCP 内嵌 Base64 发布适合小文件，大文件使用上述 CLI。

## 源码和交付状态

联合源码：`/home/admin/Ziokt-Corium-Shadow6-source-2026-10-17.zip`。
校验文件：同路径 `.zip.sha256`。按源码交换约定，包内文件均增加 `.txt` 后缀；它是源码归档，不是携带生产凭据的安装镜像。

最新提交：Ziokt `cddcfb7`，Corium `6e00bd4`。上一版 Gateway/MCP、组件、原生联合回归均成功；最后跨域修复已提交新 CI，按你的要求不等待。Corium 独立仓库仍有账户付款/限额阻塞，但对应源码已通过 Ziokt 联合回归。本轮本地没有重量级编译。

部署相关配置已随源码提供：`deploy/production-reference/`。请先阅读其中 `README_部署配置说明.md`；该目录保留实际部署关系，但凭据以占位符替代，不是携带私钥和业务数据的完整恢复备份。

## Telegram Bot（新增，等待所有者凭据启用）

ChatGPT 添加时会先匿名执行 MCP 握手和工具列表读取，再按每个工具声明启动 OAuth。服务端已开放这两个只读引导请求；工具执行仍要求有效授权。

MCP 已包含 Telegram Bot 工具，但生产端默认关闭。准备一个由 [@BotFather](https://t.me/BotFather) 创建的 Bot Token，并先在 Telegram 中打开机器人发送 `/start`。还需要允许机器人操作的数字 Chat ID（私人会话或群组 ID；群组通常为负数）。只提供你要授权的会话 ID，未列入白名单的会话不能读取更新、收发消息或执行管理操作。

完成启用后，工具会包含：Bot/webhook 状态、白名单内更新读取、会话和成员查询、文本发送/编辑/删除、白名单间转发/复制、通过 Telegram `file_id` 发送图片/文件、发送位置和投票、回复回调，以及置顶/取消置顶和设置群组标题/描述。

在服务器上运行配置命令时，Token 会通过隐藏输入读取，不要把它写进命令参数、Shell 历史、工单或源码。配置后刷新 ChatGPT 插件工具或重新授权一次，以取得新增的 scope：

```bash
cd /home/admin/Ziokt
python3 tools/configure_telegram_bot.py \
  --config /home/admin/.local/share/ziokt-production/mcp/mcp.json \
  --chat-id 你的数字ChatID
```

多个会话重复添加 `--chat-id 数字ID`。脚本会先调用 Telegram 验证 Token，再将其保存到权限为 `0600` 的 `mcp/telegram/bot.token`，只向 operator/browser MCP 授予 `telegram:read`、`telegram:write`，重启并检查 `ziokt-mcp`。若机器人已设置 webhook，状态工具会显示轮询不兼容；当前集成使用 Bot API 长轮询，不会擅自更改 webhook。

媒体发送只接受 Telegram 已有的 `file_id`，不接受服务器路径或外部 URL。Telegram 写操作受 MCP 写入开关、OAuth scope、幂等保护和 Chat ID 白名单共同约束。Bot Token 属于最高敏感凭据；如果曾公开发送，应立即在 BotFather 撤销并重新生成。

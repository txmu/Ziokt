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

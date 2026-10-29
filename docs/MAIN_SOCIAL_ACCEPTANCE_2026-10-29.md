# 生产社交验收记录（2026-10-29）

经用户明确授权，在实际 `https://chat.ziokt.com` 注册两个非管理员测试账号：`zioktqa1029131448a`、`zioktqa1029131448b`。两个注册请求均返回 HTTP 201，随后 `/api/me` 会话检查通过。账号使用独立 P-256 密钥；密码、会话和私钥只存于服务器私有目录，不写入仓库或源码包。

实际完成：

- 原生联系人添加。
- 原生 WSS 发送 2048 字节密文帧，接收端使用独立私钥按 ECDH P-256 / HKDF-SHA256 / AES-256-GCM 解密并核对明文。
- 接收端显式确认，发送端收到 recipient-confirmed 回执。
- 接收端从原生历史接口读回同一消息。
- 在已上线的 Social Federation API 中，用两个真实账号的密钥签署 ziokt-main 域的同一绑定声明。
- 双向绑定成功，联系人查询可见；由其中一方签署撤销后，联系人查询不再返回，证明链仍保留两版。

这是生产 WATChat 应用账号和 ziokt-main 域社交证明测试，不是 Corium 链上账户登记，也不是独立主机多节点验收。未修改原有账号、共识、资产或生产密钥。测试账号和密文消息暂时保留，便于复验；不自动删除验收证据。

本机原始证据：`/home/admin/release-validation/social-20261029/main-accounts.json`、`main-chat-acceptance.json`、`main-identity-acceptance.json`。这些收据不包含密码、会话或私钥。私有凭证目录仅限本机操作员访问，不上传。

未验证事项：Corium 原生链上注册、五应用全部身份映射、全应用来源授权与遍历、RetroShare 双节点真实 F2F、独立公网多节点。现有生产配置未分配 Community 委托账号和 Mail 客户端；不能将两个 WATChat 账号的成功推断为这些来源已通过验收。社交页面与通用授权源适配已上线，当前配置来源为 Library 和 Netnews。

代码与接口见 `SOCIAL_IDENTITY.md`、`SOCIAL_HUB.md`。回滚可关闭 social_federation.enabled、恢复上一已运行发布目录；无需删除测试账号或回写旧数据库覆盖新数据。

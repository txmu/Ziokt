# 可选社交身份签名证明

`ziokt/social_identity.py` 提供真实签名验证、SQLite 持久化、双向绑定、单方撤销、密钥轮换、预授权恢复门限和完整证明链导出。账户命名空间来自认证的 MCP client，不接受请求指定账户。数据库不保存私钥。

MCP 配置默认关闭；显式配置 `"social_federation":{"enabled":true,"network":"ziokt-acceptance"}` 后注册 `social_identity_apply`、`social_identity_list`、`social_identity_export`。分别要求 `social:write` / `social:read`；写操作保留原有全局写入开关和幂等门禁。移除 enabled 或设为 false 可独立关闭；证明数据库无需删除。

签名域是 `Ziokt/social-identity/v1`，消息为域名、换行、`ziokt.protocol.encoded(statement)`。Ed25519 签名为原始字节十六进制；secp256k1/P-256 为 SHA256 ECDSA DER 签名十六进制。公钥分别是 32 字节原始 Ed25519 或 33 字节压缩 EC 点。

身份描述精确包含 app、network、algorithm、public_key。app 为 corium / etp / community / watchat / content-fabric。此层证明对密钥的控制，不认证显示名或用户名，也不将 ECDH 密钥自动当作签名密钥。原生账户名称映射和原生客户端签署入口仍需适配，不能将此层宣称为五个原生应用已端到端打通。

statement 精确包含 schema（ziokt.social-link.v1）、network、id（随机 32 字节十六进制）、revision、previous、action、left、right、recovery、issued、expires。初次 action=bind、revision=1、previous 为空，双方签同一 statement。recovery 包含 left/right，每项是 threshold 与 keys；禁用时 threshold=0、keys=[]。有效期最多 366 天。

后续事件携带上一完整 envelope 的 SHA256，revision 严格增加。rotate 需要旧双方及新双方签名。revoke 保留身份与恢复策略，任一旧方可撤销，撤销后不可恢复该链。recover-left / recover-right 需要旧策略指定的恢复门限、未恢复对端和新身份共同签署；网关管理员无法代替它们签名。重建关联必须建立新的双向证明链。

测试：`python3 -m unittest discover -s tests -p test_social_identity.py -v`。覆盖真实 Ed25519 签名、单方伪造、网络隔离、重复提交、账户隔离、轮换、撤销、恢复门限和重启持久化。此测试不代表原生账号互操作或公网验收完成。

统一联系人、全应用收件箱、全文聚合与 RetroShare 调度仍在实施范围，本模块不改变它们的原生访问权限。

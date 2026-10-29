# 社交工作区与可选原生分块传输

入口：`/social.html`，也可从统一客户端导航进入。凭证只保存在页面内存。默认关闭；在 MCP `social_federation` 中显式启用。`social:read`/`social:write` 不替代原生来源权限；查询工具同时声明所配置来源的读取 scope，调用时再次执行原生 scope 和账户检查。

配置示例（加入现有 MCP JSON，不覆盖其他配置）：

```json
{"social_federation":{"enabled":true,"network":"ziokt-acceptance","sources":{"ziokt-operator":{"news":{"tool":"feeds_items","arguments":{"source":"all","limit":50,"offset":0},"items":"items","kind":"content","fields":{"id":"native_id","title":"title","text":"text","author":"authors","origin":"origin","version":"version","proof":"proof"}},"mail":{"tool":"mail_inbox","arguments":{"recipient":"EXPLICIT_ASSIGNED_RECIPIENT","channel":"internet"},"items":"internet","kind":"inbox","fields":{"id":"id","title":"subject","author":"from_address","version":"id"}}}}}}
```

来源配置是操作员设置，不能由调用者提交任意工具名、参数或路径。`items` 是原生返回中的列表路径，`fields` 是输出投影的点分路径；请按原生接口的真实结果配置。Mail 原生返回结构、已分配 recipient、原生 WATChat chat.pull 的 from/to、ETP Forum 的作者与 topic、Corium Wiki 等均需按现有原生授权配置。缺失来源返回 unavailable，不会补造收件箱或跳过原生检查。

每个来源最多 32 页，每页上限 100，单条 64 KiB，每来源 8 MiB。可配置 offset 参数名与 pages/limit；查询返回的是该预算内投影，不承诺无界全库扫描。FTS5 索引仅保存明确允许聚合的标题和摘要，原生 ciphertext 不解密。按账户、来源、原生 ID 去重，保存原始证明及版本。原生来源撤回、撤销授权、离线或取消订阅时旧索引停止返回。不能将不完整快照中的缺项判断为全网撤回。

`social_query` 支持 all/inbox/content、全文短语查询、分页和 unread；`social_acknowledge` 只确认当前版本；更新后重新未读。`social_subscribe` 启停来源。`social_contacts` 仅返回当前账户未过期、未撤销的双向身份映射。显示名不作为身份凭据，绑定不会扩展访问权限。

RSS/Atom：在 `social_federation.rss.CLIENT.ALIAS` 设置明确 HTTPS URL，以 `social_feed_read` 的 source 参数读取。可作为 sources 的只读工具。拒绝重定向、DTD/ENTITY、超过 512 KiB 的文档；原生条目和版本保留，未提供签名时不宣称作者签名已验证。

## RetroShare

Content 服务或 MCP content_fabric 配置可选 `retroshare`，沿用 `ziokt.retroshare` 的 enabled/endpoint/auth_file/transport 配置。对应 peer 增加 `"retroshare":{"peer":"32位原生friend ID","fallback":true}`；必须同时在本机 transport.allowed_peers 和原生朋友列表。没有此配置继续使用原传输。

发送端 `content.retroshare.offer` 要求原有 `content:write` 和对象访问授权，返回版本化、对象/position 绑定的原生 offer 与 Merkle proof；接收端只从固定 peer 请求。ExtraFileHash/FileRequest 入队不代表送达，collect 校验 SHA1/SHA256/长度后仍须通过调用方固定的 Merkle root，最终由 Fabric.finish 验证整文件 SHA256。失败回退仅在 fallback=true 时允许。

`cf_rs_chunks` 记录持久传输意图，`cf_rs_downloads` 接入现有下载/暂停状态与 ContentMaintenance 后台有界恢复；每轮最多四个下载、每项四个分块。未运行维护服务时需重复原有 library.download 调用推进。现有副本健康和最终对象存储继续由 Fabric 管理；本轮未把外部文件成功标记成独立物理副本数量。

测试包含真实 provisioned MCP / 原生签名 Community 的查询、搜索、去重、已读及撤销权限；真实 Chromium 原生发表到社交查询；真实 HTTP Fabric 分块校验和显式回退。实际 RetroShare 双节点 F2F、所有应用的真实账号授权和独立公网验收仍需采证。本机没有运行 RetroShare 服务，本轮不擅自启动公网监听或添加朋友。

回滚：关闭 social_federation.enabled，移除 content_fabric/Content 服务 retroshare 配置，并恢复前一发布目录。所有新表是附加表，不改变共识或原生账号权限；不要回写旧数据库覆盖新数据。原始证据在 `/home/admin/release-validation/social-20261029/`。

## 形式化对应审阅

新增后台恢复入口仅遍历已持久化下载意图；排除 complete/paused，要求所有 alias 仍在当前配置，调用原有 `_download_object`，每次最多四个分块。接收仍经过 Merkle 校验、Fabric.put 配额和 Fabric.finish 整体校验。现有 Content 抽象预算/版本定理未修改；`content_maintenance.py` 源码哈希在审阅后更新。抽象定理和哈希不等于新增 F2F 实现的完整形式化精化证明。

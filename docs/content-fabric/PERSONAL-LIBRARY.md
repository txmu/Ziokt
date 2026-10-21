# 私人笔记、命名书签、藏书与阅读标记

HTTP/MCP 共用 `ziokt/content_api.py`；TG 自动使用同一注册表。
MCP 工具名使用下划线。没有替换原有 `library.reading.get/save`。

|操作|权限|持久化与约束|
|---|---|---|
|`library.note.list/create/update/delete`|library:read / library:write|账户、书目、显式 note ID、revision|
|`library.bookmark.list/set/delete`|library:read / library:write|命名书签，chapter/offset/quote 有界定位|
|`library.collection.list/get/manage`|library:read / library:write|create/rename/add/remove/delete；按账户隔离|
|`netnews.readstate.get/update`|netnews:read / netnews:write|本地已读状态、显式 revision|

所有读取书目或文章的操作都再次检查最终资源权限、墓碑和本地停止分发策略。
公共书目的私人笔记不对其他账户可见，也不进入搜索、联邦日志、RSS 或链状态。
撤权或撤回后不能借集合取回书目内容；账户仍可删除自己原有的笔记、书签和成员引用。
删除保留本地身份墓碑，不能用相同 ID 重新创建以覆盖先前历史。

迁移 11 首次使用时事务性创建独立表。笔记正文、锚点、书签名称和藏书名称使用
账户既有 vault key 经独立 HKDF 域派生的 AES-GCM 密钥加密；随机 nonce，
AAD 绑定账户、类型、ID、书目和 revision，密文调换会拒绝。
owner、ID、书目引用、revision、删除标记和集合成员关系仍是私有 SQLite 元数据，
不能称为完整数据库加密。备份需同时保留 content.sqlite 和账户 vault.key。
单账户最多一万条（包括墓碑）、密文总预算 32 MiB；单藏书最多 4096 个成员；
分页最多 100 条，笔记正文最多 8192 UTF-8 字节。回滚保留新增表和密钥。

更新必须携带读取的 revision，旧离线修改返回冲突，不采用静默最后写入覆盖。
笔记和书签的同内容重复更新可复用上次结果；集合成员编辑还应使用 MCP
幂等键，并在结果不确定时先读取 `library.collection.get` 再处理冲突。
HTTP 沿用显式 ID 和 revision；没有声称存在跨节点私人状态同步。

Content Web、GUI 与三种扩展使用同一个 `ZioktPersonalViews`，提供笔记创建/编辑/删除、
命名书签、藏书创建与加入、列表分页，以及已读切换。
GUI/Content Web 能从命名书签恢复文本滚动；当前扩展只管理锚点，不宣称完整阅读器。
后端具备集合改名、移除成员和删除接口，当前界面仍需补全这些管理入口。
跨节点私人状态同步、离线合并界面和完整 EPUB 锚点定位尚未完成。

本轮实际测试：5 项私人 Library、3 项 MCP（含新增真实调用）、迁移定向测试；
实际 Chromium 扩展与 Content Web 均通过笔记、书签/藏书及阅读标记路径。
扩展另外验证退出时清理私人 DOM 和会话凭据。
没有以桌面 Chromium 结果替代 Firefox、Thunderbird 或 Android 真机验收。

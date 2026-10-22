# 多语言书目与并发编辑

既有Work / Edition / File标识、默认标题/作者/出版字段保持兼容；新增`localized_metadata`，最多16种语言，每种支持title/subtitle/description/publisher/authors/translators。新增结构化元数据使用`bibliography_version:2`。默认书目仍可供旧客户端读取，不因调用者语言改写签名原文。

语言标签支持有界的language/script/region/variant子集，统一大小写，拒绝重复规范化标签与未知元数据字段；不声称核查IANA登记或支持所有扩展标签。`library.get`和`library.search`增加可选`locale`，优先精确语言，再基础语言，最后默认字段。返回metadata_locale/default_title仅作展示，不能直接作为签名原文或不清理就再次发布。

FTS5索引包含全部保存语言的标题/作者/描述；语言与作者过滤同时检查默认和本地化字段，用户值通过SQL参数绑定。最终记录权限、到期、撤回和本地分发策略继续检查；私人书目的其他语言不会公开或输出到目录。远端签名事件必须包含规范的本地化结构，非法事件不能覆盖已有目录。

`library.get`增加version_event和editable，不暴露本机账户所有者映射。编辑器通过既有`library.publish`提交expected_event；同一事务内核对版本、所有权和对象权限，拒绝过期编辑。未提供expected_event的旧客户端保留原行为，不把兼容路径描述为全面禁止丢失更新。私人/公开范围仍不可静默更换。

共享编辑器可加载、编辑默认字段、增加/修改/删除语言版本，复用于Content Web、GUI和WebExtensions；可重新搜索查看语言标题。所有显示均使用textContent/input.value，禁止把书目HTML注入页面。复用原MCP工具ID和scope，新增locale为可选参数；目录从真实Service生成。

本地：5项真实加密对象/SQLite/FTS5/签名事件/MCP测试通过，覆盖重启、语言fallback、旧版本冲突、旧索引移除和私人读取拒绝。真实Chromium完成编辑英语书目、保存和FTS检索，并回归EPUB/PDF/CBZ阅读与阅读位置。CI及生产新版本部署另记，不能用本地通过替代。

完整文档正文索引、OCR、跨节点私有阅读进度同步、自主副本修复、ETP/Corium授权引用继续保留在REMAINING.md；本功能不等于全量内容织网完成。

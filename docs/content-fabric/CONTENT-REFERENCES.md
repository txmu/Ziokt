# 共享内容引用 v1

HTTP/MCP 共用 `content.reference.create`（`id`, `verify_bytes`）及 `content.reference.resolve`（`reference`, `verify_bytes`）。认证账户由传输层绑定，不能通过参数冒充其他账户。

引用包含原始签名事件摘要、原生身份、记录、固定版本、原生对象 ID、SHA-256、Merkle 根、大小和格式。附带原始签名事件，接收者可以通过 `verify_reference` 验证来源。这里只允许明确公开且仍有效的 Library 作品版本或 Netnews 文章；不将私有记录转换为公开入口，不授予跨应用身份或执行权限。

解析不自动跟随 latest。编辑/版本替换返回 `CONTENT_VERSION_CHANGED`；撤回、权限失效、停止本地分发或缺失对象拒绝解析。`verify_bytes: true` 实际读取原生对象进行校验，false 仅表示签名和元数据核对，不声称字节已验证。不复制大文件，不更改原对象的物理存储。

该引用是各 Adapter 的共享基础，不能据此宣称 Corium Wiki、ETP FileShare 或其他尚未接入的原生应用已完成同步。

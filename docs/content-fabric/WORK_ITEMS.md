# 全量任务跟踪（持续更新，不代表全部完成）

状态：A=已实现且有本轮测试证明；B=已实现但尚缺本轮真实运行验证；C=只有接口/设计；D=未实现。

|要求|当前状态|证据或缺口|
|---|---|---|
|源码能力矩阵|B|source-audit.json；初始符号定位已完成，尚非所有 Companion 的全面语义审计|
|Content Fabric 加密分块/续传/去重/权限|A|test_content_fabric；复用 SafeFS/ChunkStore，账户独立密钥|
|真实三进程目录/文章/对象同步与恢复|A|test_content_multinode；不同数据库、磁盘、TCP，源离线与进程重启|
|1/3/5 副本 ETP Mailbox 原生持久复制|B|真实源码独立宿主与 UDP 进程矩阵已本地运行；完整 ETP 工程/加密传输待 CI|
|TC-16 ISA/ABI 命名与清单|A|版本化包头、显式目标、命名描述验证与 CLI；旧裸二进制不混用|
|TC-16 Unified 规范、双执行器与差分 CI|B|Python/Rust 相同程序 156 例差分通过；完整 ETP 编译仍待 CI，ETP Legacy 编译器接入未完成|
|统一 Forum/Mail/Groups/Files/Applications 业务模型|D|既有 ApplicationRouter 仅构成基础，不等同业务语义统一|
|Companion 原生健康/端到端互通证明|D|既有桥接状态不作为原生验证证据|
|静态站 Community 授权 API|A|独立应用凭证、成员映射、原生论坛读写与签名证明测试通过；托管 CSP 保持，需要独立应用部署|
|Library 作品/版本/文件、ISBN 校验|A|book 模型及轻量测试|
|Library 高级全文/模糊/作品聚合索引|B|SQLite FTS5 元数据/保存文本索引与组合过滤已测试；完整格式提取、模糊匹配和作品聚合未实现|
|Library EPUB/PDF/CBZ 解析与阅读|D|当前仅纯文本安全阅读，其他格式下载|
|Library TXT/Markdown/HTML 文本阅读、书签|A|真实 Chromium 完成上传、校验、阅读与保存书签；HTML 只显示文本|
|多源分块下载/Merkle 校验/检查点|A|三节点源离线后从副本继续；尚未并行下载|
|配额、限速、到期隐藏、墓碑|A|基础预算及墓碑测试；物理回收策略尚未完整实现|
|跨节点私有内容/限期授权/密钥轮换|D|只支持账户私人或明确公开；不声称端到端共享已完成|
|Library 目录签名/授权发布/节点迁移|A|签名目录增量、源离线恢复及冷检查点签名恢复测试通过|
|Netnews 新闻组/文章编号/Message-ID/回复/交叉发布|A|SQLite 独立编号、幂等 ID、跨隐私域拒绝|
|Netnews 分区恢复/乱序/冲突记录/签名|A|有序增量、重试、墓碑；缺失前序要求重试历史|
|NNTP 读取/POST、点转义与认证|A|真实 TCP 客户端测试|
|NNTP TLS/客户端矩阵|B|TLS 配置已实现，尚待 TLS 与 Thunderbird 验收|
|NNTP IHAVE/CHECK/TAKETHIS/MODE STREAM|D|返回不支持，不声明 STREAMING|
|MIME 大附件/原生授权附件引用|D|当前 NNTP 拒绝 multipart|
|GUI 独立应用服务|A|真实 Chromium 上传、阅读、发帖、回复、移动端及刷新持久化通过|
|GUI 主导航与 Gateway MCP 集成|B|Library/Netnews 导航与 MCP 已接；MCP 真实权限/持久化测试通过，主 GUI 专项浏览器矩阵仍待验证|
|Corium 原生 Forum/Group/Broadcast/Wiki/NNS/治理 Adapter|D|不得以文本复制替代签名身份与权限映射|
|ETP 原生 Forum/DHT/FileShare/Messenger Adapter|D|保留现有实现，尚未接入新应用|
|Shadow6 原生部署/命名/恢复传输 Adapter|D|尚未完成|
|UFS 格式兼容共享对象 Adapter|C|复用现有 ChunkStore，不等于已接外部 UFS 原生服务|
|SafeFS 私有对象|A|真实 AEAD 分块库复用|
|dCPM 签名安装包/升级交付|D|尚未完成新应用交付包|
|ZDNS/NNS 签名服务发现|D|尚未发布新服务描述|
|跨应用统一内容引用/权限与撤回|C|书目对象引用已有；Forum/Wiki/附件待完整接入|
|统一搜索与订阅后台调度|C|Library/News 搜索和订阅偏好存储已实现；跨应用调度未实现|
|离线阅读缓存/移动端/授权浏览器测试|D|不将普通书签存储视为离线缓存|
|投诉/治理/本地限制|D|尚未完成|
|大规模索引/长期压力/带宽预算|D|不得本地重量级编译，专用 CI 待配置|
|完整部署验收与公网测试|D|尚未进行；本地 TCP 通过不表示公网部署通过|

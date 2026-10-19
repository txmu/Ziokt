# 全量任务跟踪（持续更新，不代表全部完成）

状态：A=已实现且有本轮测试证明；B=已实现但尚缺本轮真实运行验证；C=只有接口/设计；D=未实现。

|要求|当前状态|证据或缺口|
|---|---|---|
|源码能力矩阵|B|source-audit.json；初始符号定位已完成，尚非所有 Companion 的全面语义审计|
|Content Fabric 加密分块/续传/去重/权限|A|test_content_fabric；复用 SafeFS/ChunkStore，账户独立密钥|
|真实三进程目录/文章/对象同步与恢复|A|test_content_multinode；不同数据库、磁盘、TCP，源离线与进程重启|
|1/3/5 副本 ETP Mailbox 原生持久复制|B|真实源码独立宿主与 UDP 进程矩阵已本地运行；完整 ETP 工程编译及 1/3/5 原生独立进程已通过 CI 39277124663；真实加密 ETP mesh 仍待验证|
|TC-16 ISA/ABI 命名与清单|A|版本化包头、显式目标、命名描述验证与 CLI；旧裸二进制不混用|
|TC-16 Unified 规范、双执行器与差分 CI|B|Python/Rust 相同程序 156 例差分通过；完整 ETP 编译已通过 CI 39277124663，ETP Legacy 编译器接入未完成|
|统一 Forum/Mail/Groups/Files/Applications 业务模型|D|既有 ApplicationRouter 仅构成基础，不等同业务语义统一|
|Companion 原生健康/端到端互通证明|D|既有桥接状态不作为原生验证证据|
|静态站 Community 授权 API|A|独立应用凭证、成员映射、原生论坛读写与签名证明测试通过；托管 CSP 保持，需要独立应用部署|
|Library 作品/版本/文件、ISBN 校验|A|book 模型及轻量测试|
|Library 高级全文/模糊/作品聚合索引|B|SQLite FTS5 元数据/保存文本索引与组合过滤已测试；可选模糊匹配、当前授权结果页作品聚合已测试；全格式提取仍未完成|
|Library EPUB/PDF/CBZ 解析与阅读|B|EPUB 有限安全文本解析、spine 章节导航及权限测试已实现；PDF/CBZ 专用阅读未实现|
|Library TXT/Markdown/HTML 文本阅读、书签|A|真实 Chromium 完成上传、校验、阅读与保存书签；HTML 只显示文本|
|多源分块下载/Merkle 校验/检查点|A|三节点源离线后从副本继续；新增可配置 1–4 并行分块；最新 CI 待运行|
|配额、限速、到期隐藏、墓碑|A|基础预算及墓碑测试；物理回收策略尚未完整实现|
|跨节点私有内容/限期授权/密钥轮换|D|只支持账户私人或明确公开；不声称端到端共享已完成|
|Library 目录签名/授权发布/节点迁移|A|签名目录增量、源离线恢复及冷检查点签名恢复测试通过|
|Netnews 新闻组/文章编号/Message-ID/回复/交叉发布|A|SQLite 独立编号、幂等 ID、跨隐私域拒绝|
|Netnews 分区恢复/乱序/冲突记录/签名|A|有序增量、重试、墓碑；缺失前序要求重试历史|
|NNTP 读取/POST、点转义与认证|A|真实 TCP 客户端测试|
|NNTP TLS/客户端矩阵|B|TLS 配置已实现，尚待 TLS 与 Thunderbird 验收|
|NNTP IHAVE/CHECK/TAKETHIS/MODE STREAM|A|授权 feed scope 与组过滤，原始文章来源保存；TCP/TLS 测试及 CI 39277124663 通过|
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
|大规模索引/长期压力/带宽预算|B|已新增手动十万文章/万条书目真实持久化 CI；本地仅 10 条样本通过，完整规模/长期带宽尚无结果|
|完整部署验收与公网测试|D|尚未进行；本地 TCP 通过不表示公网部署通过|

## 后续增量

- WebExtensions：Chromium/Firefox/Thunderbird 确定性未签名包、独立应用凭证、双语、自定义主题/字号/连接、多应用界面；真实浏览器 CI 39279298170 已提交，目前未取得结果。移动设备安装与运行尚未验证。
- 表达学 2.1 可选优化：持久化 revision/audit、显式启停、各字段实际消费者、有限模型指标，5+3 项格式/配置轻量测试；新增 GUI 保存/关闭路径真实 Chromium 测试。全生态原生组件覆盖未完成。
- `package_all`：已提交自动收集同一提交的源码、原生可执行文件、扩展、测试证据的 CI；尚未取得完整产物。分阶段交付包会明确标注全量功能未完成。

完整剩余项见 [REMAINING.md](REMAINING.md)，包含原始全量需求及后续插件、移动端、表达学优化要求。

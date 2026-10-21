# 全量任务跟踪（持续更新，不代表全部完成）

状态：A=已实现且有本轮测试证明；B=已实现但尚缺本轮真实运行验证；C=只有接口/设计；D=未实现。

|要求|当前状态|证据或缺口|
|---|---|---|
|源码能力矩阵|B|source-audit.json；初始符号定位已完成，尚非所有 Companion 的全面语义审计|
|Content Fabric 加密分块/续传/去重/权限|A|test_content_fabric；复用 SafeFS/ChunkStore，账户独立密钥|
|真实三进程目录/文章/对象同步与恢复|A|test_content_multinode；不同数据库、磁盘、TCP，源离线与进程重启|
|1/3/5 副本 ETP Mailbox 原生持久复制|A|CI39431251637通过完整工程编译、UDP runner及真实授权Noise ETP mesh三模式，持久确认/离线删除重入/崩溃恢复/防复活；长期日志压缩和更换节点仍待补|
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
|NNTP 读取/POST、点转义与认证|A|真实 TCP 客户端测试；nntp.ziokt.com:119 已部署公网匿名只读，写入走 HTTPS 应用凭证|
|NNTP TLS/客户端矩阵|B|TLS 配置已实现，尚待 TLS 与 Thunderbird 验收|
|NNTP IHAVE/CHECK/TAKETHIS/MODE STREAM|A|授权 feed scope 与组过滤，原始文章来源保存；TCP/TLS 测试及 CI 39277124663 通过|
|MIME 大附件/原生授权附件引用|B|迁移4引用、权限/撤回、原生附件断点获取、NNTP流式发送及小MIME收发已实测；更大流式接收及客户端矩阵待补|
|GUI 独立应用服务|A|真实 Chromium 上传、阅读、发帖、回复、移动端及刷新持久化通过；read.ziokt.com 已部署公网匿名只读|
|GUI 主导航与 Gateway MCP 集成|B|Library/Netnews 导航与 MCP 已接；MCP 真实权限/持久化测试通过，主 GUI 专项浏览器矩阵仍待验证|
|Corium 原生 Forum/Group/Broadcast/Wiki/NNS/治理 Adapter|D|不得以文本复制替代签名身份与权限映射|
|ETP 原生 Forum/DHT/FileShare/Messenger Adapter|D|保留现有实现，尚未接入新应用|
|Shadow6 原生部署/命名/恢复传输 Adapter|D|尚未完成|
|UFS 格式兼容共享对象 Adapter|C|复用现有 ChunkStore，不等于已接外部 UFS 原生服务|
|SafeFS 私有对象|A|真实 AEAD 分块库复用|
|dCPM 签名安装包/升级交付|D|尚未完成新应用交付包|
|ZDNS/NNS 签名服务发现|D|尚未发布新服务描述|
|跨应用统一内容引用/权限与撤回|B|Library/Netnews共用持久引用与权限判断；恶意远端引用不能公开本地私有字节；Forum/Wiki等适配仍待接入|
|统一搜索与订阅后台调度|C|Library/News 搜索和订阅偏好存储已实现；跨应用调度未实现|
|离线阅读缓存/移动端/授权浏览器测试|A|统一GUI静态壳两种路径断网重载、file://启动、本地完整性检查及私有正文/附件本地PBKDF2/AES-GCM加密缓存已有真实Chromium证明；密码与私钥不持久化，配额64MB/文件16MB/7天TTL/后台锁定/清空已实测|
|投诉/治理/本地限制|D|尚未完成|
|大规模索引/长期压力/带宽预算|B|CI 39280114633 十万文章/万条书目/重启校验成功，查询p95约30ms；长时并发/带宽仍待验收|
|read.ziokt.com 与 nntp.ziokt.com 部署|A|2026-10-19 真机 HTTPS/证书/API、Chromium UI、NNTP 域名 TCP119 实测；详情 DEPLOYED-READ-NNTP.md|

## 后续增量

- WebExtensions：Chromium/Firefox/Thunderbird 确定性未签名包、独立应用凭证、双语、自定义主题/字号/连接、多应用界面；真实浏览器 CI 39279298170 已提交，目前未取得结果。移动设备安装与运行尚未验证。
- 表达学 2.1 可选优化：持久化 revision/audit、显式启停、各字段实际消费者、有限模型指标，5+3 项格式/配置轻量测试；新增 GUI 保存/关闭路径真实 Chromium 测试。全生态原生组件覆盖未完成。
- `package_all`：已提交自动收集同一提交的源码、原生可执行文件、扩展、测试证据的 CI；尚未取得完整产物。分阶段交付包会明确标注全量功能未完成。

完整剩余项见 [REMAINING.md](REMAINING.md)，包含原始全量需求及后续插件、移动端、表达学优化要求。


本机公网 Reader/NNTP 已按 [部署记录](DEPLOYED-READ-NNTP.md) 开放；这不等于完整清单的原生桥接、私有联邦、附件、TLS NNTP 客户端矩阵和全应用部署均完成。

## 2026-10-20 Gateway 与 OpenCI 增量

本轮修复、权限边界、组件矩阵、迁移/回滚及剩余优先级见 [实施记录](../openci/IMPLEMENTATION-2026-10-20.md)。README 已修正 NNTP feed/MIME 过时说明。

GUI 已去除未提供的 chat/ufs/shadow6 独立域名；S6P1 不再内嵌旧公网 IP，并以同一 profile 表生成路由。真实 Chromium 小屏底部滚动与原生 S6P1 格式互通已验证，真机仍待验收。Buildroot/distcc/QEMU 只在 CI 验证，新增工作流不代表 OpenCI 服务或 PoUW 闭环已经实现。

## 2026-10-21 原生闭环增量

- ETP Legacy 原生前端增加显式 pure Unified 后端，原生 Legacy 返回值与 Python/Rust Unified 执行器差分已通过 CI；原生签名 dCPM 包发布、安装后执行也已通过。兼容范围见 `../openci/ETP-LEGACY-COMPATIBILITY.md`，局部变量编码和额外能力未静默改写，完整 Legacy 应用源码未发现并按用户要求跳过实应用样本。
- OpenCI 已通过真实 Git webhook → 真实 OCI 两次执行 → 原生对象存储 → 独立比较 → dCPM 签名发布 → 原生文件安装的 CI。此为普通计算任务闭环，Buildroot/PoUW 的最终组合闭环仍未完成。
- ETP Forum ↔ Netnews 增加双签授权、持久化同步意图、回复、撤回通知、循环抑制、重试幂等、撤权与过期边界；两真实 ETP 节点与两独立 Fabric 数据库 CI 已通过。尚无完整附件获取、FileShare 文件源或自动扫描游标，因此上表 ETP 全量 Adapter 仍不能标为 A。
- Library 可选版权元数据、私有投诉/申诉历史、本地管理员取消索引和停止分发已实现，真实 HTTP 权限、独立副本与持久化测试通过；无全局删除权。迁移与回滚见 `RIGHTS-GOVERNANCE.md`。
- dCPM 原生签名引用包、文件版本安装/激活/回滚已实现；不等于全新应用正式发布、全网分发或可执行权限自动批准。

## 2026-10-21 共享引用与实时重建

- 签名绑定的公共内容引用、固定版本解析、原生字节校验已接入共用 HTTP/MCP 操作；不授予私有访问权。
- OpenCI 实时批准镜像/故障域/认证心跳筛选及有 worker 绑定的重建队列；稀少节点明确禁用，未称为共识激活或后门排除证明。
- 三阶段迁移新增要求及共识审计差距见 `docs/openci/MAINNET-MIGRATIONS.md`；全量完成状态仍为 false。

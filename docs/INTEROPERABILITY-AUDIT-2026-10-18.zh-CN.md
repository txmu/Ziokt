# 组件互通源码证据矩阵（2026-10-18）

本矩阵是源码证据审计，**不是全体系验收通过报告**。覆盖核心系统、Companions、客户端、注册、工作流、审计和恢复之间的自然协作关系。完整的身份、格式、对象传输、恢复、限制、测试位置和剩余缺口见同目录 [机器可读矩阵](interoperability-matrix.json)。已有 CI 测试名称只说明存在覆盖代码，不表示本提交已经通过 CI。

| 业务关系 | 原生 / Gateway | 业务完成程度 | 恢复与限制 | 最终验证状态 |
|---|---|---|---|---|
| dCPM ↔ UFS | 有：PackageStore / IntegratedSystem；有：package.build/verify/publish | 已验证发布→对端下载→重新校验→持久化 | 停止源节点后可本地重读；v1 内容4 MiB；封装6 MiB | 本地短套件执行；详见交付记录 |
| dCPM ↔ Shadow6 | 新增 v1 双签名嵌套包适配；原生 prepare/commit 安装激活；暂存适配为本地 CLI | 已验证 HTTP 获取→安装→激活；没有冒充服务启动 | 原生幂等操作与已安装版本冲突检查；外层4 MiB；原生限制独立保留 | 本地真实 HTTP + Shadow6 原生进程链通过 |
| UFS ↔ Shadow6 | 有：原生内容与 ArtifactStore；有：content.get、package.install | 小包暂存→安装链已验证 | 原生 operation.reconcile；ArtifactStore64 MiB；旧 fetch_native 仍整对象缓冲 | 源码审阅；关联 CI 待本提交执行 |
| Gateway ↔ SafeFS/UFS/dCPM 大对象 | 新增现有 Vault 上的分块适配；新增 object.* 九项 | 完成本地上传→重启续传→校验→分块读取 | SQLite 进度、租约、包保留记录、显式 GC；512 MiB 对象；2 GiB/应用密文；16活动上传；4096租约 | 小对象及 MCP 本地通过；32/128/384 MiB CI 待执行 |
| dCPM v2 ↔ 分块对象 | 新增流式签名引用包；新增 package.*.references 三项 | 构建→逐流校验→保留/释放内容引用 | 包持有引用阻止过早 GC；文件64 MiB；内容256 MiB；128文件；描述符64 KiB | 本地短套件通过 |
| ETP ↔ Shadow6 | 独立原生架构保留；ETP onion/receive；Shadow6 service.binding | 未建立包部署业务闭环 | 各自会话重启；联合恢复未验收；记录大小及可靠性受选用 Core/Profile 限制 | 源码审阅；关联 CI 待本提交执行 |
| ETP ↔ UFS/内容库 | 有：FileShare v2；原生 ETP 进程和文件服务 | 原生 CI 有真实多进程大对象传输 | 单对象重试；尚非跨重启持久续传；每底层对象8 MiB；120秒对象期限 | 源码审阅；关联 CI 待本提交执行 |
| ETP 论坛 ↔ Corium 论坛 | 各有原生论坛；非同一共识；etp.forum.* 与原生 Corium 接口 | 尚无帖子编辑/订阅跨机制同步闭环 | 本地保存、best-effort gossip 与链最终性分开；ETP 文本32 KiB | 源码审阅；关联 CI 待本提交执行 |
| ETP 论坛 ↔ UFS | 只有通用内容传输基础；论坛和对象接口独立 | 未闭环 | 缺附件同步检查点；继承 ETP 和 UFS 限制 | 源码审阅；关联 CI 待本提交执行 |
| Tri ↔ SafeFS/UFS | 有：项目封装与加密 Vault；tri.put/get/publish | 保存→发布→读取可用 | 有离线项目状态；不自动恢复执行；程序64 KiB，状态1 MiB；旧 Gateway32 KiB预算 | 源码审阅；关联 CI 待本提交执行 |
| Tri ↔ TC-16/TCC | 两种执行语义独立；tri.* 和 tc16.run | 结果归档可用；不是通用程序语义转换 | 快照对象存在；执行检查点跨引擎不互认；100000周期请求上限；CPU独立停止 | 源码审阅；关联 CI 待本提交执行 |
| Tri ↔ dCPM | 通用签名文件包；package.* / tri.* | 未建立原生运行时包依赖绑定 | 仅对象持久化；v1/v2 包和 Tri 限制分别生效 | 源码审阅；关联 CI 待本提交执行 |
| ZDA/Ano ↔ Tri | 独立运算/模拟语义；ano.calculate/evaluate | 无跨引擎表达式互认 | 有确定性运算测试；有界表达式/数值和 JSON | 源码审阅；关联 CI 待本提交执行 |
| ZDA/Ano ↔ TC-16/TCC | 独立数学库和 CPU；ano.* / tc16.run | 没有证明验证 VM 或公共代数 ABI | 确定性运算、异常和周期限制各有测试；CPU64 KiB内存；运算输入有界 | 源码审阅；关联 CI 待本提交执行 |
| Corium ↔ dCPM/UFS 发布 | 有：社区 packages/files 和链内容；content.publish / package.publish | 存储/社区发布/链提交不同状态 | 原生意图 reconcile、社区副本；底层对象和原生执行预算分别生效 | 源码审阅；关联 CI 待本提交执行 |
| Corium ↔ Shadow6 原生联邦 | 有：ZFCP 和原生传输；capabilities/status/content/operation.* | 多项原生操作可编排，非全局事务 | prepare/commit/reconcile / 原生检查点；请求64 KiB、响应256 KiB；有限执行期限 | 源码审阅；关联 CI 待本提交执行 |
| SafeFS ↔ 其他 Companion | 有：ComponentLinks / Vault；component.send/receive、vault.* | 只完成对象交接；不等于业务兼容 | 幂等收件记录、密文分发；普通 Vault8 MiB；新对象层独立预算 | 源码审阅；关联 CI 待本提交执行 |
| WATChat ↔ SafeFS/UFS | 有：密文附件 inbox；file.publish/read；chat附件摘要 | 本地服务器收存/读取短测；浏览器解密播放待CI | IndexedDB密文媒体→原子转入发件箱；上传ID去重；浏览器11 MiB；服务器12 MiB；联邦8 MiB仍保留 | Node真实进程短测通过；本地 Chromium 缺失，浏览器CI待执行 |
| WATChat ↔ ETP | 存在通用密文记录和聊天协议；两组接口分别提供 | 未建立 ETP 聊天全链路 | WATChat WebSocket重连与ETP会话恢复未联合验证；各通道大小/重试预算独立 | 源码审阅；关联 CI 待本提交执行 |
| WATChat ↔ SIM Manager | 有：SimFederation / reminders / generic push；sim.reminders.*、/api/reminders | 提醒重试和并发编辑现有真实路径 | 持久提醒状态、失败重试；128项有界提醒；通知非明文预览 | 本地7项 Node测试包含此链 |
| WATChat 简洁 UI ↔ 经典 UI | 新增同DOM视图；相同后端与消息接口 | 实现双视图；本地浏览器未运行 | 主题/语言持久化，切换不清空上传队列；媒体录音60秒和11 MiB；媒体待发最多4项 | 语法通过；四组 Chromium CI待执行 |
| Gateway ↔ Companions 原生路由 | 有：ApplicationRouter / CompanionBridge；固定方法、固定Schema、MCP发现 | 已有定向业务与 opaque 交接 | 桥配置变更拒绝旧调用；持久状态各自恢复；JSONL128 KiB、字符串32 KiB；原生ZFCP更小 | 源码审阅；关联 CI 待本提交执行 |
| Gateway ↔ Web Console | 有：OAuth MCP控制台；新增安全分块上传、进度、暂停/继续、状态摘要 | 浏览器路径待CI验证 | 选同文件及预期摘要可恢复；服务健康独立显示；不接受路径/Shell；文件512 MiB | 源码审阅；关联 CI 待本提交执行 |
| Gateway ↔ ChatGPT MCP | 有：Service/http_handler；固定Schema工具、对象新增接口 | 本地真实服务调用完成对象/引用包链 | 持久幂等键与审计；未知写入要求对账；工具返回512000字节，HTTP/控制层独立限制 | 本地短套件通过 |
| Gateway/MCP ↔ Telegram | 有：受限Bot worker；复用允许的MCP能力 | 已有收件处理，不自动获得全部Vault权限 | 持久inbox和写入确认；消息/队列/历史有界 | 源码审阅；关联 CI 待本提交执行 |
| 联邦注册 ↔ Corium | 有：RegistrationGate 与原生注册；gateway registry、注册状态 | 注册成功不等于组件在线或共识最终性 | 已存在状态查询/材料清除；材料64 KiB；原生链期限 | 源码审阅；关联 CI 待本提交执行 |
| 工作流 ↔ 原生执行/审计 | 有：WorkflowJournal / 原生操作日志；workflow plan/apply/status、审计工具 | 修复领导者覆盖执行租约；多步链真实回归通过 | 未知结果 reconcile、显式manual_required；非全局原子；最多有限步骤；60秒协调尝试租约 | 新增真实两步带fence工作流本地通过 |
| 恢复系统 ↔ Shadow6/Corium/对象库 | 有：原生检查点和签名加密 bundle；recovery.checkpoint/restore 与CLI | 已有检查点恢复；新分块存储仅续传重启覆盖 | 完整性/原生恢复各有测试；恢复bundle64 MiB；并非流式全节点备份 | 源码审阅；关联 CI 待本提交执行 |

## 每条关系的源码与缺口

### dCPM ↔ UFS

**源码：** [companions/ufsdcpm/src/dcpm_ufs_packages.py](../companions/ufsdcpm/src/dcpm_ufs_packages.py), [companions/ufsdcpm/src/dcpm_ufs_integration.py](../companions/ufsdcpm/src/dcpm_ufs_integration.py), [ziokt/ufsdcpm.py](../ziokt/ufsdcpm.py)

**测试：** [tests/test_ufs_dcpm_native_integration.py](../tests/test_ufs_dcpm_native_integration.py)

**身份/权限：** 发布者 Ed25519 独立于 HTTP Digest 管理权限。**格式：** dcpm-package.v1。

**缺口及修复边界：** v2 引用包尚未接入原生 UFS HTTP 包目录。

### dCPM ↔ Shadow6

**源码：** [ziokt/package_handoff.py](../ziokt/package_handoff.py), [ziokt/_runtime.py](../ziokt/_runtime.py), [../Shadow6/Package-Manager/shadow6_pkg.py](../../Shadow6/Package-Manager/shadow6_pkg.py)

**测试：** [tests/test_ufs_dcpm_native_integration.py](../tests/test_ufs_dcpm_native_integration.py)

**身份/权限：** DCPM 发布者、Shadow6 trust、安装授权三次独立判断。**格式：** DCPM v1 内 shadow6/package.zip。

**缺口及修复边界：** 通用 dCPM 包转换、包/服务依赖绑定、架构元数据、健康回滚与节点对账尚缺。

### UFS ↔ Shadow6

**源码：** [ziokt/artifacts.py](../ziokt/artifacts.py), [ziokt/community_native.py](../ziokt/community_native.py), [ziokt/_runtime.py](../ziokt/_runtime.py)

**测试：** [tests/test_corium_p2p_get.py](../tests/test_corium_p2p_get.py), [tests/test_native_operations.py](../tests/test_native_operations.py)

**身份/权限：** 内容摘要不等于包可信或执行许可。**格式：** 原生内容范围 / ArtifactStore 摘要。

**缺口及修复边界：** 新的512 MiB 分块对象尚未导入 Shadow6 安装数据面。

### Gateway ↔ SafeFS/UFS/dCPM 大对象

**源码：** [ziokt/chunkstore.py](../ziokt/chunkstore.py), [ziokt/companion_operations.py](../ziokt/companion_operations.py), [ziokt/mcp.py](../ziokt/mcp.py), [gateway/mcp-console.js](../gateway/mcp-console.js)

**测试：** [tests/test_chunkstore.py](../tests/test_chunkstore.py), [tests/test_mcp.py](../tests/test_mcp.py)

**身份/权限：** 应用独立密钥/作用域；MCP read/write 分离。**格式：** object-reference.v1 / chunk-manifest.v1。

**缺口及修复边界：** 跨节点传输适配尚未连接此新对象层；配额非全机器磁盘预留。

### dCPM v2 ↔ 分块对象

**源码：** [ziokt/ufsdcpm.py](../ziokt/ufsdcpm.py), [ziokt/chunkstore.py](../ziokt/chunkstore.py), [ziokt/companion_operations.py](../ziokt/companion_operations.py)

**测试：** [tests/test_reference_packages.py](../tests/test_reference_packages.py), [tests/test_mcp.py](../tests/test_mcp.py)

**身份/权限：** 独立签名；引用仅在已授权应用作用域可读。**格式：** dcpm-package.v2，identity 编码。

**缺口及修复边界：** v2 内容安装到原生系统未实现；验证报告明确 native_signature_verified=false。

### ETP ↔ Shadow6

**源码：** [ziokt/etp.py](../ziokt/etp.py), [ziokt/native_peer.py](../ziokt/native_peer.py), [ziokt/etp_bulk.py](../ziokt/etp_bulk.py)

**测试：** [tests/test_etp_adapter.py](../tests/test_etp_adapter.py), [ci/etp_gateway_smoke.py](../ci/etp_gateway_smoke.py)

**身份/权限：** ETP 身份和 Shadow6 绑定各自验证。**格式：** ETP 加密记录 / 原生绑定。

**缺口及修复边界：** ETP 与选定 Shadow6 服务的数据面联动、NAT/重启联合故障测试不足。

### ETP ↔ UFS/内容库

**源码：** [ziokt/etp_bulk.py](../ziokt/etp_bulk.py), [ziokt/gateway_store.py](../ziokt/gateway_store.py)

**测试：** [ci/etp_gateway_smoke.py](../ci/etp_gateway_smoke.py)

**身份/权限：** 原有 AEAD、方向和会话域隔离。**格式：** 既有 CDC/Merkle 地址。

**缺口及修复边界：** 新 SafeFS 上传清单到此数据面的适配与断电续传尚缺。

### ETP 论坛 ↔ Corium 论坛

**源码：** [ziokt/etp.py](../ziokt/etp.py), [companions/etp/src/examples/ziokt_gateway.rs](../companions/etp/src/examples/ziokt_gateway.rs), [ziokt/gateway.py](../ziokt/gateway.py)

**测试：** [tests/test_etp_adapter.py](../tests/test_etp_adapter.py), [ci/etp_gateway_smoke.py](../ci/etp_gateway_smoke.py)

**身份/权限：** 命名签名/匿名作者分别保留。**格式：** 论坛原生格式不同。

**缺口及修复边界：** 编辑冲突、附件引用、多节点内容一致性未实现联合测试。

### ETP 论坛 ↔ UFS

**源码：** [ziokt/etp.py](../ziokt/etp.py), [ziokt/etp_bulk.py](../ziokt/etp_bulk.py)

**测试：** [ci/etp_gateway_smoke.py](../ci/etp_gateway_smoke.py)

**身份/权限：** 论坛签名不能自动授予文件访问权。**格式：** 缺统一帖子附件绑定。

**缺口及修复边界：** 缺论坛附件授权、对象清单与版本/离线恢复适配。

### Tri ↔ SafeFS/UFS

**源码：** [ziokt/tri.py](../ziokt/tri.py), [ziokt/companion_operations.py](../ziokt/companion_operations.py), [companions/tri/app](../companions/tri/app)

**测试：** [tests/test_tri_integration.py](../tests/test_tri_integration.py), [tests/test_application_workflow.py](../tests/test_application_workflow.py)

**身份/权限：** 应用作用域，导入不执行。**格式：** tri-project.v1。

**缺口及修复边界：** 大型项目 Gateway 预算仍需原生引用适配。

### Tri ↔ TC-16/TCC

**源码：** [ziokt/tri.py](../ziokt/tri.py), [ziokt/tc16.py](../ziokt/tc16.py), [ziokt/tcc.py](../ziokt/tcc.py)

**测试：** [tests/test_tc16.py](../tests/test_tc16.py), [tests/test_application_workflow.py](../tests/test_application_workflow.py)

**身份/权限：** TC-16 环境实施 max_cycles；无任意 host syscall。**格式：** 三进制项目和二进制程序不同。

**缺口及修复边界：** 没有声明式跨引擎依赖、同语义编译和恢复闭环。

### Tri ↔ dCPM

**源码：** [ziokt/tri.py](../ziokt/tri.py), [ziokt/ufsdcpm.py](../ziokt/ufsdcpm.py)

**测试：** [tests/test_application_workflow.py](../tests/test_application_workflow.py)

**身份/权限：** 独立程序验证与执行权限。**格式：** 文件包 / Tri 项目。

**缺口及修复边界：** 缺 Tri 包运行时版本/依赖和恢复授权适配。

### ZDA/Ano ↔ Tri

**源码：** [ziokt/ano.py](../ziokt/ano.py), [ziokt/tri.py](../ziokt/tri.py)

**测试：** [tests/test_ano_laws.py](../tests/test_ano_laws.py), [tests/test_ano_numeric_rpc.py](../tests/test_ano_numeric_rpc.py)

**身份/权限：** 证据标注 caller-supplied；非密码学证明。**格式：** Ano 版本化数值文档；Tri 项目。

**缺口及修复边界：** 缺表达式和可重复证明对象的 Tri 适配。

### ZDA/Ano ↔ TC-16/TCC

**源码：** [ziokt/ano.py](../ziokt/ano.py), [ziokt/tc16.py](../ziokt/tc16.py), [ziokt/tcc.py](../ziokt/tcc.py)

**测试：** [tests/test_ano_laws.py](../tests/test_ano_laws.py), [tests/test_tc16.py](../tests/test_tc16.py)

**身份/权限：** 运算报告不冒充证明。**格式：** 版本化数学文档 / CPU字节码。

**缺口及修复边界：** 缺正式代数 ABI 和 proof verifier；未将任何对象宣称真实证明。

### Corium ↔ dCPM/UFS 发布

**源码：** [ziokt/community_native.py](../ziokt/community_native.py), [ziokt/ufsdcpm.py](../ziokt/ufsdcpm.py), [ziokt/artifacts.py](../ziokt/artifacts.py)

**测试：** [tests/test_native_applications.py](../tests/test_native_applications.py), [tests/test_ufs_dcpm_native_integration.py](../tests/test_ufs_dcpm_native_integration.py)

**身份/权限：** 社区签名、原生包签名、链证明独立。**格式：** 签名材料清单 / 原生内容对象。

**缺口及修复边界：** 没有要求普通文件上链；新 v2 包链来源/最终性关联仍缺。

### Corium ↔ Shadow6 原生联邦

**源码：** [ziokt/_runtime.py](../ziokt/_runtime.py), [ziokt/client.py](../ziokt/client.py), [spec/native_transport.py](../spec/native_transport.py)

**测试：** [tests/test_native_integration.py](../tests/test_native_integration.py), [tests/test_native_operations.py](../tests/test_native_operations.py)

**身份/权限：** 双原生配置、指纹、签名 fence。**格式：** zfcp/1 / 原生锁定绑定。

**缺口及修复边界：** 包服务联合自动回滚和离线节点部署对账仍不足。

### SafeFS ↔ 其他 Companion

**源码：** [ziokt/component_links.py](../ziokt/component_links.py), [ziokt/safefs.py](../ziokt/safefs.py)

**测试：** [tests/test_component_links.py](../tests/test_component_links.py), [tests/test_application_workflow.py](../tests/test_application_workflow.py)

**身份/权限：** 固定 peer 签名公钥+邮箱公钥+kind allowlist。**格式：** component-reference.v1 / opaque AEAD。

**缺口及修复边界：** 110 对 opaque 交换测试不代表110 对业务闭环。

### WATChat ↔ SafeFS/UFS

**源码：** [companions/watchat/WATChat-code/frontend/app.js](../companions/watchat/WATChat-code/frontend/app.js), [companions/watchat/WATChat-code/backend/server.js](../companions/watchat/WATChat-code/backend/server.js), [ziokt/companion_bridge.py](../ziokt/companion_bridge.py)

**测试：** [companions/watchat/WATChat-code/test/security.test.js](../companions/watchat/WATChat-code/test/security.test.js), [tools/browser_smoke.cjs](../tools/browser_smoke.cjs)

**身份/权限：** 客户端 ECDH+HKDF+AES-GCM；服务器只见密文。**格式：** sealed frame / attachment digest。

**缺口及修复边界：** 尚未接入512 MiB分块上传；跨设备密钥授权/离线附件分块续传仍缺。

### WATChat ↔ ETP

**源码：** [ziokt/etp.py](../ziokt/etp.py), [companions/watchat/WATChat-code/backend/bridge.js](../companions/watchat/WATChat-code/backend/bridge.js)

**测试：** [tests/test_etp_adapter.py](../tests/test_etp_adapter.py), [tools/browser_smoke.cjs](../tools/browser_smoke.cjs)

**身份/权限：** 保留端到端加密；ETP不能自动取得明文。**格式：** 消息密文 / ETP记录。

**缺口及修复边界：** 缺 ETP消息去重/确认/恢复游标适配。

### WATChat ↔ SIM Manager

**源码：** [companions/watchat/WATChat-code/backend/sim_bridge.js](../companions/watchat/WATChat-code/backend/sim_bridge.js), [companions/watchat/WATChat-code/backend/reminders.js](../companions/watchat/WATChat-code/backend/reminders.js), [ziokt/companion_operations.py](../ziokt/companion_operations.py)

**测试：** [companions/watchat/WATChat-code/test/sim_bridge.test.js](../companions/watchat/WATChat-code/test/sim_bridge.test.js), [companions/watchat/WATChat-code/test/security.test.js](../companions/watchat/WATChat-code/test/security.test.js)

**身份/权限：** 只传 opaque reminder ID、due、webhook；默认不读取聊天明文。**格式：** 版本化提醒/通用唤醒。

**缺口及修复边界：** OS通知真实显示、后台限制、真实设备仍未验证。

### WATChat 简洁 UI ↔ 经典 UI

**源码：** [companions/watchat/WATChat-code/frontend/index.html](../companions/watchat/WATChat-code/frontend/index.html), [companions/watchat/WATChat-code/frontend/app.js](../companions/watchat/WATChat-code/frontend/app.js), [companions/watchat/WATChat-code/frontend/style.css](../companions/watchat/WATChat-code/frontend/style.css)

**测试：** [tools/browser_smoke.cjs](../tools/browser_smoke.cjs)

**身份/权限：** 共享认证、密钥、pin、数据库、发件箱。**格式：** 唯一消息格式、唯一 IndexedDB数据库。

**缺口及修复边界：** Android真实设备、PWA安装提示、硬件麦克风仍需设备验证。

### Gateway ↔ Companions 原生路由

**源码：** [ziokt/application_router.py](../ziokt/application_router.py), [ziokt/companion_bridge.py](../ziokt/companion_bridge.py), [ziokt/mcp_schemas.py](../ziokt/mcp_schemas.py)

**测试：** [tests/test_application_router.py](../tests/test_application_router.py), [tests/test_mcp.py](../tests/test_mcp.py)

**身份/权限：** 目标配置一致、method allowlist、应用独立密钥。**格式：** 固定 JSONL 请求/返回。

**缺口及修复边界：** 新增方法需显式加入部署的 router methods；不自动扩大已有授权。

### Gateway ↔ Web Console

**源码：** [gateway/mcp-console.js](../gateway/mcp-console.js), [gateway/default_dapp/entrypoint.py](../gateway/default_dapp/entrypoint.py)

**测试：** [tools/gateway_browser_smoke.cjs](../tools/gateway_browser_smoke.cjs), [tests/test_gateway_native.py](../tests/test_gateway_native.py)

**身份/权限：** 沿用OAuth scopes和MCP幂等键。**格式：** 共享MCP能力模型。

**缺口及修复边界：** 控制台新上传流程已编写真实浏览器用例，尚未执行；静态运行/签名徽标已改为未观测；部署服务状态图仍不完整。

### Gateway ↔ ChatGPT MCP

**源码：** [ziokt/mcp.py](../ziokt/mcp.py), [ziokt/mcp_schemas.py](../ziokt/mcp_schemas.py)

**测试：** [tests/test_mcp.py](../tests/test_mcp.py)

**身份/权限：** OAuth audience、scope、过期、撤销、写入幂等审计。**格式：** 结构化MCP结果。

**缺口及修复边界：** 未在真实ChatGPT账号和已部署服务验证新工具。

### Gateway/MCP ↔ Telegram

**源码：** [ziokt/telegram.py](../ziokt/telegram.py), [ziokt/telegram_worker.py](../ziokt/telegram_worker.py), [ziokt/mcp.py](../ziokt/mcp.py)

**测试：** [tests/test_mcp.py](../tests/test_mcp.py)

**身份/权限：** chat/user allowlist与显式写入确认。**格式：** 结构化MCP调用、持久inbox。

**缺口及修复边界：** 本轮未连接真实Bot；大文件Bot适配未增加。

### 联邦注册 ↔ Corium

**源码：** [ziokt/registration.py](../ziokt/registration.py), [ziokt/registry.py](../ziokt/registry.py)

**测试：** [tests/test_registry.py](../tests/test_registry.py), [tests/test_community.py](../tests/test_community.py)

**身份/权限：** 成员政策、提交者签名、管理员批准范围。**格式：** 注册材料承诺/原生交易。

**缺口及修复边界：** 跨节点在线检测不由注册保证；新对象注册关联未实现。

### 工作流 ↔ 原生执行/审计

**源码：** [ziokt/workflow.py](../ziokt/workflow.py), [ziokt/control.py](../ziokt/control.py), [ziokt/mcp.py](../ziokt/mcp.py)

**测试：** [tests/test_control_native.py](../tests/test_control_native.py), [tests/test_native_operations.py](../tests/test_native_operations.py)

**身份/权限：** reviewed digest、fence、guard复核。**格式：** workflow.v1 / 原生operation状态。

**缺口及修复边界：** 缺通用 Saga补偿/取消协议和原生健康终态依赖。

### 恢复系统 ↔ Shadow6/Corium/对象库

**源码：** [ziokt/recovery.py](../ziokt/recovery.py), [spec/recovery_runtime.py](../spec/recovery_runtime.py)

**测试：** [tests/test_native_recovery.py](../tests/test_native_recovery.py), [tests/test_chunkstore.py](../tests/test_chunkstore.py)

**身份/权限：** 签名、AEAD、联邦域和epoch反回滚。**格式：** recovery.v1 / 原生检查点。

**缺口及修复边界：** 新分块索引/包保留记录备份导入与损坏检查点联合测试尚缺。

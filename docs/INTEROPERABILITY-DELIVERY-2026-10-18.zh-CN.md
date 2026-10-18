# 本批工程交付与验证边界

日期：2026-10-18。**本批完成了实际代码和定向验证，但尚未达到用户提出的全体系十项验收条件。** 未把编写测试、注册接口、保存文件、签名通过、原生提交或节点连接等同于全业务健康运行。

完整的 28 条自然协作关系及证据见 [源码审计矩阵](INTEROPERABILITY-AUDIT-2026-10-18.zh-CN.md) 和 [逐项机器可读矩阵](interoperability-matrix.json)。矩阵逐条记录原生/Gateway 接口、身份转换、格式、对象传输、业务完成程度、恢复、限制、测试位置、浅层桥接及剩余缺口。未将已有 110 对 opaque 对象交换测试描述成 110 对业务闭环。

## 已提交的工程批次

- `076796c`：分块对象、引用包、双签名原生交接、MCP及工作流修复。
- `6ddc172`：WATChat双界面、密文附件队列、上传去重、接收确认。
- `55e4f7c`：逐个读取待发密文附件，补充存储升级提示。
- `9be93fe`：门户观测状态、公开留言语义、渲染及浏览器夹具回归。
- CI与审计文档属于本记录所在的后续提交。

## 已落实的源码变化

- `ziokt/chunkstore.py`：在既有 SafeFS Vault 上加入可恢复分块存储适配。16 KiB 分块，应用独立 AEAD，HMAC 内容地址去重，持久进度，分块/完整对象摘要校验，有序可验证清单，逐块读取/生成器，有界对象与并发上传、内容保留租约、包保留记录、显式垃圾回收。SQLite 使用 FULL 同步；POSIX 在承认新块前同步数据目录。Windows 目录断电持久性未验收。
- `ziokt/ufsdcpm.py`：v1 仍为原有签名格式，恢复其已有 4 MiB 内容预算，移除 Gateway 在文件引用构建上的额外 32 KiB 限制。新增 v2 签名引用包，逐流验证内容，内容不进入 JSON/Base64 包封装；不声称 v2 已能安装到 Shadow6。
- `ziokt/package_handoff.py`：DCPM v1 的版本化 Shadow6 适配器。仅接收内含 `shadow6/package.zip` 的包，分别验证外层 DCPM 发布者与内层 Shadow6 原生签名；保留原始完整封装、原生内容及来源摘要。检查外内名称/版本、已安装版本冲突及已激活依赖。输出暂存证据，安装和执行授权均为 false。
- `ziokt/workflow.py`：修复领导者变量覆盖执行租约 owner，导致多步执行或租约清理错误的问题。状态新增 `execution_semantics`、`global_atomicity=false`、`application_health=not-assessed`，保留已有 state。
- Gateway/MCP：对象和引用包方法接入现有 Schema、OAuth scope、幂等写入及审计系统。仅配置了 Vault 的应用才发现对象工具。`component.status` 明确报告本地桥可达、原生运行未观测。
- `gateway/mcp-console.js`：复用原控制台，增加上传进度、暂停、选同文件续传、预期 SHA-256 输入，以及签名/授权/提交/健康等状态的说明。旧门户硬编码的 RUNNING/LISTENING/VERIFIED 等改为未观测，目录和示例不再冒充健康结果；公开留言不再冒充端到端密聊，写入失败明确报告并回退显示；新增空观测渲染与实际上下文/转义测试。使用 File.slice 逐块读取，不把完整大文件转成 JSON。
- WATChat：同一 DOM/状态模型支持简洁版和经典丰富版；加入主题选择、移动联系人/对话返回、绿色聊天气泡、图片/视频入口、语音录制、权限错误、媒体播放失败及保存入口、密文附件摘要、客户端密文附件持久队列、幂等上传、接收方确认和受限联系人在线状态。

## 新增接口契约

所有 Companion 方法都通过现有固定参数入口发布；未知参数拒绝。Gateway/MCP 返回结构化结果与稳定业务错误码。写入沿用应用 `:write` scope、全局写入启用开关、幂等键和审计；读取沿用应用 `:read` scope。引用本身不授予其他应用的读取权。原有 ApplicationRouter 部署必须显式加入 methods 允许列表，不会自动扩权。

| 方法 | 固定参数 | 返回 | 权限 |
|---|---|---|---|
| `object.begin` | upload, size, digest, ttl | `ziokt.upload.v1` | 应用 write |
| `object.status` | upload | 上传状态、接收数、首个缺块、到期信息 | 应用 read |
| `object.chunk.put` | upload, position, digest, data_base64 | `ziokt.chunk-receipt.v1` | 应用 write |
| `object.finish` | upload | `ziokt.object-reference.v1` + Ed25519 attestation + lease | 应用 write |
| `object.reference` | object（清单摘要） | 引用、验证语义、引用计数 | 应用 read |
| `object.chunk.get` | object, position | 单块 Base64、SHA-256、位置 | 应用 read |
| `object.abort` | upload | 取消后的上传状态 | 应用 write |
| `object.release` | object, upload | 释放此租约；其他租约/包保留仍有效 | 应用 write |
| `object.gc` | 无 | 回收块数和仍存活块数 | 应用 write |
| `package.build.references` | name, version, files（path→清单摘要）, dependencies | 私有 v2 包描述符引用，并保留内容 | UFS/dCPM write |
| `package.verify.references` | digest, authority | `ziokt.package-verification.v2`，逐流校验报告 | UFS/dCPM read |
| `package.release.references` | digest, authority | 释放包保留记录；保留描述符元数据 | UFS/dCPM write |
| WATChat `GET /api/presence` | 无 | `watchat.presence.v1`，仅本人的获准联系人在线布尔值 | 有效会话 |
| WATChat `POST /api/upload` 扩展 | 可选 `X-Upload-Id`（32 hex）；主体保持密文 | url, digest, duplicate | 有效会话、原有 Origin/上传限制 |
| WATChat WS `received` | action, id | 向发送者发 recipient-confirmed receipt | 接收者会话、联系人权限 |

`package.build`、`package.verify`、`component.status`、workflow.status 及旧上传接口保持兼容，只有新增字段/明确的预算修复。未提供任意 Shell、SQL、路径、进程命令或私钥读取工具。

对象错误包括：`OBJECT_LIMIT`、`STORAGE_QUOTA`、`UPLOAD_LIMIT`、`REFERENCE_LIMIT`、`OBJECT_METADATA_QUOTA`、`UPLOAD_NOT_FOUND`、`UPLOAD_EXPIRED`、`INVALID_CHUNK`、`CHUNK_INTEGRITY`、`UPLOAD_INCOMPLETE`、`OBJECT_INTEGRITY`、`OBJECT_UNAVAILABLE`、`CHUNK_NOT_FOUND`、`IDEMPOTENCY_CONFLICT`。包适配另有 `PACKAGE_FORMAT`、`PACKAGE_IDENTITY_MISMATCH`、`DEPENDENCY_MISSING`、`DEPENDENCY_INCOMPATIBLE`、`VERSION_CONFLICT`，以及现有签名拒绝和原生包错误。

MCP 审计记录工具名、请求摘要、调用者和结果，不记录明文内容/密钥。直接本地 Companion 调用保留自身持久进度，但没有凭空获得 MCP 的审计或远端能力委托属性。

## 限制必须分别理解

| 层 | 本批实际限制/性质 |
|---|---|
| 原生 ZFCP 请求/响应 | 原有 64 KiB / 256 KiB |
| 应用 JSONL | 原有 128 KiB；字符串 32 KiB |
| 新块 | 明文16 KiB；Base64最多21848字符；SafeFS密文最多32 KiB |
| 完整对象 | 512 MiB；每块单独读取；完成前完整SHA-256校验 |
| 应用存储 | 2 GiB 已索引密文预算，保守预留；不是全机器磁盘保留/系统硬配额 |
| 元数据/并发 | 16活动上传、4096上传租约、131072分块位置记录、4096包保留记录；需要释放/GC |
| v1 包 | 内容4 MiB、封装6 MiB；继续为有界内存格式 |
| v2 引用包 | 每文件64 MiB、总内容256 MiB、128文件、签名描述符64 KiB；不含压缩数据 |
| Shadow6 原生包 | 保留原生 ZIP 路径、签名、文件/总解压预算和安装检查；本批未改其流式实现 |
| WATChat媒体 | 浏览器11 MiB、服务器12 MiB、联邦inbox8 MiB；待发密文附件最多4项；录音60秒 |
| 验证资源 | 大对象CI限制256 MiB地址空间，断言Python追踪分配峰值<48 MiB；这些测试尚未执行 |

新对象/引用包不解压、不运行脚本、不接受文件路径，避免在这一层引入压缩炸弹或路径提取。原生 ZIP 的安全检查仍由 Shadow6 负责。SafeFS 旧 API、WATChat 媒体、原生包和 recovery bundle 的整对象内存限制仍存在，不能因此把全体系描述为流式。

完整对象采用清单哈希和全文件 SHA-256；读取者可以逐块重新构建有序清单并核对摘要。对象完成证明是某次验证的签名证据，不是永久可用性保证，也不授予跨应用读取/执行能力。GC 只回收没有上传/对象成员引用的块，不承诺物理擦除。完成租约和包保留记录需显式释放；中断上传TTL最长24小时，到期后GC可清理。崩溃留下的未索引块由显式GC清理。

## WATChat旧版比较与迁移

当前工作区未找到单独的 `WATChat-code.zip` 文件；使用仓库保留的 `companions/watchat/original/WATChat-code` 作为可追踪旧版基准，SOURCE.json 记录原归档名称与摘要。未声称比对了不存在的新附件。

| 项目 | 保留旧版设计/交互 | 本批实现与边界 |
|---|---|---|
| HTML/CSS | 手机联系人→对话、返回、深色绿色气泡、底部输入 | 现有DOM上实现两种正式视图；支持浅/深/系统主题；不禁缩放 |
| 状态/消息 | 联系人、对话、发送与恢复 | 唯一加密消息逻辑、用户体系、IndexedDB；切换不重建会话 |
| 图片/视频 | 独立入口、接收播放 | 当前加密上传/消息协议；摘要验证、播放失败提示；旧版压缩/缩略图未全部复刻 |
| 语音 | MediaRecorder、60秒上限 | MIME能力选择、权限拒绝、取消、自动释放麦克风；实际硬件未测 |
| 用户管理 | 管理入口 | 保留当前管理功能；旧版任意用户联系人编辑器未完整复刻 |
| 认证/WebSocket | 使用当前后端 | 保留 HttpOnly/SameSite/Origin、密钥pin、密文帧；不恢复旧版URL token和弱密码；门户公开留言另外明确标明明文，不冒充WATChat私密会话 |
| PWA/通知 | 安装、离线外壳、通知 | 缓存升级v4、保留其他应用缓存；通知只用通用唤醒，不传聊天明文 |
| 附件离线队列 | 原版欠缺持久化附件阶段 | 新增IndexedDB media store，仅保存密文文件和已加密消息帧；上传后原子转入outbox |

IndexedDB 数据库名保持 `ziokt-watchat-v2`，版本1→2只增 media store，保留keys/pins/outbox。部署更新服务工作线程后缓存升级v4；旧会话不因切换视图退出。服务器继续读取原有密文数据库/附件，新附件多记录owner绑定的at-rest purpose；旧客户端不提供上传ID仍可使用。`receivedAt` 是可选新增字段，旧消息照常读取。

附件发送、服务器已存储、接收者客户端确认分开呈现。接收确认不是已验证真实用户阅读，也不意味着跨联邦最终送达。跨设备密钥导入/授权同步未新增；原有缺少账户设备密钥时拒绝发送的行为保留。

## 本地实际验证

- Python定向短套件：`PYTHONPATH=tests:. python3 -m unittest test_chunkstore test_reference_packages test_mcp test_ufsdcpm test_ufs_dcpm_native_integration test_control_native -v`：19项，18通过，1项大型CI测试按明确门禁跳过，13.789秒。涵盖真实子进程续传、MCP对象/引用包、作用域拒绝、UFS HTTP发布/获取、Shadow6原生安装/激活、两步fence工作流。
- Node：`node --test companions/watchat/WATChat-code/test/security.test.js companions/watchat/WATChat-code/test/deployment.test.js companions/watchat/WATChat-code/test/sim_bridge.test.js`：7项全部通过，约2.7–3.3秒。含真实服务器、幂等上传冲突/所有者拒绝、媒体ACL、接收确认、联系人在线权限、数据持久化/重启、通用提醒与缓存保留。
- Gateway真实回环夹具启动、UFS门户HTTP渲染检查：通过；没有据此声称浏览器上传已验证。
- 修改Python模块的py_compile、JS的node --check、四个Actions YAML的BaseLoader解析、`git diff --check`：通过。
- `python3 ci/build.py`：通过，生成 `dist/ziokt.pyz`，包含CLI帮助和失败退出码检查。该文件为构建产物，不作为源码提交。
- `node tools/browser_smoke.cjs`：尝试运行，但Chromium headless shell二进制不存在，**浏览器未启动，不能记为通过**。未本地下载浏览器或运行长网络/压力/故障矩阵。

追加短测：最后的对象/引用包/MCP复核12项（11通过、1大型CI门禁跳过，4.290秒）；门户观测渲染3项通过（含公开留言不冒充E2EE、写入拒绝不伪装成功、历史内容转义）。

## CI覆盖及当前状态

新增 `.github/workflows/interoperability.yml`，保留原 companions/gateway/integration 和原生CI。companions.yml 加入对象/引用包短测；gateway.yml 加入门户观测回归和真实浏览器上传/重选文件恢复用例。原生源码锁未改，Corium/Shadow6源码未被此批改写；Shadow6原有用户修改 `config.json.example` 保留。本地Shadow6 HEAD为 `39a6a8b4`，CI锁为 `d12acb94`；包管理器、本批使用的CLI、service_registry/service_storage在两者之间没有差异。Corium为锁定的 `6e00bd4d`。`tools/sync_providers.py --check` 通过。

| 层 | 实际测试代码/配置 | 本提交结果 |
|---|---|---|
| 单元/边界 | chunkstore、reference_packages、现有crypto/CPU/Ano/组件套件 | 本地定向部分已过；CI未执行 |
| 组件互通 | MCP对象/引用包；DCPM→真实UFS HTTP→Shadow6原生prepare/commit | 本地短测通过；CI待执行 |
| 多进程 | Python子进程续传、真实Shadow6CLI、真实WATChat服务器 | 本地短测通过；CI待执行 |
| 大对象 | PR32 MiB；定期/手动128、384 MiB；最多2分片并发 | 只编写，尚未执行 |
| 损坏/失败 | 摘要错误、AEAD损坏、身份拒绝、过期、配额、幂等冲突、真实存储失败 | 小型短测通过；完整故障矩阵尚未补齐 |
| 浏览器 | 简洁/经典×手机/桌面4组；真实ECDH、图片、视频、音频、合成麦克风、拒绝、切换、语言、离线附件、PWA外壳 | 尚未执行；Android大小视口不等于真实Android设备 |
| 既有ETP/网络 | 保留原ETP原生进程/论坛、原生网络/NAT及恢复测试 | 本批未执行；不冒充新对象层跨节点容错 |

测试全用临时隔离目录、测试密钥和回环服务器。失败保留日志，浏览器异常时保留测试页面截图。未关闭签名、权限、完整性或TLS检查；已有回环HTTP测试的明文传输仅用于隔离HTTP认证协议测试，不作为生产TLS建议。

本批**未 push、未触发 GitHub Actions**。所以不存在“本提交CI已通过”的结论。工作流文件完成与远端运行结果严格区分。

## 部署与原生包交接

1. 审阅新源码与矩阵，在CI完成后再部署。已有生产服务和数据本轮未操作。
2. 更新Ziokt后，MCP为已有明确配置的Vault应用发现新方法，仍受scope及全局写入开关约束。直接ApplicationRouter需要管理员显式增加所需方法允许列表，不自动添加新信任关系。
3. 原生软件先用Shadow6原有签名工具构建包；由dCPM将原始zip以 `shadow6/package.zip` 文件承载，保持外内名称和严格SemVer一致。v1容量限制不变。
4. UFS保存/发布/获取后，操作者可运行下面的本地适配命令。参数均为本机操作者选择；没有远端任意路径接口：

```sh
python3 -m ziokt.package_handoff \
  --package /operator/verified-download.zpkg \
  --publisher <明确可信的DCPM发布者公钥> \
  --shadow6-root /operator/Shadow6 \
  --trust-file /operator/native-trust.json \
  --artifact-root /operator/artifacts \
  --package-root /operator/packages
```

5. 审阅适配结果后，以原生 `package.install` 的artifact_digest和selector执行 prepare/commit，再独立审阅 `package.activate`。服务运行继续要求真实命名服务绑定、Core/Profile兼容性和独立授权；适配结果不能代替这些前提。依赖预检查是暂存时的快照，不是安装时锁定依赖的承诺。
6. 分块对象保存在 `<vault_root>/chunks-<application>/`；旧Vault对象不迁移、不重写。复制/备份此数据必须一致保存索引和密文块。本批未实现新对象层的备份恢复协议，不能只复制SQLite或只复制data后声称完整恢复。

## 尚未完成的验收条件

全体系尚缺：通用大包到Shadow6流式安装、包/服务依赖绑定与启动健康回滚、跨节点部署对账、新对象层到ETP/UFS原生传输的适配、论坛附件和编辑冲突同步、Tri/TC-16/ZDA跨引擎语义及证明验证、WATChat大附件分块传输与设备密钥授权同步、通用工作流Saga补偿/取消、新索引检查点恢复，以及对应真实网络/设备/完整故障矩阵。现有可用功能没有为这些缺口而被关闭或替换；本批也未以mock或纸面接口填充完成状态。

# Content Fabric / Library / Netnews 工程入口

这是可选新增应用层，不改变已有 Community、Corium、ETP、Shadow6 服务和静态托管策略。全量要求的完成情况见 [WORK_ITEMS.md](WORK_ITEMS.md)，不得把此阶段已运行的功能视为整套生态已全部验收。

## 启动独立应用

依赖沿用仓库 requirements.txt；Python 3.11+，SQLite 必须支持 FTS5。无需本地构建 ETP/Rust。仓库根目录执行：

```sh
python3 -m pip install -r requirements.txt
python3 -m tools.configure_content --directory "$HOME/.local/share/ziokt-content"
python3 -m ziokt.content_server --config "$HOME/.local/share/ziokt-content/content.json"
```

打开 `http://127.0.0.1:8210/`。从生成的 application.token 文件取得应用凭证，输入连接表单。凭证只留在页面内存，刷新需重新输入。该凭证不是 Gateway 管理口令。默认只监听本机，NNTP 为 8119，需认证；本地开发允许明文 loopback AUTHINFO。对外监听必须配置 tls.cert/key；生产 NNTP 同样使用独立 TLS 与端口。

用户服务配置：`deploy/content-fabric/ziokt-content.service`，按实际 Python/虚拟环境路径调整 ExecStart 后安装为 systemd 用户服务。服务默认内存 512 MiB、CPU 一核、文件描述符 1024；HTTP/NNTP 各限制 16 条并行连接。

## 接入已有 Gateway / MCP 和 GUI

在已有 MCP 配置中增加明确 opt-in：

```json
{"content_fabric":{"enabled":true,"root":"/private/content-state","accounts":{"ziokt-operator":"owner"}}}
```

root 可与独立应用服务指向同一数据库。向指定 MCP client 显式授予所需 library:read/write、netnews:read/write、content:read/write、applications:write、community:read/write。同步和维护需要 content:admin。已有 Gateway 管理凭证不会自动成为独立 HTTP 应用凭证；已有 MCP client 也不会自动取得新 scopes。

主 GUI 的 Library / Netnews 页面通过原有 `callTool`、Gateway 鉴权与 MCP 审计调用新实现。没有配置时会明确报工具不可用，不显示假书目或假投递结果。修改源 GUI 后，可执行 `node gui/build.js --bundle-only` 仅生成文本 bundle；完整打包仍走原构建流程。

## HTTP / MCP 操作

POST /api：`{"operation":"library.search","arguments":{"query":"sample","limit":30,"offset":0}}`；Authorization: Bearer 使用应用凭证。MCP 将点号换为下划线，如 library_search、content_upload_begin、netnews_post。精确字段由 `ziokt/content_api.py` OPERATIONS 定义并用于注册工具。

内容：upload.begin/put/status/finish、object.info/get/verify、withdraw、health、sync、subscription.get/save。上传每个 put 最多 16384 原始字节，JSON 只承载一个有界 Base64 分块，不承载整本大文件。

Library：publish、search、get、reading.get/save、download。搜索使用 SQLite FTS5，支持语言、年、格式、ISBN、作者、标签、作品/版本组合过滤。当前全文索引涵盖实际保存的元数据与可选 text 字段；尚不自动解析整本 PDF/EPUB。

Netnews：groups、group.create、post、articles、search、get。公开/私人组、只读组策略由节点执行；Message-ID 与本地序号独立。文章正文当前限制 8192 UTF-8 字节。客户端不能指定其他账户的 From 身份。

TC-16：applications.tc16.compile/execute，见 [TC16-UNIFIED-V1.md](TC16-UNIFIED-V1.md)。

大文件：

```sh
python3 -m ziokt.content_client --url http://127.0.0.1:8210 \
  --token-file "$HOME/.local/share/ziokt-content/application.token" \
  --upload-id reusable-local-operation your-authorized-book.epub
```

客户端两遍流式处理文件（计算摘要、分块发送），默认对象上限 512 MiB；浏览器自身上传/阅读预算为 16 MiB。文件传输也支持授权 GET /objects/ID 和单段 HTTP Range，响应以 attachment/octet-stream 输出，不执行不可信 HTML。

## 配置多节点

每个节点使用独立 root、密钥、数据库、监听地址。peers 按别名配置固定 url、public_key、token、可选 ca 与允许的 groups。public_key 是对方 Content Fabric 节点签名公钥；token 是对方明确授予 content:replicate/content:read 的应用凭证。非 loopback URL 必须 HTTPS，不跟随重定向。所有原始事件发布者均需在本地钉住，不因转发者可信而自动信任未知发布者。

在本地创建允许同步的公开新闻组后，通过 content.sync（参数 peer 别名）拉取增量；HTTP 同时保留 federation.sync 管理入口。同步保存事务、游标与冲突记录，不使用内存消息表。目录同步只传目录与文章，不强制下载图书。library.download 显式选择已配置来源，持久记录已验证分块和下载状态；逐块 Merkle 证明及最终 SHA-256 通过后才完成。当前为有界串行多源回退，尚不提供并行下载或自动后台调度。

## 身份、隐私与授权 Community API

账户名称由认证传输映射，不接受调用者冒充 owner。每个账户有独立 SafeFS 密钥与去重域；对象字节 AEAD 加密，SQLite 元数据是 owner-private 文件，**不是数据库加密**。公共事件包含发布账户、节点公钥、时间和公开书目；私有记录不进入公共导出日志。此模型尚不提供跨账户端到端共享、成员撤销后抹除历史密钥或匿名发布证明。

community 配置可指向既有 Community：root、policy、owner、encryption_key，以及 accounts[应用账户] 中的 public_key 和仅写入时需要的 signing_key 文件。接口 community.forum.list/post 检查真实成员 forum 权限，保留原始签名封套，按 operation 幂等。读取身份不必持有写入私钥。未知应用账户拒绝。

给静态应用授权时，单独配置允许的 origins 和只有 community:read/write 所需 scope 的应用凭证。CORS 预检只允许明确来源；该接口没有 Gateway 管理、执行、密钥导出和任意路径参数。既有托管 CSP 不变：接口授权不自动授予托管页联网能力，仍需单独的受控应用部署或能力代理配置。当前没有第三方 OAuth。

## NNTP 实现边界

提供 CAPABILITIES、MODE READER、LIST ACTIVE/NEWSGROUPS/OVERVIEW.FMT、GROUP、ARTICLE、HEAD、BODY、STAT、NEXT、LAST、OVER、HDR、POST、DATE、HELP、QUIT 和 AUTHINFO USER/PASS。支持点转义、CRLF、真实磁盘提交和可选独立 TLS。默认无匿名读取，只有明确授予 netnews:write 的应用身份能投稿，不能作为开放转发中继。

当前是有界读取/投稿适配器，**不是完整 RFC 3977/5536/5537 合规声明**。已实现授权 feed 的 IHAVE、CHECK、TAKETHIS、MODE STREAM，以及有界 MIME 附件收发和原生附件引用；feed scope、组过滤和附件权限仍须独立满足。能力与限制参见 [FEEDS.md](FEEDS.md)、[ATTACHMENTS.md](ATTACHMENTS.md) 和 [WORK_ITEMS.md](WORK_ITEMS.md)。真实 Thunderbird/slrn/tin 全命令兼容矩阵尚未验收，不宣称完整 RFC 合规。标准参考：[RFC 3977](https://www.rfc-editor.org/rfc/rfc3977)、[RFC 5536](https://www.rfc-editor.org/rfc/rfc5536)、[RFC 5537](https://www.rfc-editor.org/rfc/rfc5537)、[RFC 4644](https://www.rfc-editor.org/rfc/rfc4644)。

## 迁移、删除和冷恢复

首次启用在新 root 创建独立数据库，不读取或改写旧应用数据。迁移表记录 v1 数据模型与 v2 FTS5 索引。FTS5 迁移在事务内完成。单节点旧功能不必启用新服务。

content.withdraw 只允许本地原发布者，产生签名墓碑。旧事件重放不覆盖墓碑；远端删除只意味着本地不再有效发布，不保证物理删除其他节点的副本。到期文章从查询中排除；目前长期保留同步日志与墓碑，物理对象 GC、成员 epoch 清理和全面缓存淘汰尚未完成。磁盘预算包括加密填充与上传保留，过期租约回收仍需继续完善。

停止应用写入后创建冷检查点：

```sh
python3 -m ziokt.content_checkpoint create /private/content-state /private/new-snapshot
python3 -m ziokt.content_checkpoint restore /private/new-snapshot /private/new-state --authority EXPECTED_NODE_PUBLIC_KEY
```

检查点用 SQLite backup 捕获 WAL，复制密文和独立账户密钥，签名列出每个文件摘要。只恢复到新目录，拒绝路径穿越、符号链接、额外文件和摘要不符。检查点包含私钥，必须按节点私密备份保管；它不是可公开分发的目录快照。不支持运行中无协调写入的跨数据库一致快照。

## 测试与交付

本地轻量测试见 tests/test_content*.py、test_community_application.py、test_tc16_spec.py。真实浏览器脚本 tools/content_browser_smoke.cjs；三独立进程测试 test_content_multinode.py；Rust 多副本与差分脚本在 ci/。完整 ETP 编译只交给 GitHub Actions。独立轻量宿主编译只能证明被包含的源码模块与实际进程交换，不能代替完整 ETP Core 集成。

全量 CI 配置在 .github/workflows/content-fabric.yml；实际 CI 结果必须以对应 commit 的运行记录为准。示例馆藏为本仓库原创 CC0 短文本，不抓取第三方受限馆藏。

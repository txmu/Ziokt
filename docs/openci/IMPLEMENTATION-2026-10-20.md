# Ziokt / OpenCI 实施记录（未全量完成）

## 执行与证据原则

Corium、Shadow6 为创始原生组件，ETP 等 Companion 保持独立运行。重用原生引擎；不得把注册、HTTP 接受或任务完成当作内容同步、验证或结算完成。新增主网交易、生产密钥/数据库升级和公开服务变更均未执行。

按用户补充：distcc、QEMU、Buildroot 及大型原生编译只在 CI 执行。本机缺少这些工具不构成阻塞。本机仅进行源码审阅、语法检查、轻量原生回归和浏览器测试。CI 配置文件存在不表示 CI 已通过。

## 已定位的实施顺序

|阶段|原生落点/现状|下一验收条件|
|---|---|---|
|P0-A|`companions/etp/src/src/extensions/tc16_tcc.rs` 为 Legacy CPU/编译器；`tc16_unified.rs` 为独立 Unified VM；`ziokt/tc16_spec.py` 明确拒绝不支持的 Legacy 编译|先冻结 MMIO/栈/整数溢出/中断/存储语义，增加 Rust 后端与真实 ETP 程序差分；不能直接重标 ISA|
|P0-B|`ziokt/content_fabric.py`、Library/Netnews 已有共同引用；原生 Corium Forum/Wiki 与 ETP Forum/FileShare Adapter 仍未完成|带身份授权的原生写入、签名保存、撤回/冲突、防环、游标恢复测试|
|P0-C|工作区未发现独立 OpenCI Controller/Scheduler/Runner 实现|持久 DAG/任务/租约、隔离 Runner、取消、恢复、日志和制品；独立于 PoUW 运行|
|P0-D|新增 `ci/openci/` 和 `openci-buildroot.yml` 为真实构建验收工具，尚不是 OpenCI 服务|CI 两架构交叉工具链、真实 distcc 工作、ccache 命中、镜像启动与日志；仍需接入 P0-C|
|P0-E|需以 Corium 原生 compute_engines/pouw_engine 注册及治理为准|所有者审批、原生验证器、贡献去重及测试网结算；CI 记录不自动视为 PoUW 证明|
|P0-F|`Corium/corix_v108.sh` 保留 test-/dev- 激活限制、持有人授权及审查交易|扩展恶意请求/签名/份额门槛/重放/恢复测试，独立审计与主网升级另行进行|
|P1/P2|原完整剩余项仍在 Content Fabric `REMAINING.md`|签名发现、发行生态、安全供应链、版权治理、真机与性能矩阵|

## 本轮真实修改

- 移除 GUI Web/Android/源文件中未配置的 chat/ufs/shadow6 独立域名，保留节点内授权操作。
- 参考 Caddy 配置不再绑定这三个独立域名；同域服务代理保留原始 Host。参考 WATChat origin/联系地址改用已有 cor-web 域名。未重载生产 Caddy 或修改实际 WATChat 运行配置。
- Shadow6 `Control-Center/web_gateway.py` 移除旧 sslip.io 和未配置独立域名的 Host/Origin 白名单，保留既有本地认证与 CSRF 控制。未重启生产进程。
- S6P1 不再嵌入旧 IP/假节点身份。按同一 UI profile 表生成 13 路由、12 个去重 Core 的明确未验证示例，加入原生所需 components 字段。原生 `unpack_protocol` 已接受实际浏览器生成的信封。
- `/api/gateway/public-address` 从固定 HTTPS 观察源探测服务器出口 IP，严格限制响应、超时并缓存；拒绝私网地址、重定向及代理；失败返回 503/`ok:false`，不复用过期旧地址。出口 IP 不证明入站、NAT 映射或 Core 可达。没有生成 sslip.io 域名或自动申请证书。
- S6P1 路由字段按文本转义，不把客户端格式解析称作密码学验证；保存 API 返回 error 时不显示保存成功。
- 动态视口与 flex 子项缩小规则修复小屏滚动；同步 PWA 缓存版本。
- README 改为准确说明已实现的 NNTP feed 和有界 MIME，保留客户端验收限制。

## 本轮本机证据

- `python3 -m unittest discover -s tests -p test_gateway_observation.py`：5 项通过。
- `python3 -m unittest discover -s tests -p test_public_address.py`：3 项通过；观察源为受控响应，未声称真实公网探测验收。
- `node gui/build.js`：打包和 JS 语法通过，Web/Android 静态副本已同步。
- `node tools/gui_viewport_smoke.cjs`：真实 Chromium 192/320/390/1440 像素视口底部可达，无文档横向溢出；受控地址响应生成 S6P1 后交原生 Shadow6 解析器接受；恶意 HTML 字段不生成 DOM 元素；浮点字段被拒绝。
- `Corium: python3 -m unittest test_privacy_consensus.py -v`：原生签名请求→投票→重建 1 项通过，并确认批准后披露表仍为空。此测试不覆盖所有持有人签名攻击或独立密码学审计。
- `Shadow6: .venv/bin/python -m unittest discover -s Control-Center -p test_web_gateway.py`：认证/CSRF/会话及退休域名拒绝 4 项通过。
- 只读 systemd 核查：Corium 共识/P2P/relayer、Gateway/MCP、内容/NNTP/TLS NNTP、UFS、WATChat 及 Shadow6 进程仍运行。这只证明进程状态，不证明业务健康。

## 迁移、回滚与权限边界

本轮没有数据库 schema 变更、ISA 重标、密钥轮换或主网状态写入。回滚代码提交并重新构建 GUI 即可恢复旧静态资源；参考配置不是生产部署变更。已保存的 S6P1 配置不会被自动改写。

|操作|权限边界|本轮状态|
|---|---|---|
|公网地址观察|固定外部 HTTPS，只输出出口 IP，不处理用户目标 URL|只读公开端点；不授权任何 Core 操作|
|S6P1 解析|用户数据的格式预检，不等于准入/签名验证|授权仍由原生组件执行|
|SafeFS 保存|既有 vault API 必须明确返回 success|失败不包装成功|
|Shadow6 控制|保留会话、Origin、CSRF、后端令牌隔离|未扩大操作授权|
|distcc 测试|仅临时 CI VM 的回环监听与编译器白名单，无发布密钥|不是公网 Worker、SSH/mTLS 或多宿主信任验收|
|制品/贡献|CI 产物记录不等于签名发布、dCPM 安装或 Corium 验证|这些状态全部保持未验证|

## 组件互通状态

|路径|本轮证据|
|---|---|
|Gateway UI → Shadow6 S6P1 原生格式|真实浏览器生成→原生解析通过；未宣称网络准入成功|
|GUI → 小屏 Web/Android 资源|同源打包与 Chromium 视口测试；Android/手表真机未测|
|Library ↔ Netnews 共用引用|已有实现；本轮仅修正文档，未重新验收全内容网络|
|Library/Netnews ↔ 原生 Corium/ETP/Shadow6/UFS/dCPM|未完成；保留原待办|
|OpenCI → Buildroot/distcc/QEMU|新增 CI 验收工具；需记录实际 run 结果|
|OpenCI → 原生存储/签名发布/Corium PoUW|未接通，不能以 GitHub artifact 上传代替|

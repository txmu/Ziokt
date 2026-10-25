# 统一客户端：真实后端使用说明

版本：1.0.0，发布验收以对应 GitHub Actions 的结果和下载页清单为准。Web 入口：https://app.ziokt.com/ 。安装包入口：https://github.com/txmu/Ziokt-Releases/releases 。

## 连接与鉴权

打开业务页面，输入 Node administrator token，再点“连接并刷新工具”。令牌来自节点私有的 `config/admin_token.key`，不是 Telegram Token。令牌只在当前页面内存中保留，刷新页面后需要重输。旧版本浏览器 localStorage 中的认证令牌会清除；节点地址和主题可以保留。不要把令牌放入 URL、截图、软件包或工单。

Web 页面通过 Gateway 的 `/api/gateway/tools` 和 `/api/gateway/tools/call` 调用相同的 MCP 调度器，复用 scope、写入开关、幂等键、审计和原生策略校验。服务端需要私有 Gateway 配置的 `mcp_config` 指向本节点的 MCP 配置。跨来源访问仅允许 `gui_origins` 中的明确来源；未授权的请求和未确认的写操作会拒绝。

## 功能页

首页显示实际状态工具；网络页显示 Shadow6/ETP 的真实状态与能力；开发页提供 Corium、TC-16、Tri 和 ZDA 的真实工具。工具列表和参数 schema 来自服务器，不使用静态区块高度、随机证明或随机延迟。选择工具，填写 JSON，再执行；所有写入都要明确勾选确认。错误会如实显示，未安装、未激活或没有原生运行证据时不会显示成功。

文件页可实际分块上传文件内容：`object.begin` → 每块 `object.chunk.put` → `object.finish`。每块 16 KiB，浏览器单文件限额 64 MiB；后台对象协议还有独立限额。上传回执包含完整摘要和 `manifest_digest`。输入该引用可以逐块下载，客户端核对块摘要、总长度和完整 SHA-256 后才保存文件。对象和引用受应用 scope 隔离，不能把 SafeFS 的引用直接冒充 dCPM 的引用。

## 原生软件包

1. 所有者通过 `ziokt_package_signer_update` 明确批准原生 Ed25519 发布者；默认信任表为空。
2. 选择独立签名的 Shadow6 原生 ZIP，填写与其签名一致的包 ID、版本。
3. “生成 v2 引用包并验证原生签名暂存”把真实 ZIP 分块存入 dCPM，生成外层 v2 签名引用包，再进行外层 dCPM 与内层原生签名的双重验证。
4. 暂存回执给出 `selector`、`receipt_digest`、`artifact_digest`，并明确 `installed: false`。
5. 所有者执行 `ziokt_package_admission_approve`，以精确回执摘要和 selector 批准该版本准入。随后调用原生 `package.install.plan` / `package.activate.plan`，审阅实际计划，再通过 workflow apply 执行。

生成签名、暂存、准入、安装和激活是不同状态。GUI 不执行包内安装脚本，不隐式信任新的发布者，不把上传等同于安装。v1 原生交接保持兼容，v2 直接使用已验证的对象引用，不重新签署内层原生包。

## 平台状态

Linux systemd 环境的 Tauri 组件控制调用固定单元名，再读取 `is-active`；权限不足、缺少服务或超时均返回错误。其他平台不声称已启停本地服务。TCP Ping 建立实际连接，返回真实经过时间；它不代表组件业务健康。

Windows/Linux/macOS 安装包由 CI 实际构建，不把前端静态目录压缩包命名成桌面程序。macOS 未提供 Apple 发布证书时使用 ad-hoc 签名，不等同于 Apple 公证。Android 从 1.1 使用节点所有者持有的持续发布签名，通过 CI 私有凭据注入签署，签名密钥不进入源码或安装包；旧调试签名版本可能需要先卸载。Android 通过受控 HTTPS 资产源加载本地资源，不开放 file URL 的任意跨域权限。HarmonyOS ArkUI 工程仍需对应 SDK、签名材料和真实设备验收，源码包装档案不标作可安装 HAP。

## 验证与隐私边界

`gui/tests/test_gui_e2e.py` 实际通过 HTTP 写入并读取加密对象；`tools/gui_browser_smoke.cjs` 在真实浏览器中输入令牌、点击上传、独立读回并验证内容，同时检查凭据未持久化。跨浏览器和 WATChat 的媒体/录音/离线测试由 CI 执行；浏览器仿真不等于真实手机硬件验收。

ZKN 的新接收密钥、加密回执、固定大小封装和匿名载体不等于屏蔽链上持有人。当前链上所有权变化仍可观察，认证接收端也能识别调用者。`ziokt_privacy_status` 和 Telegram `/privacy` 会报告这些事实，不会把它描述成已实现的完全匿名账本。

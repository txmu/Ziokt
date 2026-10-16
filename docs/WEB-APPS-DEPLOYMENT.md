# WATChat、SIM Manager：独立部署与 Ziokt 桥接

## 运行与数据边界

WATChat 的默认页面标题为“网页管理”。管理员在“管理用户”中可编辑标题；
服务端验证并保存在加密数据库中，同步到页面与动态 PWA manifest。普通账户
无权更改；浏览器离线时仅缓存不敏感标题。账号、密文消息、订阅与调度状态
保存在 DATA_DIR 的加密文件中；E2EE 私钥仍留在最初登记的浏览器。

SIM Manager 可完全静态部署，号码/卡片/PIN 状态留在加密 IndexedDB。
设置中的可选“Ziokt 提醒网关”使用同源 HttpOnly 会话登录，不保存登录密码。
发送到网关的是提醒标识、时间及是否选择 webhook，不包含号码、PIN、套餐内容。
桥接状态区分“配置存在”和实际送达；没有网关仍可本地管理与前台提醒。
Web Push 需 HTTPS、服务端 VAPID 配置、用户许可和实际设备订阅；未实测手机送达。
Webhook 目标由服务器管理员配置，不接受浏览器提交的任意回调地址。

WATChat 与 SIM 应使用独立 HTTPS origin、存储目录、账户和密钥，避免 root
Service Worker、会话及 IndexedDB 的作用域混用。WATChat 缓存清理只删除自身
前缀缓存，不再清除 SIM、Tri 等其他应用缓存。

## 可复用部署步骤

需要 Node.js 24（兼容回退到 22）、Python 3.12+ 与 Ziokt 的安全依赖。

```
python3 -m pip install -e '.[security]'
npm ci --prefix companions/watchat/WATChat-code --omit=dev --ignore-scripts
python3 tools/configure_web_gateway.py --root /srv/ziokt/watchat --application watchat --origin https://chat.example.org --port 8182
python3 tools/configure_web_gateway.py --root /srv/ziokt/sim --application sim-manager --origin https://sim.example.org --port 8183
```

脚本生成独立的私有策略、密钥、有效 bridge.json、Vault 和 service.env；
拒绝覆盖既有目录。`--standalone` 显式生成不依赖联邦桥的配置。私有配置不能放在
HTTP 静态根中。生产部署可用 `--python` 和 `--project-root` 固定 Python 与版本化
Ziokt 源码目录或 `.pyz`，不运行网络下载的任意脚本。

以运行用户启动 Node：为进程设置 service.env 中的环境变量，再运行
`node companions/watchat/WATChat-code/backend/server.js`。
该文件采用 systemd EnvironmentFile 引号格式，不应当成 shell 脚本执行。
推荐 systemd：User 指定普通账户，EnvironmentFile 指向该私有文件，ExecStart
固定 Node 24 及 server.js，UMask=0077，NoNewPrivileges=true，Restart=on-failure。
后端只监听 loopback；HTTPS 代理须保留公开 Host/Origin、WebSocket upgrade。

SIM：

```
cd companions/sim-manager/src
npm ci --ignore-scripts
npx tsc --noEmit
npm run build
# 可选独立根目录构建，所有 worker、通知与 PWA scope 跟随 base：
SIM_BASE_PATH=/ npm run build
```

默认把 dist 部署到 `/sim/`，SPA 回退到 `/sim/index.html`；同 origin 的
`/api/*` 和 `/app-config` 反代至 SIM 专用网关，不要回退为 HTML。独立静态部署
可省略反代，此时网关面板显示未连接。`SIM_BASE_PATH` 仅接受绝对目录前缀。
配置 VAPID 时将 `{subject,publicKey,privateKey}` 保存为 0600 JSON，由
WATCHAT_PUSH_CONFIG 指定；subject 应是运营者 HTTPS 联系地址或邮件地址。
首次账户为 admin，随机密码仅写到私有 service.env，不进入源码与包。

## 本机部署

- WATChat：https://ziokt-chat-43-207-75-185.sslip.io/
- SIM：https://ziokt-sim-43-207-75-185.sslip.io/sim/
- Node：已核验官方归档 SHA-256 的 v24.22.0，两个独立 systemd 服务。
- 本机桥接均使用真实私有 Community SQLite/CAS；这不是已有远端社区的副本，
  不代表已加入互联网联邦或获 Corium 链上确认。
- 私有账户信息：`/home/admin/.local/share/ziokt-production/webapps-access.txt`。
- 服务：ziokt-watchat、ziokt-sim-manager、ziokt-https。

## 微信访问与算力档位

公开只读 GET 不再因外部跳转的 Sec-Fetch-Site 被拒绝；保留精确 Host、CSP、
CORP 与无 CORS 响应。计算 POST 仍要求精确 Origin 和同源 Fetch Metadata，
不增加微信 UA 白名单、不信任任意代理头、不降低 TLS。

奋斗五档本地预算：

| 档 | 最大 Worker | 每批哈希数 | 批后休息 ms | 每 Worker 并发 digest |
|---|---:|---:|---:|---:|
| 1 | 1 | 64 | 40 | 1 |
| 2 | 1 | 256 | 20 | 2 |
| 3 | 2 | 512 | 5 | 4 |
| 4 | 4 | 1024 | 1 | 8 |
| 5 | 8 | 2048 | 0 | 16 |

Worker 数还受硬件线程数限制；每个 Worker 使用不重叠 nonce 分区。服务端任务
不能提高本地档位。总任务仍限 100 万 nonce、90 秒；找到证明立即终止其他
Worker。实时显示实际哈希量/速率，等待新链任务时不做无用计算，不故意占满内存。
“允许后台继续”需主动勾选，默认关闭；取消时后台任务立即停止。浏览器/系统仍可
限速冻结。切换到另一个标签可继续；关闭或完整导航离开计算文档会终止 Worker。
页面提供独立计算页及新标签浏览器链接，避免把“后台可运行”误称为锁屏永久运行。

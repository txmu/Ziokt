# 原生应用桥与公开奋斗页

## 同一调用入口

在 Shadow6、Corium 所使用的 Python 环境中安装 Ziokt（源码部署可用 `python3 -m pip install -e '.[security]'`）。原生提供者仍可独立运行；未安装 Ziokt 时，新增 companion 命令明确返回 `COMPANION_UNAVAILABLE`。

```sh
python3 -m ziokt companion app call --bridge-config /srv/ziokt/router.json --request /srv/ziokt/request.json
python3 /path/to/Shadow6/CLI/shadow6.py ziokt companion app call --bridge-config /srv/ziokt/router.json --request /srv/ziokt/request.json
bash /path/to/Corium/corix_v108.sh ziokt companion app call --bridge-config /srv/ziokt/router.json --request /srv/ziokt/request.json
```

三个命令接收同一种请求：

```json
{"target":"tc16","method":"tc16.run","params":{"source":"int main() { return 65535 + 2; }","syntax":"tcc","cycles":1000}}
```

结果来自实际 TC-16/TCC，`registers[0]` 为 1。方法名不是任意命令，接收的文件、包和消息不会自动运行。

[完整路由模板](examples/application-router.json) 覆盖十大部件及 Tri。复制后替换所有路径、ETP 二进制摘要；路由、请求、桥配置和密钥文件须由运行用户拥有，权限为 `0600`，私有目录为 `0700`。每个本地桥的 `application` 必须等于路由目标。Shadow6/Corium 后端沿用已启用、摘要锁定的 federation 提供者及其权限；ETP 使用 CI 构建并核验摘要的网关。缺失后端会明确报错，不回退到另一种实现或直连。

| 目标 | 实际调用 |
|---|---|
| Shadow6 | `status.get`、`capabilities.get`、`objects.list`、`service.binding`；已有原生操作仍由提供者授权 |
| Corium | 原生状态、P2P 对象清单、链事实与 `compute.challenge`；链写入保留 prepare/commit/reconcile |
| WATChat | `chat.append/pull/ack`、`file.publish/read`，浏览器密文保持不解密 |
| SafeFS | `vault.put/get/publish`、`safefs.publish/read`，按应用密钥隔离 |
| ZDA/Ano | `ano.evaluate`、`ano.laws`、`ano.calculate`、`ano.defence`；数学性质与授权决策分开 |
| UFS、DCPM | 各自作用域中的 `vault.put/get`、`package.build/verify/publish`，保留签名包与存储结合 |
| TC-16/TCC | `tc16.run`，显式源码、语法和指令预算 |
| ETP | `etp.stats`、`etp.onion.send`、`etp.receive`、显式启用的 `etp.forum.identities/subscribe/publish/get`；固定批准路径与二进制 |
| SIM Manager | `sim.reminders.replace/pull`、加密状态文件交换 |
| Tri | `tri.put/get/publish`、加密项目与签名文件发布 |

`vault.put` 接收 `name` 与 `data_base64`；`vault.get` 接收 `digest`。小 RPC 的明文数据上限为 32 KiB，大文件使用已有加密不可变对象引用。`package.build` 的 `files` 为路径到本应用 vault 摘要的映射；`tri.put` 接收 `program`、`state`。所有组件还共享配置了固定收件密钥的 `component.send/receive`。

连续调用可使用同一配置的有界 JSONL 入口，ETP 后端跨请求保留会话：

```sh
python3 -m ziokt companion app serve --bridge-config /srv/ziokt/router.json
```

每行仍是上述 `{target,method,params}` JSON；EOF 释放子进程。路由配置变更后必须重启。
`ano.calculate` 处理版本化精确数值文档，`ano.defence` 只评估显式证据，不替代签名验证。
`package.verify` 校验现有签名包与指定发布者；`package.publish` 发布经验证的社区包事件，
不执行安装脚本。原生 UFS/DCPM 同样读取这一签名包格式，其实际 HTTP/TLS 产品接口和
配置见 [UFS 原生接口](UFS-NATIVE-HTTP-2026-10.md)；应用桥不自动启动这些监听器。
ETP Forum 的私有库、作者密钥及订阅配置见 [原生论坛网关](ETP-FORUM-GATEWAY.md)。

## SIM Manager 提醒的实际调度

为 SIM Manager 建立 `application:"sim-manager"` 的 CompanionBridge，配置独立的 `application_key` 和 `vault_root`。通知网关设置 `SIM_BRIDGE_CONFIG=/srv/ziokt/sim-manager/bridge.json`，并沿用既有 `ZIOKT_PROJECT_ROOT`、`ZIOKT_PYTHON`、Web Push/Webhook 与 HTTPS 配置。

```json
{"target":"sim-manager","method":"sim.reminders.replace","params":{"user":"12345678-1234-1234-1234-123456789abc","items":[{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","due":1800000000000,"webhook":false}]}}
```

示例 `due` 应替换为实际到期毫秒时间。`user` 必须对应网关里已有账户 UUID。计划以 SafeFS 密文进入签名联邦记录，网关约每 30 秒拉取后交给真实提醒调度器。反向从 SIM 页面修改的计划先持久化，再通过应用桥重试发布；并发编辑不会被旧请求的成功回包删除。新的到期时间会重置已发送标志。浏览器权限、推送配置和手机系统设置仍决定最终送达；真实手机测试尚未执行。

## 公开“一键开始奋斗”网页

网页接入 **Corium Engine Zero**。外部设备点击后，以 Web Worker 计算原生 SHA-256 挑战；奖励/贡献记到服务端配置的 Corium 节点身份。该地址必须匹配本机原生签名身份，不能把另一身份填入后冒领。浏览器不接收私钥，也不能指定地址、脚本、引擎、难度、RPC 方法或待提交交易。

1. 启动配置好的 Corium 节点，确认本地已接受的区块链可读。
2. 在本机 Corium `[ziokt]` 配置中显式启用 `allow_mutations=TRUE`，允许 `compute.submit`，允许资源 `compute:corium/internal-engine-zero-v1`。保留原有其它允许项。联邦提供者需已启用。
3. 复制 [奋斗页配置](examples/effort-web.json)，填真实提供者、节点身份、来源和私有状态目录，设 `0600`。
4. 启动：

```sh
python3 -m ziokt effort-web --config /srv/ziokt/effort-web.json
```

默认在 `127.0.0.1:8081` 提供页面和两个固定 API。用已有 HTTPS 反向代理将配置的域名转发到该地址，保留精确 Host，禁用响应缓存并限制连接数。公网浏览器需要 HTTPS；不使用反向代理时，可设置公网监听地址以及 `certificate`、`private_key`，由程序直接提供 TLS。程序不修改防火墙、DNS、路由或系统服务。

页面只有一个开始/停止按钮，明确说明 CPU、电量和贡献归属。没有点击不会获取计算任务；停止、关闭页面或切到后台会终止 Worker。按批次休息，单任务 90 秒过期，nonce 范围有限。所有资源来自同一站点，无第三方脚本或遥测。

服务端重算证明，绑定链网络、当前接受区块和本机身份，然后通过 Corium 原生 `compute.submit` 提交。一个区块问题使用同一个持久化 operation ID；重复点击、回包丢失与进程重启由原生 journal 和本地回执协调。页面“证明已提交”表示等待原生共识，**不表示已经上链或已有收益**。区块验证者选择和证明挑战期沿用原生规则，网页不代替共识。请求与并发均有预算，来源核验阻止跨站调用；公网部署仍应在 TLS 入口设置容量限制。

AirGap 模式拒绝启动该网页或网络后端；离线代数、TC-16、加密存储和人工签名文件交换继续可用。

## 验证范围

本地不执行重量级原生编译。Python 回归使用临时状态和已有六核心产物；真实 Corium 提交测试仅在自有临时链上运行。ETP 原生构建在 CI 中进行，最小和集成配置均执行四进程多跳收发。浏览器测试实际计算 SHA-256，验证点击前不取任务及停止/后台终止。手机系统推送仍需目标设备验证；本机创世链、公开奋斗页和只读区块链浏览器已经部署，访问与服务信息记录在家目录 fendou.txt。

联合包收录当前成功 CI 的原生产物、ETP 网关、协调器 `.pyz` 与 SIM/Tri PWA；原生 Core 的复用来源和本次 Nim 重建结果分别记录在校验报告中。原生二进制针对 Linux x86_64，三平台通过的是可移植协调层测试。`MANIFEST.json` 为每个包内文件记录 SHA-256。源码与验证报告可用于复核，历史原始参考目录不作为部署入口。

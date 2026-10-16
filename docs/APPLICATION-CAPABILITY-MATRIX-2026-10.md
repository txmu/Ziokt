# 统一应用入口：实际能力与边界（2026-10）

盘点对象为 `ApplicationRouter`、`CompanionBridge`、
`companion_operations`、`component_links` 和对应测试。
统一请求 `{target, method, params}` 是控制入口；仅配置了目标、方法和私有
后端材料的调用才被允许。入口存在、状态查询成功，不等于组件全部功能已经运行。

## 逐组件实际可调能力

| 目标 | 当前实际后端及可调用能力 | 尚未接入同一路由或需单独运行的已有实现 |
|---|---|---|
| Shadow6 | `NativeClient`：状态、能力、对象清单、Broker `service.binding`；经明确授权的 prepare/commit 等事务调用原生 service.run/stop、package.install/activate、checkpoint/restore | Profile/Core 运行依赖原生部署和具体服务配置，不能从状态查询推断全部 Profile 已联调；S6EPE/Extensions 走原生机制，不是任意 Python 插件执行接口；当前该路由不接受 CompanionBridge 的 component.send/receive |
| Corium | `NativeClient`：状态/对象、内容获取、身份/治理事实、ZKT/ZKN/ZKC 查询、Engine Zero challenge；经事务授权调用内容发布、贡献提交、转赠/签发、链和恢复操作 | 具体链状态、确认、P2P 可用性需实际原生验证；统一入口不把论坛事件直接上链，也未将全部 Corium CLI 封装为通用任意命令；当前该目标不转发 component.send/receive |
| ETP | 固定摘要原生 `EtpGateway`：stats、显式 onion.send、receive、shutdown，以及 Forum identity/subscribe/publish/get（需运行支持这些方法的原生 gateway） | 不自动暴露全部 ETP 插件；本地发帖返回 stored_locally/best_effort，不是远端接收确认或链上确认；该目标不转发 CompanionBridge 的 component.send/receive |
| WATChat | CompanionBridge：chat.append/pull/ack，附件摘要及 file.publish/read，应用 Vault、可配置的定向组件交换 | 浏览器 ECDH/HKDF/AES-GCM、联系人授权、HTTP/WebSocket 后端、PWA/Web Push 仍由 WATChat 产品前后端执行；统一入口不自动启动或替代这些服务 |
| SafeFS | CompanionBridge：vault.put/get/publish、safefs.publish/read，应用密钥隔离，定向组件交换 | 主机挂载/内核隔离/物理擦除不是 Vault 的已执行能力；沙箱说明或计划不等于部署完成 |
| ZDA/Ano | CompanionBridge：ano.evaluate/laws/calculate/defence，版本化逻辑及精确数值，应用 Vault 和定向交换 | defence 的调用者证据不是密码学证明，不能代替签名/权限验证；符号证明与原始组件全部界面不通过这些方法自动获得 |
| UFS | CompanionBridge：应用 Vault、package.build/verify/publish、定向交换；使用既有 Ziokt 签名包格式 | 原生 UltraHandler HTTP/WebDAV 与 IntegratedSystem HTTP 包服务是独立可运行入口；统一路由未增加启动/管理这些监听器的方法，见 UFS 原生审计文档 |
| DCPM | CompanionBridge：从本应用 Vault 的文件构建签名包、验签/内容验证、加密发布与定向交换；无自动安装 | 原生 DCPM 的配置式发现、HTTP/P2P 传输、信任域和本机包管理器另行运行；不因签名包已发布而宣称已复制、安装或获链上确认；legacy ufsdcpm CLI 仍有独立兼容 scope，不能直接假定其旧密文等于 ufs/dcpm 新 scope |
| TC-16/TCC | CompanionBridge：tc16.run，明确 assembly/tcc 源码和 1..100000 指令预算，真实 Python 16 位 VM/编译器；Vault 与交换 | ETP Rust TC-16/TCC 是独立实现；统一入口不自动转换 ABI，不自动授予宿主文件/网络访问；接收程序不自动执行 |
| SIM Manager | CompanionBridge：sim.reminders.replace/pull，持久加密提醒快照、去重、应用 Vault/交换；另有实际通知网关的桥接调用 | IndexedDB/eSIM LPA、卡片/套餐/统计、PWA 与后台通知由产品及网关执行；统一接口没有镜像所有号码/PIN/PUK 数据，也不自动颁发运营商 Profile |
| Tri | CompanionBridge：tri.put/get/publish，真实项目封装/校验/加密存储与发布、定向交换 | 这些方法保存模拟器项目及状态，不运行完整浏览器三态模拟器、UI 或任意导入脚本；模拟引擎由 Tri 产品执行 |

CompanionBridge 的八个目标可以按应用范围配置通用 Vault 方法及
component.send/receive；组件专属计算/包/提醒方法另行检查目标。
Shadow6、Corium、ETP 三个目标当前直接分派到各自原生后端。
**110 对 ComponentLinks 测试直接构造交换对象，不是上述三个原生目标已经
实现统一路由交换适配的证据。** 两个原生 CLI 能调用同一个 router，也不等于
调用的数据自动经过其网络 Core；数据载体另由明确的网络/隐私配置决定。

## 本轮新增的真实工作流证据

`tests/test_application_workflow.py` 全程通过 ApplicationRouter 操作五个应用：

1. TC-16/TCC 实际执行 `65535 + 2`，验证 16 位结果为 1。
2. 使用其独立 Vault 和已钉住身份的组件交换，将执行结果交给 Tri；Tri
   生成包含结果的项目。
3. Tri 项目交给 SafeFS，实际加密发布；用 DCPM 的应用密钥打开 SafeFS 密文
   必须失败。再以定向封套交给 DCPM。
4. DCPM 构建并验证既有格式的签名包，签名发布后定向交给另一节点的 UFS。
5. 两个独立 Community SQLite/CAS 通过真实本地 mTLS、授权 grant 和检查点
   分块协议同步。接收节点不持有源 DCPM 的应用 Vault 密钥。
6. UFS 收件后验证 DCPM 发布者及内容，读取 Tri 项目，确认原计算结果；
   错发布者、错来源和未授予方法均拒绝。重复投递返回同一持久回执，
   不添加社区事件、不自动执行程序或安装包。

各应用有独立签名、邮箱和 Vault 密钥，交换必须满足显式对等方及 kind 授权。
本测试不是内存消息替身，也没有以固定成功结果代替传输或验签。

命令：

```
PYTHONPATH=tests:. .venv/bin/python -m unittest test_application_workflow -q
```

实际结果：**1 项通过，0 失败、0 跳过，1.194 秒**。

该测试覆盖受控本地 mTLS 工作流，未启动 Shadow6 Core、Corium 共识或 ETP
原生节点，不证明此工作流已通过全部匿名载体。它验证实际计算与认证数据流，
不为接收端创建远程计算证明、ZKT 贡献、ZKN/ZKC 发行或全局共识事实。
既有直接函数组合测试和 110 对交换测试仍保留，不将其覆盖范围扩大描述。

# 原生联邦实施与验收

保留 Shadow6 多模块/独立 Core、Corium 单生产文件和双方默认关闭。原生 main 未合并；
改造在各自 `ziokt/native-support` 分支，精确版本见 `native-sources.lock.json`。
本地不运行重量级编译；原生编译与发行物验收由 Ziokt 的 focused CI 执行。

| 阶段 | 已交付机制 | 验证证据 |
|---|---|---|
| P0 | 原生所有权、版本/限额、13 Profile 契约、开关、联合对象目录与故障边界 | source-contract 12 Core/13 Profile；目录含服务/包/应用、Wiki/Forum/Mail/模板、身份/Nomen、提案、Strata、快照 |
| P1 | S 独立模块和安装入口、C 单文件提前分流、严格配置/JSONL、独立可用 | S 原生 5 项、C 原生 6 项；复制 C 单文件仍能运行，关闭不创建联邦状态 |
| P2 | native prepare/commit/abort/status/reconcile、revision/lease、SQLite FULL intent、scope 幂等、outbox、持久化 Saga | 12 家族相同 stop 契约；真实 SIGKILL 在内容写入后留下 unknown，恢复后单一完成事件；签名包篡改拒绝 |
| P3 | 原 SDK 应用边界、C 原签名网关、C 原生发送函数绑定、同一 stream/message 协议、分片/重试/范围内容、多源 CAS | 12 Core/13 Profile 实际 broker/agent/client → C native PING/内容读取；私有帧预算 padding 同样通过 |
| P4 | 原生 S 验包与激活、C Wiki/快照/Strata 固定动作、依赖 lock、可审查工作空间、双 ownership proof、S 原 ShadowChat 引用 C 原 Wiki | 真正 C ACL 拒绝、交易创建/挖块、Wiki 投影、快照；原 S 聊天验签/解密/重放拒绝；原签名包安装/激活 |
| P5 | 方向 AES-GCM、原生 C 身份 pin、私有文件/DACL、无明文产品标记、private 固定帧 padding、禁止未批准回退、有限预算、签名加密联合恢复包、原生冷恢复 | 流/消息篡改与反射拒绝、背压、多源中断接续、密文/epoch/作用域拒绝；真正 Phoenix 销毁后冷恢复，S 材料重建且保持停止 |
| P6 | TLS1.3 mTLS、证书/Ed25519 grant 双绑定、持久 nonce/epoch、单权威领导任期、Provider fencing、每步治理事实复查、三平台协调器 CI、哈希固定 native 发行物 | 真正 mTLS 调原生 Provider 与重放拒绝；原生旧任期 commit 拒绝；C 原签名链事实/错误 workflow/引用消失拒绝 |

本表区分机制实现与部署保证。原生 Strata 引导仍须原项目 root/工具及运行预算；
超出固定前台执行预算时保留 unknown/原生审查，CI 不安装主机系统。restricted 连接
要求可核实匿名载体；当前缺少证据时明确拒绝。单权威 SQLite 任期不宣称跨机共识。
链观察是原生 signed inclusion，不能替代 C 原共识和最终性判断。元数据投影不证明
线上可用，恢复不复活旧 PID、就绪或运行授权。原生各平台与 Core 的能力限制保持真实。

## 本地验证

- 完整 Ziokt suite：39 项通过（一次 network gate 单独运行）；随后新增治理验收独立通过。
- 完整 native data gate：12 家族/13 Profile、26 个真实原生 PING/内容往返；private padding
  版本在本地预编译基线运行 139.720 秒。后续相同协议的细节由远端全 gate 复验。
- 协调器 zipapp 成功；未执行本地 Core 编译、宿主路由/防火墙/服务或全局依赖安装。

每次 native 代码更新同步 canonical spec 并锁定新 commit；最终 CI 链接与制品见
`docs/verification.json`。便携 CI 分别验证 Linux/macOS/Windows，原生 gate 在 Linux
编译 Ziokt-enabled Go/Rust/Control，并使用 SHA256 固定的成功上游产物验证全部 Profile。

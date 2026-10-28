# Ziokt 1.0 联邦验收准备 / Federation acceptance preparation

审计基线：`aadb00735c67fde06c10c40c4b91a93a7e7ce954`。本轮是针对性源码审计与低风险修复，不是所有组件的完整安全认证，也不是公网多节点验收。

## 已交付 / Delivered

| 修改与实际路径 | 验证 | 影响与回滚 |
|---|---|---|
| `gui/src/modules/chat.js`：删除本地模拟聊天、预置联系人、虚假握手及语音回执，改为显式原生 WATChat 入口。HTTPS 或 loopback HTTP；拒绝嵌入凭证、查询和片段；不转发网关 token。同步 `gateway/gui/modules/chat.js`、Android assets 与各自 `app.js`。 | `node tools/gui_browser_smoke.cjs`，真实 Chromium 页面、实际本地 Gateway / Community / 文件服务；检查无模拟消息、拒绝带凭证地址。 | 不改原生聊天协议、密钥或消息。用户需配置原生聊天 URL；旧本地缓存保留但不再作为消息使用。回退发布目录即可；回退会重新暴露旧版误导 UI，优先修复前进。 |
| `gui/src/modules/home.js` 及分发副本：删除固定的 UFS 挂载、Shadow6 在线和 WATChat 握手成功记录。 | 同一浏览器回归；无伪造握手记录。 | 未加载活动回执时明确显示未验证；不改变服务状态。回滚方式同上。 |
| `gui/src/i18n/{zh,en,zh-CN,en-US}.json`、`core.js` 及分发副本：算法说明改为 ECDH P-256 / HKDF-SHA256 / AES-256-GCM，棘轮及路由不再显示固定就绪。 | 原生证据：`companions/watchat/WATChat-code/frontend/app.js` 的 `messageKey`、`sealMessage`、`openMessage`。 | 算法描述是随附实现说明，不是运行时握手证据；远端自定义实现需独立核对。 |
| `.github/workflows/openci-alfs.yml`：checkpoint 测试加入轻量检查；测试文件修改也触发工作流。 | checkpoint / 配置测试及 `bash ci/openci/alfs/check_image.sh`。 | 未触发完整 LFS 编译，不改变构建权限。单独 revert 此文件可回滚。 |
| `tools/gui_browser_smoke.cjs`：扩展原有真实浏览器验收。 | Chromium 通过。 | 仅测试代码；未引入模拟投递。 |

已有打包文件与模块源存在差异。本轮分发文件只同步上述目标修改，保留其他已有代码；统一构建源与所有历史生成副本的一致性是后续事项。PWA shell 版本已更新，旧安装客户端仍需正常更新服务工作线程。

English: The GUI now hands chat off to native WATChat. It never claims login, key agreement, recording or delivery based on browser storage. The bundled native cipher is ECDH P-256 / HKDF-SHA256 / AES-256-GCM. Gateway authentication is separate from native chat authentication. No consensus, assets, production keys or native authorization rules were modified.

## CI 与本地证据 / CI and local evidence

- 最新已完成原生集成失败：[40593672990](https://github.com/txmu/Ziokt/actions/runs/40593672990)，`ci/package_native.py` 拒绝 `stale or uncommitted zipapp: ziokt.pyz`。下载缓存放在 checkout 内导致 dirty stamp；基线提交已将缓存移到 `$RUNNER_TEMP/ziokt-native-reuse`。本轮不重复实现，`tests/test_release_build_cleanliness.py` 验证缓存移出仍能检测真实源码变更。
- 前一提交 ALFS 检查 [40593829535](https://github.com/txmu/Ziokt/actions/runs/40593829535) 成功；基线含 `[skip ci]`，不能将其视为当前源码全量 CI 已通过。当前提交推送后不等待 CI 即部署。
- 44 项针对性 Python 测试通过：build cleanliness、ALFS checkpoint/config、Feeds、统一 Mail / Internet Mail / survival、package lifecycle、NAT reuse、TC-16 spec / legacy、frozen deployment。
- GUI HTTP 测试 1 项通过；Chromium 实际本地服务浏览器回归通过，覆盖分块上传独立校验、原生 Community 发布/重载、内存凭证和原生聊天入口。
- ALFS 实际 ext4 打包、权限、文件复制与 `e2fsck` 通过；未执行完整 LFS 编译或 QEMU 启动。
- 原始本机日志：`/home/admin/release-validation/federation-20261028/`。本地回归（包括原有单元测试）不代表公网连接或真实收件人投递证据。

## 现有实现与后续路线 / Inventory and roadmap

| 项目 | 已有实现、复用入口 | 尚未完成及验收边界 |
|---|---|---|
| P0 社交身份 | `ziokt/component_links.py` 已有显式 pinned identity / capability 的组件桥；应用自身保留身份。 | 这不是通用用户双向身份绑定。实现下面的可选 Social Federation 设计后才能宣称交付。 |
| P0 联系人 / Inbox | `ziokt/mail_accounts.py` 已有账户隔离、多 Internet 账户 inbox；原生 WATChat 自管联系人及指纹。 | 未实现所有通信系统的联系人映射、通知与跨应用私密搜索。不得复制聊天私钥到网关或以名字相同自动绑定。 |
| P0 聚合 | `ziokt/content_feeds.py` 已有 Library / Netnews / Community 的授权过滤 RSS、Atom、JSON Feed、OPML；`ziokt/library_index.py` 与原生论坛桥可复用。 | 尚未覆盖所有 Corium / ETP / Wiki / RSS 导入、统一去重与签名/版本/撤回索引；保留 unavailable_sources，不补造条目。 |
| P0 Mail | `ziokt/mail.py`、`mail_internet.py`、`mail_receipts.py`、`mail_accounts.py` 已有地址解析、外部账户桥、队列与回执能力，本轮相关回归通过。 | 外部 SMTP 接纳不等于收件人阅读；显示名称不等于已认证公钥。真实外部账号、跨节点往返、退信/撤回/MDN 仍需实测；本轮未发送外部邮件。 |
| P1 Packages / Hosting | `ziokt/community_native.py` 明确 materialize 返回 native_signature_verified=false；`ziokt/package_handoff.py` 保留 dCPM 与原生 Shadow6 双重信任；`package_lifecycle.py` 管理安装/恢复。 | 按内容哈希、发行者签名、计划提交、执行回执、应用健康分别采证。跨节点实际部署链路待验，不新增自动安装。 |
| P1 UFS / dCPM / Corium / OpenCI | 已有文件服务、原生 handoff 和工作流实现。 | 独立权限、ABI、签名门禁保持；构建到恢复的完整跨节点演练未完成。 |
| P1 RetroShare | 基线已有 `retroshare.py`、`retroshare_transport.py`、`retroshare_node.py`，显式 enabled / allowlist、64 KiB 单对象上限、128 项 spool 及 SHA1/SHA256/长度核对。 | `collect` 的 verified/delivered 是该 carrier 字节检查，不能当 Content Fabric manifest/Merkle 验证。能力协商、持久队列与副本调度完整联动、限额清理和失败回退仍待实现/实测；本轮不启用、不安装新依赖。 |
| P1 STUN / Shadow6 | `ziokt/nat.py` 已在实际 UDP socket 发现映射，要求显式 literal server 和 standard privacy；映射不作为可达性证明。 | 独立网络 ICE/打洞、同协议 core 认证、数据哈希、授权 relay 回退分别验证；不假定所有 Core 互通。本轮无公网地址探测。 |
| P2 UX | 复用 `gui/src/modules/ecosystem.js`、现有原生入口；此次修复聊天断点。 | 统一通知、联系人页和可选登录映射仍待实现；不建新聊天/论坛协议。 |
| P2 Tri / TC-16 | `ziokt/tri_isa.json`、`tc16_spec.py`、`tc16_legacy.py`；本轮 TC-16 spec / legacy 回归通过。 | 全语言 ISA/ABI 差分、导入权限与执行预算矩阵待扩展，不静默升级旧机器码。 |

## 可选 Social Federation 设计（未实现） / Proposed, not implemented

1. 默认关闭；由用户逐项选择 Corium / ETP / Community / WATChat / Content Fabric 身份绑定，匿名身份无需加入。只保存公钥引用和证明，不收集私钥，不产生跨应用执行权限。
2. 每条绑定使用版本化、域分离的 canonical statement：双方应用/网络/主体、公钥算法和指纹、作用域、随机挑战、期限、序号。双方各自在原生应用签署同一 statement；验证器适配原生算法，不能假设 WATChat ECDH 密钥能用于签名。先确认各应用的原生签名能力；无签名能力时报告 unsupported，不能伪造证明。
3. 任一方签名撤销即可停止使用绑定；保存撤销 tombstone，阻止旧序号或到期证明恢复关系。轮换需旧新密钥授权及对端重新确认。设备恢复依赖原生加密备份/事先授权恢复策略；不能由网关管理员重签冒充本人。离线撤销未知时不得据绑定提升权限。
4. 联系人/消息索引仅在用户授权设备构建；只聚合原生允许暴露的摘要。私密正文解密与搜索留在原生客户端；通知只含最小元数据。
5. 内容引用保留源、原生 ID、作者签名原文、ACL、版本及撤回状态。按 source + native ID + version 去重；内容哈希仅用于候选关联，不将不同作者/权限的条目合并。
6. 验收覆盖单边伪造、跨网络重放、过期/撤销、轮换冲突、恢复失窃、权限变更和离线设备；功能必须有独立关闭与索引删除路径。

## 部署、兼容与回滚 / Deployment and rollback

使用现有 `tools/deploy_frozen_services.py` 固化已提交源码、备份配置/数据库并切换 Gateway、MCP、TG、Content、OpenCI、Effort；失败自动恢复之前 service override 与 Caddy 配置。不重启共识，不改 `ziokt-main` / `ziokt-acceptance` 网络配置、生产密钥或资产语义。

本机部署回执：`/home/admin/.local/share/ziokt-production/config/frozen-deployment-receipt.json`；其中 backup 字段记录私有备份目录。发布后若需回退，使用同一工具、相同 settings，将 `--revision` 指定为前一已运行提交 `27e628a1cddf073544ecde943031ca6c03956d6c` 并 `--activate`；工具会另建备份并验证版本。此轮无数据库 schema 修改，不应盲目覆盖上线后新增数据。

可立即开始独立多节点验证，但不能把本报告作为验证已通过的证明。建议先固定本次源码包 SHA256，再在独立主机核对网络 ID / 节点身份、认证连接、双向消息及文件哈希、重启恢复、原生授权拒绝和回执状态。TG 服务 active 仅是进程状态，本轮不代表机器人对话送达。所有未完成项按上表保留，默认不启用新的社交绑定或 RetroShare 路由。

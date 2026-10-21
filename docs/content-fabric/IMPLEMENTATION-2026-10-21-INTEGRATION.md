# 全生态深化：本轮实施与证据

这是增量交付记录，完整原始要求仍保留在 ACCEPTANCE、WORK_ITEMS、REMAINING。
全量审计及统一逐条矩阵尚未完成，不能以本记录取代 37 章验收。
`all_requested_features_complete` 仍为 false。

## 实际修改

- `tools/package_webextensions.py`：三平台来源清单和统一 SHA256SUMS。
- `.github/workflows/webextensions-release.yml`：独立打包测试、Artifacts、标签触发的未签名预发布。
- `tests/test_webextensions.py`：来源和所有安装包摘要覆盖测试。
- `docs/webextensions/README.md`：下载名称、校验与发布方式。
- `ziokt/content_fabric.py`：迁移 10、账户隔离的持久阅读标记、乐观版本和额度。
- `ziokt/content_api.py`：共享 HTTP/MCP 阅读状态操作及严格类型/版本边界。
- `tests/test_content_readstate.py`、`tests/test_content_mcp.py`：持久化、最终权限、重试、冲突、MCP scope 与幂等。
- `docs/MCP_TOOL_CATALOG.json`：从实际配置/注册表重新生成。
- `docs/content-fabric/NNTP-CLIENTS.md`：阅读标记接口、迁移及兼容边界。

## 本轮能力与原生互通

|范围|本轮结果|仍未证明|
|---|---|---|
|阅读状态后端|A：实际 SQLite 重启、独立账户、权限拒绝和 MCP 调用测试|GUI、NNTP 客户端本地标记同步、跨节点冲突 UI|
|扩展打包|A：三平台确定性与完整摘要验证|商店签名、Thunderbird/Android 真机|
|扩展 Release CI|B：代码与发布标签已提交，运行 39683060733 排队|真实运行通过及附件上传|
|Corium/Shadow6 协议副本|本轮生成器 check 通过，本地 HEAD 与锁文件一致|完整业务及远端恢复|
|ETP、UFS、dCPM、ZDNS/NNS|本轮未修改原生协议|继续按既有 WORK_ITEMS 逐项验收|
|Library、Netnews 全业务|只新增上述阅读标记|完整业务矩阵见 WORK_ITEMS，不升格整体状态|

Corium 锁定 `ec8fbea1d0bf54fe9bf403d7821859d37ad086b8`，
Shadow6 锁定 `92d3bf115bd569662803a9d86c965dd5d90dbfe1`。
检查不运行原生构建或生产进程。

## MCP 与 TG

新增 `netnews_readstate_get`、`netnews_readstate_update`；没有弃用工具。
分别需要 `netnews:read` 和 `netnews:write`，调用账户由已认证传输映射，
拒绝 caller-supplied owner。每次重新检查文章最终权限与墓碑。
写操作继续使用已有 MCP 幂等日志，底层 revision 拒绝旧离线状态静默覆盖。
目录由实际 Service 导出为 450 项，旧目录 363 项；差额并非全部本轮新增。
TG 的 `/tools`、`/help TOOL`、`/mcp TOOL JSON` 使用同一个 Service 注册表，
写入继续需要确认；本轮未发送 Telegram 消息，也未重启生产 TG。

## 验证与 CI

本地只运行受影响轻量测试：扩展 3 项、阅读状态 2 项、Content MCP 3 项，全部通过。
另执行 `tools/sync_providers.py --check`，通过。
不运行 ETP 等重量级构建，不重复已有完整浏览器和原生验收。

扩展发布提交 `73717b7fb98dc0b891e3190b4d03523e1d2013e7`，
标签 `extensions-v2026.10.21-dev.73717b7`，
[实际发布运行](https://github.com/txmu/Ziokt/actions/runs/39683060733) 排队；
排队不计通过，不提供尚未存在的附件下载链接。
下载入口为 [Releases](https://github.com/txmu/Ziokt/releases)。
包名固定为 `ziokt-companion-chromium.zip`、`ziokt-companion-firefox.xpi`、
`ziokt-companion-thunderbird.xpi`。Firefox XPI 为临时开发安装用途，
不能称为正式版 Firefox 永久安装包。

已查询基线 `bbf0f81d8d01c18086a2c3ccf4c5736c34b60e48`：
Content 39620396719、Gateway 39620396820、隐私 39620396814、
互操作 39620396974 成功；联邦 39620396859、Companion 39620396716 失败。
失败原因尚未审查，不将这些运行计为全生态通过。

## 部署、隐私与未满足条件

本轮未升级公共 Reader/NNTP 或变更证书/密钥/生产配置。
升级阅读标记后端前备份整个 Content root；新增表保留原数据，降级保留新表。
阅读标记是本地私有数据库数据，不是字段加密，也不进入公共联邦日志。

Tor/I2P/Peer、ZKN v2 和屏蔽所有权本轮没有新增安全证明；既有协议边界继续有效。
主网 OpenCI、PoW、匿名所有权均未因本次发布激活。
独立密码学审计、治理批准、多节点共识升级/回放和真实设备验收仍是具体外部条件。
本轮不是最终源码/原生二进制全量包，不宣称 package_all 已完成。

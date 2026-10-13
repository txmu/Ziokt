# Working State

## 2026-10-13 Actions 修复与隐私路由

修复最新运行的源码锁漂移、Windows 测试路径及 NAT 地址更换后的默认路由丢失。新增显式洋葱 SOCKS 多跳、无 Tor／I2P 的用户轻量代理和两到四跳 mTLS、候选路径实际连接、v2 rendezvous 加密长度填充、禁用脚本的站点沙箱及匿名导出元数据脱敏。功能、配置、升级要求及隐私局限见 [隐私路由与多跳](privacy-routing.zh-CN.md)。以下历史条目不代表本次修改已通过远端 Actions。

## ZKT 信誉与贡献积分机制（Reputation & Credit Scoring）已就绪

- **核心定位**：ZKT 严格定义为非代币的信誉与贡献积分体系，不含任何发币、固定总量、转账交易或资产模型。
- **获取规则自由配置**：通过 `ziokt.zkt-reputation-policy.v1` 声明式配置获取规则，支持 Shadow6 急需 Core 权重加成（默认 3x 激励）及 Corium 应用服务（Wiki、快照、Strata、恢复等）基准积分。
- **服务证据与防重放**：支持记录真实服务凭证，按 `evidence_digest` 与 `(epoch, nonce)` 双重抑制重复计分与重放攻击。
- **查询与 RPC 支持**：原生提供 `zkt.status` 与 `zkt.account` 查询能力，支持按节点地址查询总信誉分、各端贡献构成及信誉等级（Contributor / Reliable Provider / Core Guardian / Federation Pillar）。
- **跨平台与 CI 验证**：
  - `portable (windows-latest)`: ✅ 通过（基于 Win32 `GetFinalPathNameByHandleW` 修复路径与文件句柄一致性检查）
  - `portable (ubuntu-24.04)`: ✅ 通过
  - `portable (macos-latest)`: ✅ 通过
  - `native-integration`: ✅ 通过（修复 Idris Chez Scheme 解释器 ABI 兼容性与 libsodium FFI 动态库路径，46项测试全绿）

## 隐私与匿名机制增强（Privacy & Anonymity Enhancements）已就绪

- **秘密投票与承诺凭证（Secret Ballots）**：支持治理投票盲化承诺 `ballot_commitment`、无偏验证 `verify_ballot` 以及使用计票权威 X25519 信箱定长加密加密选票 `seal_ballot` / `open_ballot`，解决公开计票中的选票明文暴露问题。
- **情境假名令牌（Pseudonym Tokens）**：提供基于 HKDF 域分离的不可关联假名派生 `pseudonym_token`，在不同主题或反馈情境下保护用户长期公钥身份不被交叉关联。
- **批准路径模式路由仲裁（Approved Paths Routing）**：在 `routes.py` 中补充并激活 `approved-paths` 模式验证，根据社区隐私配置（如 `restricted` 强制洋葱载体、禁用直连回退）动态调用 `select_path` 仲裁合规候选路径。
- **本地材料清除（Purge）**：`RegistrationGate.purge` 与 CLI/API 删除本地暂存密文和登记索引，拒绝符号链接；不保证存储设备、备份或链上承诺的物理擦除。
- **静态网站发布作者脱敏（Anonymous Site Publishing）**：为 `build_site` 与 `publish_site` 提供 `anonymous=True` 选项与 CLI `--anonymous` 标志，将文章作者统一遮蔽为“匿名成员”并截断标识，防止静态发布泄露社区全员公钥图谱。
- **门户安全与私信可用性修复**：修复社区 UI 门户 `registration_state` 调用作用域，向 `/api/status` 暴露 `carrier_required` 标志，支持私信发送自动生成安全随机消息键。


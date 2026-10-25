# Ziokt

Ziokt 是面向自治节点的分布式应用与协作平台。它以 Corium 的链、治理与可验证贡献，以及 Shadow6 的独立原生传输为基础，提供自己的节点管理、Content Fabric、Library/Netnews、OpenCI、dCPM/UFS 交付、身份与命名、Gateway/MCP 和跨平台客户端。

节点、内容、构建、分发与恢复通过明确的权限和证据关联；各组件保留独立部署与自治能力。Shadow6 保留多模块和独立 Native Core；Corium 的主要生产入口为 `corix_v108.sh`。双方默认关闭 Ziokt，无需安装本仓库即可独立使用。

v1.0 的审计修复、形式化对应范围、跨组件与故障验收入口见 [v1.0 发布验证说明](docs/V1.0-ASSURANCE.zh-CN.md)。公开交付仍使用 **v1.0**；内部 Python、桌面及移动工程版本统一为 `1.0.0`。精确提交的 CI 结果和产物摘要随 [Ziokt-Releases](https://github.com/txmu/Ziokt-Releases/releases/tag/v1.0) 发布，不能用某个模块通过替代系统验收。

节点可通过 `excluded_nodes` 排除名单拒绝指定节点的入站、出站和发现选路；多个节点使用同一名单即可联合排除。配置和解除方式见 [隐私路由与节点排除](docs/privacy-routing.zh-CN.md)。

已实现原生双向接入、持久化操作/Saga、12 Core/13 Profile 共用的数据协议、内容/签名包、工作空间、身份与治理校验、冷恢复、隐私 profile、mTLS 和任期隔离。原生能力和权限保持各自所有权；目录投影表示存储元数据，在线与应用完成须有各自原生证据。

```sh
python3 -m ziokt --help
python3 tools/sync_providers.py --check
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

测试默认使用相邻的 `../Shadow6` 与 `../Corium`；可通过 `ZIOKT_SHADOW6_ROOT`、`ZIOKT_CORIUM_ROOT` 指定源码位置。测试只使用临时状态目录，不启用真实部署。

## 2026-10-18 互通与双界面工程批次

新增作用域分块对象、签名引用包、DCPM→Shadow6双签名交接、WATChat双界面与密文附件重试，并修正无原生证据的门户状态显示。本批未完成全部跨节点服务部署验收；浏览器和大型CI尚待执行。接口、验证、迁移和剩余边界见 [交付记录](docs/INTEROPERABILITY-DELIVERY-2026-10-18.zh-CN.md)，逐组件证据见 [互通矩阵](docs/INTEROPERABILITY-AUDIT-2026-10-18.zh-CN.md)。

## 私有社区与节点恢复

`python3 -m ziokt community --help` 提供签名论坛/聊天/Wiki、加密文件和软件材料、收件人私信、身份与命名、治理记录、原生工作流回执、加密副本及冷恢复。本地浏览器门户可连接明确配置的 mTLS 对端；restricted 网络同步只使用显式 Tor v3 SOCKS5 路径，失败不直连。社区状态可在联邦协调器离线时继续使用，并保留并发编辑和原作者签名。

初始化不启动网络：`python3 -m ziokt community init --root /absolute/village --name village`。部署、成员权限、独立恢复密钥、保密性换钥、真实网络条件、默认预算和各应用成熟度见 [社区操作指南](docs/community.zh-CN.md)。

支持最多三个显式洋葱 SOCKS5 中间节点；无 Tor／I2P 时，可显式开启用户轻量代理并使用两到四跳 mTLS 隧道，代理无需社区内容解密密钥。另提供实际候选路径选择、加密长度填充的 rendezvous 和门户站点沙箱。配置、兼容性及隐私边界见 [隐私路由与多跳](docs/privacy-routing.zh-CN.md)。

## 本地配置

Shadow6 使用自己的 `~/.config/shadow6/ziokt.json` 或 `shadow6 ziokt --config FILE`。配置需为当前用户所有、非符号链接、模式 `0600`：

```json
{"schema":"ziokt.provider.v1","enabled":true,"federation_id":"home","provider_id":"shadow6-local","allow_mutations":false}
```

Corium 在所选 `CORIUM_ROOT/etc/corix/networks/NETWORK/corix.conf` 中加入以下段落，同样使用 `0600`：

```ini
[ziokt]
enabled = TRUE
federation_id = home
provider_id = corium-local
allow_mutations = FALSE
```

`corix ziokt --network NETWORK capabilities` 在原生建锁目录、恢复和交互解析之前分流。单独复制 Corium 生产文件也可使用此入口，无需外部 Python 模块。正常原生入口和 sourced API 保持既有行为。

Ziokt 自己的配置由以下命令创建，默认关闭；命令不修改双方配置，也不覆盖既有文件：

```sh
python3 -m ziokt init \
  --shadow6 /absolute/Shadow6 --corium /absolute/Corium \
  --shadow6-config /absolute/shadow6-ziokt.json \
  --corium-state-root /absolute/corium-state \
  --federation home --network default --output federation.json
```

在双方显式启用、标识一致后，编辑 `federation.json` 的 `enabled` 为 `true`，运行：

```sh
python3 -m ziokt doctor --config federation.json
python3 -m ziokt capabilities --config federation.json
python3 -m ziokt inventory --config federation.json
```

Ziokt 仅启动固定原生入口，验证配置中固定的源文件摘要，并执行私有副本；未允许任意 argv、Shell、函数或 SQL。源码更新后须人工审查并刷新摘要。协调调用采用有界管道线程，不依赖 `/dev/fd` 或 POSIX selector；原生运行前提仍按双方实际平台契约检查。

协议使用单请求 JSONL + EOF、严格有界 JSON、精确 schema/作用域、短 deadline 和相关 ID。分页绑定整个快照摘要，原生状态变更后拒绝旧游标。远端入口另用 TLS 1.3 双向证书和 Ed25519 作用域 grant，持久化 nonce/epoch；本地协议不能直接作为远端授权。写操作还须各自原生动作/资源策略。

## 实现与验收

详细架构见 [架构设计](docs/architecture.zh-CN.md)；分阶段实现和验证见 [实施记录](docs/implementation-status.zh-CN.md)；可审查的配置与使用步骤见 [操作指南](docs/operations.zh-CN.md)；非代币信誉与贡献积分机制见 [ZKT 信誉积分设计](docs/zkt-reputation.zh-CN.md)。


## 材料承诺登记与 ZKN 区块资产

社区可以在签名策略中启用材料登记。登记策略是一个 JSON 对象，字段为 `required`、`provider_id`、`issuer`、`admin_public`、`admin_mailbox`。其中 `admin_mailbox` 使用社区初始化时输出的信箱公钥；`issuer` 和 `provider_id` 必须对应已启用的 Corium provider。管理员用 `community policy --registration registration.json` 签发新策略后，启动门户时传入 `community ui --registration-config federation.json`。门户会要求成员上传 64 KiB 以内的 UTF-8 文本文件，并等待承诺交易获得区块确认后开放社区操作。文件以收件人信箱加密后保存在门户状态目录，链上登记文件承诺、成员、策略和签发者。

启用 Corium 配置中的 `zkn_enabled = TRUE` 后，每个本节点打包的区块会生成签名快照并自动提交 ZKN 铸造交易。快照清单包含区块摘要、高度、打包者、打包时间、打包内容摘要与大小，以及打包者当时的 ZKT 积分；快照内容包括该区块内交易的文本和二进制负载。完整快照作为按摘要寻址的本地对象保存，NFT 清单上链。NFT 可由当前持有者通过 `zkn.transfer` 转赠，链上 nonce 防止旧持有者重复转让。

## Unified companions / 十部件集成

The new [ecosystem guide](docs/ECOSYSTEM.md) covers private ZKN/ZKC, six-core signed Extensions, joint native node profiles, SafeFS, typed Ano/ZDA, UFS/DCPM, TC-16/TCC, ETP and Android PWAs. [Verification record](docs/verification-current.json) separates checked behavior from deployment prerequisites. Use `python3 -m ziokt companion catalog` for the source inventory.


## Content Fabric、Library 与 Netnews（可选）

新增独立持久化内容应用、主 GUI 导航、MCP 工具、授权 Community Forum API、
NNTP 读取/投稿入口，以及 TC-16 显式 ISA/ABI 包装和可选 Mailbox 复制实现。
启动、权限、迁移、协议限制及实际验证边界见
[工程入口](docs/content-fabric/README.md)；全量任务进度见
[交付清单](docs/content-fabric/WORK_ITEMS.md)。未验证的原生集成和未完成业务桥接
不作为已经交付的能力。

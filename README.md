# Ziokt

Shadow6 与 Corium 的自治联邦。Shadow6 保留多模块和独立 Native Core；Corium 的生产支持全部内嵌于 `corix_v108.sh`。两者默认关闭 Ziokt，无需安装本仓库即可独立使用。

已实现原生双向接入、持久化操作/Saga、12 Core/13 Profile 共用的数据协议、内容/签名包、工作空间、身份与治理校验、冷恢复、隐私 profile、mTLS 和任期隔离。原生能力和权限保持各自所有权；目录投影表示存储元数据，在线与应用完成须有各自原生证据。

```sh
python3 -m ziokt --help
python3 tools/sync_providers.py --check
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

测试默认使用相邻的 `../Shadow6` 与 `../Corium`；可通过 `ZIOKT_SHADOW6_ROOT`、`ZIOKT_CORIUM_ROOT` 指定源码位置。测试只使用临时状态目录，不启用真实部署。

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


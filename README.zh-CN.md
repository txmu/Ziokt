# Ziokt

[English](README.md) · [中文文档](docs/README.zh-CN.md) · [v1.0 下载](https://github.com/txmu/Ziokt-Releases/releases/tag/v1.0)

Ziokt 是面向自治节点的分布式应用与协作平台。它将内容、私有社区、可验证构建、软件交付、命名与节点运维组织成自己的应用系统。Corium 提供原生链与治理服务，Shadow6 提供可独立部署的原生传输；三者各自保有权限和部署能力。

## 一个节点提供什么

| 领域 | 组件 | 实际职责 |
| --- | --- | --- |
| 应用 | Community、Library、Netnews、浏览器阅读器、站点与聊天 | 持久化应用状态，明确成员权限与发布策略 |
| 构建和交付 | OpenCI、Content Fabric、dCPM/UFS | 源码承诺、隔离 Worker、签名回执、验包与独立激活 |
| 访问 | Gateway、节点 ZDNS、MCP、桌面/移动/PWA 客户端 | 通过作用域接口使用真实配置的服务 |
| 原生基础 | Corium、Shadow6、带类型的 companion 边界 | 权限与传输能力由各自原生项目最终执行 |
| 运维 | 独立身份、恢复、节点排除 | 显式组网、可审查证据、有界故障处理 |

对象已保存、进程在运行、区块已接纳、应用操作已完成，分别需要各自的证据。

## 使用预构建产物建节点

先按 [VPS 完整教程](https://github.com/txmu/Ziokt-Releases/blob/main/VPS_BOOTSTRAP.zh-CN.md) 安装运行依赖并选择网络，再运行：

```sh
curl --proto '=https' --tlsv1.2 -fsSL https://raw.githubusercontent.com/txmu/Ziokt-Releases/main/install.sh | sudo sh -s -- --root /opt/ziokt-node bootstrap --install --runtime --yes --enable-services --connectivity public --network ziokt-acceptance --service-prefix ziokt-acceptance
```

命令安装经校验的 CI 产物并创建新的独立验收网络。加入已有网络还需要公开创世、种子端点与公开 TLS 证书，并独立核对摘要。每个节点生成自己的密钥。引导后共识保持暂停，完成历史验证后再按网络治理启用；管理接口默认只监听本机。

## 从源码开始

使用 Python 3.11+，在独立环境中安装固定依赖：

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m ziokt --help
.venv/bin/python tools/sync_providers.py --check
```

原生集成使用相邻的 `../Corium`、`../Shadow6`，也可按 [入门指南](docs/guide/getting-started.zh-CN.md) 显式指定根目录。CI 的运行源码由 `native-sources.lock.json` 固定。重量级编译交给 CI；三联合源码 ZIP 是纯 UTF-8 文本交换包，不含可直接运行的原生二进制。

## 阅读路径

- [入门](docs/guide/getting-started.zh-CN.md)：安装、源码布局与首次只读检查。
- [架构](docs/guide/architecture.zh-CN.md)：应用归属及跨组件数据流。
- [运维](docs/guide/operations.zh-CN.md)：配置、对端、节点排除与恢复。
- [安全与隐私](docs/guide/security.zh-CN.md)：信任边界、匿名路由与发布范围。
- [验证与发布](docs/guide/verification.zh-CN.md)：Lean 对应、CI 证据与验收边界。
- [全部文档目录](docs/REFERENCE.zh-CN.md)：各组件手册和历史记录。

## 验证承诺的范围

生态发行版保持 **v1.0**，Ziokt 应用工程版本为 `1.0.0`。Lean 模型与生成的生产判断补充既有 Ada/SPARK 和 Idris 契约；它们没有证明全部实现、依赖、FFI 和操作系统行为。精确版本、验证结果与剩余边界随发布证据提供，同机多进程 CI 不代替多台物理 VPS 验收。

[Corium](https://github.com/txmu/Corium) · [Shadow6](https://github.com/txmu/Shadow6) · [发布与部署工具](https://github.com/txmu/Ziokt-Releases)

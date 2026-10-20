# Ziokt & Corium 生态网关全景架构、指令技术方案与大分块传输三大优化规范

> **文档创建时间**：2026-10-17  
> **文档位置**：`/home/admin/ZIOKT_GATEWAY_ARCHITECTURE_AND_ROADMAP.md`  
> **适用范围**：Ziokt 生产联邦网络、Corium 去中心化网关、Shadow6 原生集成、ETP 洋葱中继与 UFS/DCPM 存储系统

> **2026-10-18 实施更新**：真实 GUI 适配器与 MCP 目录已同步，当前部署 340 工具；Web 入口为 https://app.ziokt.com/ ，实际 CI 构建的安装包见 https://app.ziokt.com/downloads/ 。v2 引用包已贯通独立原生签名验证、所有者准入和原生安装/激活验收。测试依据见 `DELIVERY_VERIFICATION_2026-10-18.json`，操作见 `GUI_USER_MANUAL.md` 与 `MCP_中文使用说明.md`。链上所有权屏蔽、HarmonyOS 已签名 HAP 和真实手机硬件验收仍未完成，不能用 UI 或包装工程冒充这些能力。

---

## 目录
1. [网关系统全景资产与物理部署拓扑（各部件在哪里）](#1-网关系统全景资产与物理部署拓扑各部件在哪里)
   - [1.1 核心源码工程与仓库目录](#11-核心源码工程与仓库目录)
   - [1.2 生产环境运行时与目录架构](#12-生产环境运行时与目录架构)
   - [1.3 核心持久化数据库与 P2P 对象库](#13-核心持久化数据库与-p2p-对象库)
   - [1.4 Systemd 生产常驻服务与配置体系](#14-systemd-生产常驻服务与配置体系)
   - [1.5 域名、证书与公网入口映射关系](#15-域名证书与公网入口映射关系)
   - [1.6 归档打包产物（家目录下）](#16-归档打包产物家目录下)
2. [用户核心指令深度梳理与技术实施方案](#2-用户核心指令深度梳理与技术实施方案)
   - [2.1 指令一：网关部署体系原生化（直接合入源码作为默认网关）](#21-指令一网关部署体系原生化直接合入源码作为默认网关)
   - [2.2 指令二：创世节点与交互操作鉴权控制（防冒用且默认只读公开）](#22-指令二创世节点与交互操作鉴权控制防冒用且默认只读公开)
   - [2.3 指令三：全系统与前端高扩展性国际化（i18n）架构设计](#23-指令三全系统与前端高扩展性国际化i18n架构设计)
3. [ETP FileShare 与 DHT 对象存储大分块流式传输“三大优化”全景设计](#3-etp-fileshare-与-dht-对象存储大分块流式传输三大优化全景设计)
   - [3.1 现状技术剖析与瓶颈诊断](#31-现状技术剖析与瓶颈诊断)
   - [3.2 优化一：自适应动态大分块（Adaptive Content-Defined Chunking, CDC）](#32-优化一自适应动态大分块adaptive-content-defined-chunking-cdc)
   - [3.3 优化二：Swarm 多源并发换块管道与滑动窗口调度（Swarm Concurrent Pipelining）](#33-优化二swarm-多源并发换块管道与滑动窗口调度swarm-concurrent-pipelining)
   - [3.4 优化三：网关零落盘流式直通（Zero-Copy Direct Streaming & HTTP Range 支持）](#34-优化三网关零落盘流式直通zero-copy-direct-streaming--http-range-支持)
   - [3.5 演进对比矩阵与实施路线图](#35-演进对比矩阵与实施路线图)
4. [一键打包发布方法与自动化脚本规范](#4-一键打包发布方法与自动化脚本规范)
   - [4.1 源码纯文本交换归档包打包方法 (Source Package)](#41-源码纯文本交换归档包打包方法-source-package)
   - [4.2 生产部署目录归档包打包方法 (Deployment Package)](#42-生产部署目录归档包打包方法-deployment-package)
   - [4.3 一键打包整合脚本 (`package_all.sh`) 现成代码](#43-一键打包整合脚本-package_allsh-现成代码)
5. [总结与快速索引](#5-总结与快速索引)

---

## 1. 网关系统全景资产与物理部署拓扑（各部件在哪里）

本生产系统由 **Ziokt 联邦协调层**、**Corium 去中心化网络底层**、**Shadow6 原生套件**、**ETP 洋葱网关** 与 **UFS/DCPM 安全存储层** 协同组成。各部件在主机上的具体物理路径与角色定义如下：

### 1.1 核心源码工程与仓库目录

| 模块名称 | 物理路径 | 分支 / 状态 | 职责说明 |
| :--- | :--- | :--- | :--- |
| **Corium 核心** | `/home/admin/Corium/` | `ziokt/native-support` (commit `c993677`) | 核心脚本为 `corix_v108.sh`（4.7万行Bash/Python混合）。负责区块链共识、P2P路由、DHT对象寻址、NNS域名解析、RestrictedPython/bwrap沙箱。 |
| **Ziokt 联邦框架** | `/home/admin/Ziokt/` | `main` (commit `f7b5554`) | 联邦核心路由、协议校验（`ziokt/config.py`）、应用路由器（`ziokt/application_router.py`）、组件交互总线（`ziokt/component_links.py`）。 |
| **Shadow6 套件** | `/home/admin/Shadow6/` | `ziokt/native-support` | 多语言密码学套件、CLI入口（`CLI/shadow6.py`）、离线检查与归档工具（`Tools/archive_preflight.py`）。 |
| **UFS / DCPM** | `/home/admin/Ziokt/companions/ufsdcpm/` | 子模块源码 | `src/dcpm_ufs_integration.py`，负责双重加密卷（诱饵卷/隐藏密室卷）、DCPM 签名软件包存储与 HTTP 存储服务。 |
| **ETP Companion** | `/home/admin/Ziokt/companions/etp/` | 子模块源码 | ETP 洋葱中继协议、Sphinx 分层加密路由规范、Noise-IK4 握手逻辑。 |
| **DApp 前端源码** | `/home/admin/explorer_dapp.py` | 独立源码 (生成脚本 `make_dapp.py`) | 统一 DApp 门户，直接注入沙箱执行。包含 Forum、FileShare、Onion、ZDA、SafeFS、UFS/DCPM、TC-16、Blockchain 等全量功能模块。 |
| **静态门户源码** | `/home/admin/static_status_site/index.html` | 独立源码 | 纯去中心化 Web 静态门户，发布于 NNS 域名 `status` 与 `corium`，作为网关首页。 |

### 1.2 生产环境运行时与目录架构

生产运行时环境高度隔离，集中托管于 `/home/admin/.local/share/ziokt-production/`：

```
/home/admin/.local/share/ziokt-production/
├── bin/                                # 生产可执行二进制
│   ├── caddy                           # Caddy 生产 Web 服务器 (v2)
│   ├── corix_v108.sh                   # Corium 生产入口（带执行权限，严格哈希绑定）
│   └── node24                          # Node.js 24 运行时（供 WATChat / SimManager 使用）
├── config/                             # 生产配置中心（所有敏感配置文件均为 chmod 600）
│   ├── Caddyfile                       # 全局反向代理、TLS 证书与域名路由配置
│   ├── federation.json                 # 生产联邦配置（登记 corium-production 与 shadow6-production）
│   ├── shadow6-production.json         # Shadow6 Provider 本地特权凭证
│   ├── effort-web.json                 # Effort 算力前端绑定
│   ├── node-public.json                # 节点公开元数据声明
│   ├── ziokt-*.service                 # Systemd 服务单元定义副本
│   └── runtime-digests.json            # 生产二进制哈希基线
├── corium/                             # Corium 数据与运行时状态根目录
│   ├── etc/corix/networks/ziokt-main/  # 网络拓扑与节点配置文件 (corix.conf)
│   ├── var/lib/corix/                  # 核心数据持久化目录
│   │   ├── dapp_cache/                 # DApp 沙箱解压执行缓存
│   │   ├── networks/ziokt-main/        # 链上数据、区块、NNS、论坛
│   │   └── p2p/                        # P2P 节点与 DHT 分块对象库
│   └── run/                            # 运行时 UNIX 域套接字与 PID 锁
├── apps/                               # 独立 Web 应用与前端资产
│   ├── sim-manager/                    # SimManager 前端静态资源
│   ├── tri/                            # Tri 离线 PWA 静态资源
│   └── watchat/                        # WATChat 聊天室 Web 资产与后端代码
├── logs/                               # 生产日志归档目录
└── watchat/                            # WATChat 本地加密 Vault 与会话存储
```

### 1.3 核心持久化数据库与 P2P 对象库

所有生产交互数据均已消除临时模拟文件，完全统一至原生 SQLite 与内容寻址库中：

1. **论坛与 NNS 域名数据库**：  
   `~/.local/share/ziokt-production/corium/var/lib/corix/networks/ziokt-main/forum/forum.db`  
   - `topics` 表：存储经过 Ed25519 签名的话题条目（ID、Title、Author、Timestamp、Content Hash）。
   - `posts` 表：存储各话题下的回复条目（ID、Topic ID、Author、Timestamp、Content Hash）。
   - `nns_records` 表：维护全网 NNS 域名映射（如 `status`, `corium`, `explorer`, `forum`, `ufsdcpm` 映射至 DHT 根清单哈希）。
2. **区块链账本数据库**：  
   `~/.local/share/ziokt-production/corium/var/lib/corix/networks/ziokt-main/chain/chain.db`  
   - 存储全局区块（`blocks` 表）与广播交易信标（`transactions` 表）。
3. **P2P 与 DHT 切片索引数据库**：  
   `~/.local/share/ziokt-production/corium/var/lib/corix/p2p/dht.db`  
   - `local_chunks` 表：维护 SHA-256 哈希到物理对象文件偏移量与大小的映射。
   - `nodes` 表：维护已知 P2P 邻居节点列表与信誉分层。
4. **内容寻址物理对象存储目录**：  
   - P2P 通用对象库：`~/.local/share/ziokt-production/corium/var/lib/corix/p2p/objects/<sha256_hash>`  
   - 论坛专属对象库：`~/.local/share/ziokt-production/corium/var/lib/corix/networks/ziokt-main/forum/objects/<sha256_hash>`
5. **UFS / DCPM 存储配置与根路径**：  
   - 配置文件：`~/.config/dcpm-ufs/config.json`  
   - 存储根路径：`~/.config/dcpm-ufs/ufs-storage/`  
   - 缓存路径：`~/.config/dcpm-ufs/dcpm-cache/`

### 1.4 Systemd 生产常驻服务与配置体系

系统通过 8 个 Systemd 服务单元实现高可用守护，所有单元文件均部署于 `/etc/systemd/system/`：

| 服务名称 | 进程命令 / 入口 | 内部端口 | 说明 |
| :--- | :--- | :--- | :--- |
| **`ziokt-corium-p2p.service`** | `corix_v108.sh daemon start` | `8080` (HTTP), `8234`/`9234` (P2P) | Corium 网关与 P2P 守护主进程，托管 DApp 沙箱与 NNS 解析 |
| **`ziokt-corium-consensus.service`** | `corix_v108.sh consensus worker` | 内部 | 链上共识与 PoUW 有意义算力出块进程 |
| **`ziokt-corium-relayer.service`** | `corix_v108.sh relayer worker` | 内部 | 跨链中继与 IBC 数据同步通道 |
| **`ziokt-https.service`** | `/.../bin/caddy run --config Caddyfile` | `80`, `443` | Caddy 边界反向代理，管理 Let's Encrypt / ZeroSSL 证书 |
| **`ziokt-ufs.service`** | `python3 dcpm_ufs_integration.py system start` | `8184` | UFS / DCPM 双重卷与软件包存储 HTTP 网关（带 Digest 鉴权） |
| **`ziokt-watchat.service`** | `node24 .../apps/watchat/backend/server.js` | `8182` | WATChat 端到端密聊信令服务 |
| **`ziokt-sim-manager.service`** | `node24 .../apps/watchat/backend/server.js` | `8183` | SimManager 仿真状态控制服务 |
| **`ziokt-effort.service`** | Node/Python Web Worker | `8081` | Effort 算力前端面板后端服务 |

### 1.5 域名、证书与公网入口映射关系

Caddy 负责对外提供 HTTPS/TLS 服务，全量域名映射如下：

```
                              [ Internet Users / Clients ]
                                           │
                                           ▼ (HTTPS 443 / HTTP 80)
                             ┌───────────────────────────┐
                             │    Caddy Reverse Proxy    │
                             └─────────────┬─────────────┘
                                           │
       ┌───────────────────┬───────────────┼───────────────┬───────────────────┐
       ▼                   ▼               ▼               ▼                   ▼
cor-web.ziokt.com     ziokt-gateway...  ziokt-ufs...    ziokt-chat...       ziokt-sim...
(重写到 /nns/corium)  (网关主入口 8080) (UFS存储 8184)  (密聊 8182)         (仿真 8183)
```

- **生产主域名**：`https://cor-web.ziokt.com/`（绑定 Cloudflare DNS，重写路由至 `/nns/corium` 去中心化门户）
- **论坛直达**：`https://cor-web.ziokt.com/app/forum`（实时渲染 `forum.db` 原生数据）
- **UFS 存储管理**：`https://cor-web.ziokt.com/app/ufsdcpm`
- **UFS API 节点**：`https://ufs.ziokt.com/api/stats`（支持 Digest Auth，用户 `admin`）
- **原始网关替代链接**：`https://gateway.ziokt.com/nns/corium`（完全兼容保留）
- **各子系统入口**：
  - `https://chat.ziokt.com/`（WATChat）
  - `https://sim.ziokt.com/`（SimManager）
  - `https://effort.ziokt.com/`（Effort 算力）
  - `https://tri.ziokt.com/`（Tri 离线状态机）

### 1.6 归档打包产物（家目录下）

生产部署与纯源码包已单独打包保存在 `/home/admin/`：

1. **生产部署归档包**：
   - 路径：[`/home/admin/Ziokt-production-deployment-2026-10-16.zip`](file:///home/admin/Ziokt-production-deployment-2026-10-16.zip)
   - 大小：约 63 MB
   - SHA-256：`8c995ad21e56ea183742ddb94c0e38d22c9c890849d3beede4cf2a4ad93f99e3`
   - 包含内容：完整的 `ziokt-production` 目录树，包含预编译二进制、加固配置文件、全套 Systemd 单元文件、真实持久化的 `forum.db`、`chain.db`、`dht.db` 及所有 P2P 对象文件。
2. **源码纯文本交换归档包**：
   - 路径：[`/home/admin/Ziokt-Corium-Shadow6-source-2026-10-16.zip`](file:///home/admin/Ziokt-Corium-Shadow6-source-2026-10-16.zip)
   - 大小：约 5.0 MB
   - SHA-256：`1e99ab80d22361c05f72aeca8fac90c9f7e28a51f5004642c3eedf7fb1029649`
   - 包含内容：通过 `Shadow6/Tools/archive_preflight.py` 严格校验的 Ziokt、Corium、Shadow6 核心纯文本源码。

---

## 2. 用户核心指令深度梳理与技术实施方案

针对用户提出的三大核心改进指令，梳理如下技术规格方案，便于后续标准化合入：

### 2.1 指令一：网关部署体系原生化（直接合入源码作为默认网关）

#### 现存问题诊断
当前整套网关部署体系主要驻留在外部生产部署目录 `~/.local/share/ziokt-production/` 与家目录脚本中。Corium 与 Ziokt 的原始代码库尚未内置这一套开箱即用的“默认网关脚手架”，新节点初次检出源码时，需要繁琐的手动配置才能拉起多端口网关。

#### 技术实施方案

```
源码仓库整合规划:
Ziokt / Corium 源码树
 ├── gateway/                       # [新增] 默认网关核心组件
 │   ├── default_portal/            # 默认静态门户资产 (原 static_status_site)
 │   │   ├── index.html
 │   │   └── manifest.json
 │   ├── default_dapp/              # 默认去中心化 DApp (原 explorer_dapp.py)
 │   │   ├── entrypoint.py
 │   │   └── dapp_manifest.json
 │   ├── caddy/                     # 默认 Caddy 配置模板
 │   │   └── Caddyfile.template     # 支持环境变量动态渲染 (SSLIP_IP, DOMAIN)
 │   └── systemd/                   # 标准 Systemd 模板
 │       ├── ziokt-gateway.service.template
 │       └── ziokt-ufs.service.template
 └── tools/
     └── gateway_bootstrap.py       # [新增] 一键网关部署与引导脚本
```

1. **代码合入路径**：
   - 在 `Corium/` 或 `Ziokt/` 根目录下新增 `gateway/` 模块，将 `explorer_dapp.py`、`static_status_site/index.html` 以及 `Caddyfile` 模版直接纳入版本控制。
2. **开箱即用引导脚本 (`gateway_bootstrap.py`)**：
   - 支持子命令：`corix gateway init --default` 或 `ziokt gateway bootstrap`。
   - 自动化流程：检测网络环境 $\rightarrow$ 获取节点公网 IP 与绑定域名 $\rightarrow$ 动态渲染 `Caddyfile` $\rightarrow$ 自动将默认 DApp 与静态门户写入本地 P2P 对象库并注册至 NNS $\rightarrow$ 生成并启动 Systemd 服务。
3. **CI 流程固化**：
   - 在 `.github/workflows/` 或本地 `ci/` 中增加网关引导端到端冒烟测试，确保每次代码构建都能直接拉起默认网关并返回 200。

---

### 2.2 指令二：创世节点与交互操作鉴权控制（防冒用且默认只读公开）

#### 现存安全风险诊断
目前网关沙箱在收到 Web 端发送的 `topic` / `reply_to` / `content` GET/POST 请求时，直接调用底层 `forum_create_topic`。底层脚本会自动读取本地环境的 `USER_IDENTITY_FILE`（创世节点私钥）进行 Ed25519 签名。  
**这导致公网任何未经验证的匿名访客，只要向 `/app/forum` 发送参数，即可借用创世节点的权威身份向全网广播帖子！**

#### 技术实施方案：分级鉴权与双轨签名架构

```
                     访客请求 (GET/POST /app/forum)
                                   │
                                   ▼
                   ┌───────────────────────────────┐
                   │    是否携带写入动作参数？     │
                   └───────────────┬───────────────┘
                          No       │       Yes
               ┌───────────────────┘       └───────────────────┐
               ▼                                               ▼
       [ 默认公开只读访问 ]                         [ 严格权限与鉴权过滤 ]
   - 查询 forum.db                                             │
   - 返回已验证的话题与回复                                    ├── 1. Bearer Token 验证 (API Key)
   - 任何人均可自由浏览 (无需登录)                             ├── 2. 本地 Session / 客户端私钥签名
                                                               └── 3. 创世特权隔离检查
                                                                       │
                                                   ┌───────────────────┴───────────────────┐
                                                   ▼                                       ▼
                                       [ 创世管理操作 (私钥A) ]                [ 普通访客身份 (私钥B/临时ID) ]
                                      需要 node_master_token                   由客户端生成独立密钥签名
                                      代表官方节点发布权威公告                 标记为 Guest/Verified User
```

1. **公开读、严格写（Public Read, Authenticated Write）**：
   - **读取阶段**：所有话题列表、帖子内容、区块链高度、NNS 记录继续保持 100% 匿名公开，无需任何鉴权或 Cookie。
   - **写入阶段**：禁止网关在没有明确授权的情况下私自调用创世私钥签名。
2. **双轨写入鉴权机制**：
   - **模式 A：节点管理员发布（权威公告）**：
     - 请求头或表单必须附带 `Authorization: Bearer <NODE_AUTH_TOKEN>`（Token 由节点启动时随机生成保存在 `~/.local/share/ziokt-production/config/admin_token.key`，权限为 600）。
     - 只有携带正确 Token 的请求，才被允许使用创世身份签名，防止冒领官方公告。
   - **模式 B：社区普通用户发帖（去中心化身份）**：
     - Web 前端引入 WebCrypto API，在用户本地浏览器直接生成临时或持久化的 Ed25519 密钥对。
     - 用户的帖子由用户本地私钥签名，网关仅作为中继节点（Relayer），将用户自签名的 Manifest 转发写入 `forum.db`，作者字段标注为用户真实的公钥哈希，彻底杜绝身份越权。
3. **频率与防刷限制（Rate Limiting）**：
   - 对未认证或普通用户的发帖请求强制启用基于 IP 与公钥的滑动窗口限流（例如单 IP 每 5 分钟限发 1 帖），防止恶意垃圾数据填满 P2P 存储。

---

### 2.3 指令三：全系统与前端高扩展性国际化（i18n）架构设计

#### 现存问题诊断
当前 DApp 页面和静态门户中的大部分界面文案（标题、按钮、描述、提示信息）均为硬编码中文，无法满足海外社区或多语言环境的接入需求，扩展性不足。

#### 技术实施方案：轻量级、高扩展的前后端双层 i18n 引擎

```
                               客户端 HTTP 请求
                                      │
                                      ▼
           [ 语言协商解析 (URL ?lang=xx > Cookie > Accept-Language Header) ]
                                      │
                                      ▼
                      ┌───────────────────────────────┐
                      │     i18n 字典映射中心 (JSON)  │
                      │  (zh-CN, en-US, ja-JP, ...)   │
                      └───────────────┬───────────────┘
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            ▼                                                   ▼
   [ DApp 服务端渲染 (SSR) ]                           [ 前端动态切换 (Client) ]
   根据当前 lang 注入对应模板字典                      右上角语言下拉切换组件
   输出结构化多语言 HTML                              本地保存语言偏好 (localStorage)
```

1. **字典结构设计 (`i18n.json`)**：
   采用分命名空间（Namespace）扁平化键值对设计，支持无限扩展新语种：
   ```json
   {
     "zh-CN": {
       "nav.forum": "💬 原生论坛",
       "nav.fileshare": "📦 文件共享",
       "forum.title": "Corium 原生去中心化论坛",
       "forum.new_topic": "✍️ 发起新讨论话题",
       "forum.author_placeholder": "作者昵称 / 节点代号",
       "status.running": "运行中",
       "status.verified": "已验证"
     },
     "en-US": {
       "nav.forum": "💬 Native Forum",
       "nav.fileshare": "📦 FileShare",
       "forum.title": "Corium Decentralized Native Forum",
       "forum.new_topic": "✍️ Start New Topic",
       "forum.author_placeholder": "Author Nickname / Node ID",
       "status.running": "RUNNING",
       "status.verified": "VERIFIED"
     }
   }
   ```
2. **多源语言探测协商策略**：
   - 优先级 1：URL 查询参数（`?lang=en` 或 `?lang=zh`）。
   - 优先级 2：请求头 `Cookie: ziokt_lang=en`。
   - 优先级 3：浏览器标准头 `Accept-Language: en-US,en;q=0.9`。
   - 默认后备：`en-US`（国际化首选）或 `zh-CN`。
3. **前端扩展支持**：
   - 在 DApp 导航栏右上角增加切换按钮（`[ 🌐 简体中文 | English ]`）。
   - 字典统一抽离为独立配置，新增语言无需修改任何业务逻辑代码。

---

## 3. ETP FileShare 与 DHT 对象存储大分块流式传输“三大优化”全景设计

### 3.1 现状技术剖析与瓶颈诊断

目前系统中存在两套分布式分块逻辑，均设计于早期小文件交互场景：

```
+---------------------------------------------------------------------------------------+
|                                  当 前 现 状 瓶 颈                                    |
+---------------------------------------------------------------------------------------+
|  [ETP FileShare]                                                                      |
|  - 分块大小: 固定 16 KB (const CHUNK_SIZE = 16 * 1024)                                |
|  - 最大文件预算: 硬限制 1024 个分块 (16 KB * 1024 = 16 MB 封顶)                       |
|  - 传输模型: 单 Peer 顺序串行轮询下载                                                 |
|  - 消费机制: 必须全部下载落盘为临时文件才可用，退出立即 drop 删除                     |
+---------------------------------------------------------------------------------------+
|  [Corium DHT 对象存储]                                                                |
|  - 分块大小: 默认 256 KB 静态切片                                                     |
|  - 传输机制: 串行遍历 Manifest 中的 chunk 列表，逐个落盘拼接                          |
|  - 索引开销: 存储 1GB 文件需 4096 个分块记录，DHT 路由表与元数据急剧膨胀              |
|  - 消费机制: 不支持 HTTP Range，无法边下边看，音视频需长时间等待全量落盘              |
+---------------------------------------------------------------------------------------+
```

---

### 3.2 优化一：自适应动态大分块（Adaptive Content-Defined Chunking, CDC）

#### 设计目标
摆脱固定 16KB/256KB 的死板限制，根据文件类型与体积自适应调整分块粒度，将大文件切片提升至 **1 MB ~ 8 MB**，同时使用 CDC 算法最大化去重率。

```
原始大文件数据流:
[==============================================================================]
                 │ FastCDC (滑窗指纹算法，目标均值 2MB ~ 4MB)
                 ▼
[   Chunk 1 (2.1MB)   ][   Chunk 2 (3.8MB)   ][   Chunk 3 (1.9MB)   ] ...
         │                       │                       │
      BLAKE3                  BLAKE3                  BLAKE3
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
                     层次化 Merkle 树元数据清单
              (Manifest 体积压缩 95% 以上，支持海量数据索引)
```

#### 技术规范与实现策略
1. **分块算法演进**：
   - 弃用固定的固定偏移切片（Fixed-Size Chunking），引入 **FastCDC（Fast Content-Defined Chunking）** 算法。
   - 在数据边界产生“基于内容的数据切片点”，当文件局部修改时，只有变动部分的分块哈希改变，未修改部分保持哈希命中，极大提高增量同步效率。
2. **动态分块层级规划**：
   - **超小文件 (< 1 MB)**：单块直接封装，避免额外切片元数据开销。
   - **常规文件 (1 MB ~ 64 MB)**：动态分块目标均值设为 **1 MB**。
   - **超大文件 (> 64 MB，如视频、系统镜像、模型权重)**：动态分块目标均值设为 **4 MB ~ 8 MB**。
3. **Manifest 层次化压缩**：
   - 采用多级 Merkle 树，每 1024 个叶子分块汇总为一个二级节点，即使 100GB 的大文件，其根 Manifest 体积仍可保持在数 KB 以内，彻底消除 DHT 节点元数据存储爆炸。

---

### 3.3 优化二：Swarm 多源并发换块管道与滑动窗口调度（Swarm Concurrent Pipelining）

#### 设计目标
告别单节点串行请求模式，借鉴 BitTorrent 与 IPFS Bitswap 协议，实现多 Peer 节点并发换块与支持优先级的滑动窗口调度。

```
                     客户端下载任务 (滑动窗口调度器)
                                    │
    ┌───────────────────────┬───────┴───────┬───────────────────────┐
    ▼ (并发请求 Block 0)    ▼ (并发请求 Block 1) ▼ (并发请求 Block 2)   ▼ (并发请求 Block 3)
┌────────────┐        ┌────────────┐        ┌────────────┐        ┌────────────┐
│   Peer A   │        │   Peer B   │        │   Peer C   │        │   Peer D   │
└────────────┘        └────────────┘        └────────────┘        └────────────┘
    │                       │                       │                       │
    ▼                       ▼                       ▼                       ▼
    └───────────────────────┼───────────────────────┘
                            ▼
              [ 内存组装缓冲区 (Ring Buffer) ]
        (按序号重排并即时提交给消费通道，无需等待末尾分片)
```

#### 技术规范与实现策略
1. **Swarm 并发池管理**：
   - 客户端在 DHT 网络中检索持有目标根 Manifest 的所有候选节点池（Swarm Peers）。
   - 维护节点 RTT 延迟与可用带宽评分表，将并发分片请求动态下发给最快的 4~16 个 Peer。
2. **基于播放/读取偏好的滑动窗口调度器（Sliding Window Scheduler）**：
   - **顺序敏感场景（视频即点即播、音频流）**：
     - **紧急窗口（Urgent Window）**：优先并发抓取当前读取指针后紧随的 $N$ 个分块（权重最高）。
     - **预取窗口（Prefetch Window）**：在带宽富余时在后台异步低优先级预拉取后续分块。
   - **随机读取场景（数据库只读查询、压缩包解压局部文件）**：
     - 支持只下载目标字节范围关联的特定叶子分块，无需拉取整文件。
3. **断点续传与块级坏块自愈**：
   - 每个下载完成的分块独立进行 BLAKE3 校验，损坏分块直接丢弃并从其他 Peer 重新排队抓取，彻底避免整个大文件重传。

---

### 3.4 优化三：网关零落盘流式直通（Zero-Copy Direct Streaming & HTTP Range 支持）

#### 设计目标
网关提供真正的 HTTP 媒体流与大文件下载直通能力，数据在网关内存中经由环形队列直接管道转发给浏览器，网关宿主机磁盘零写放大、零落盘耗时。

```
浏览器端发起请求:
GET /stream/5d2b53b2f6c8... HTTP/1.1
Range: bytes=10485760-20971519 (请求中间 10MB 数据)
                                 │
                                 ▼
                     ┌────────────────────────┐
                     │  Ziokt / Corium 网关   │
                     └───────────┬────────────┘
                                 │
               根据 Range 偏移量快速定位所需的分块序号
                          (例如分块 5 到 分块 9)
                                 │
                                 ▼
                    并发从 P2P Swarm 抓取目标分片
                                 │
                                 ▼
                     [ 内存环形队列 (Zero-Copy) ]
                                 │
                                 ▼
返回 HTTP 206 Partial Content (Transfer-Encoding: chunked)
数据直接经由 Socket 喷吐给浏览器，网关机器磁盘写入量 = 0！
```

#### 技术规范与实现策略
1. **全功能 HTTP Range 请求支持**：
   - 网关层实现 RFC 7233 范围请求规范，返回 `HTTP 206 Partial Content` 与 `Content-Range: bytes START-END/TOTAL`。
   - 彻底激活原生 HTML5 `<video>`、`<audio>` 播放器的进度条任意拖拽跳转能力（Seekable Streaming）。
2. **内核级零拷贝与流式管道**：
   - 网关内部采用 Python `asyncio.StreamReader` / Rust `tokio::io` 流管道，从 P2P Socket 读取分片校验通过后，直接透传写入 HTTP 响应的 WFile 流。
   - 杜绝以往必须在网关本地生成 `.tmp` 大文件再发送的阻塞逻辑，释放网关磁盘 I/O 压力。
3. **浏览器端 WebAssembly 解密扩展（端到端保密）**：
   - 若分块在 P2P 网络中经过端到端加密（如 ETP Sphinx 保护），网关可只传输密文流，由浏览器内置的 Wasm 模块配合 Web Workers 进行边接收、边解密、边通过 MediaSource Extensions (MSE) 喂给播放器。

---

### 3.5 演进对比矩阵与实施路线图

| 评估维度 | 当前现状架构 (Current State) | 三大优化演进架构 (Target State) | 收益分析 |
| :--- | :--- | :--- | :--- |
| **文件大小上限** | ETP 封顶 16 MB；Corium 适合几十 MB 以内 | **无上限**（轻松承载 100 GB+ 镜像/视频/大模型） | 彻底打破去中心化应用的文件体积封锁 |
| **分块颗粒度** | 16 KB 或 256 KB 静态切片 | **1 MB ~ 8 MB FastCDC 动态自适应切片** | Manifest 元数据体积与索引树压缩 90%~95% |
| **传输模式** | 单线程串行阻塞轮询 | **多节点 Swarm 并发流水线 + 滑动窗口** | 充分饱和下行带宽，高 RTT 延迟下提速 5~10 倍 |
| **网关消费模式** | 必须全量落盘组装成临时文件 | **内存零落盘直通（Zero-Copy Chunked Stream）** | 消除网关磁盘 I/O 磨损与写放大，实现秒开点播 |
| **媒体点播支持** | 不支持进度拖拽，必须完全载入 | **标准 HTTP 206 Range 支持 + Seekable 播放** | 真正实现去中心化大视频/长音频在线秒播 |
| **增量更新能力** | 文件单字节改动导致全量重新分块 | **CDC 内容哈希命中局部切片去重** | 仅传输变动分块，节约 80% 以上网络中继带宽 |

#### 分阶段演进实施路线

```
[ Phase 1: 规范与元数据升级 ]
  ├── 1. 定义 ziokt.manifest.v2 规范（支持多层级 Merkle 树）
  └── 2. 引入 FastCDC 算法库，在本地工具集实现 1MB~8MB 动态分片

[ Phase 2: 网关流式直通改造 ]
  ├── 1. 网关核心适配 HTTP 206 Partial Content 与 Range 请求头解析
  └── 2. 构建内存环形缓冲区，打通 P2P 分片流向 HTTP 响应流的直通传输

[ Phase 3: Swarm 并发传输与端侧增强 ]
  ├── 1. 实现多 Peer 并发调度器与滑动窗口请求管道
  └── 2. 前端引入 Wasm 流式解密与 MSE 播放器无缝集成
```

```

---

## 4. 一键打包发布方法与自动化脚本规范

本系统包含两个核心归档包：**源码纯文本交换归档包** 与 **生产部署全量归档包**。其打包机制有严格的格式与安全性约束：

### 4.1 源码纯文本交换归档包打包方法 (Source Package)

#### 特殊约束与原理
- **纯文本交换合约（Text-Only Exchange Contract）**：Ziokt/Shadow6 规范要求跨节点源码交换包内**严禁包含二进制字节或未转义非文本文件**。必须经由 `prepare_text_zip.py` 转换，并在生成后通过 `archive_preflight.py` 预检校验。
- **排除项与暂存**：必须排除各仓库的虚拟环境（`.venv`）、编译产物（`.zig-cache`、`target/`、`build/`）以及本地日志。未提交的工作区修改需要与 Git HEAD 一并检出暂存。

#### 独立打包执行命令
```bash
python3 - <<'PY'
from pathlib import Path
import shutil, subprocess, tempfile

repos = [
    ('Shadow6', '/home/admin/Shadow6', [
        'Shadow6/work', 'Shadow6/Benchmark/results', 'Shadow6/.venv', 'Shadow6/.venv-ft', 'Shadow6/.tools',
        'Shadow6/.runtime', 'Shadow6/.tmp', 'Shadow6/.nim_runtime', 'Shadow6/.android-toolchain',
        'Shadow6/Android/.gradle', 'Shadow6/Android/build', 'Shadow6/Android/app/build', 'Shadow6/Android/dist',
        'Shadow6/Android/app/src/main/jniLibs', 'Shadow6/config.mk', 'Shadow6/release*',
        'Shadow6/Core-Rust/target', 'Shadow6/Core-Gleam/build', 'Shadow6/Core-Gleam/obj',
        'Shadow6/Core-Zig/.zig-cache', 'Shadow6/Core-Zig/zig-out', 'Shadow6/Core-Ada/obj', 'Shadow6/Core-Nim/obj',
        'Shadow6/Detector/datasets', 'Shadow6/Detector/models', 'Shadow6/Auto-Orchestrator/generated',
        'Shadow6/Auto-Orchestrator/generated-rust']),
    ('Ziokt', '/home/admin/Ziokt', ['Ziokt/.venv', 'Ziokt/dist', 'Ziokt/build', 'Ziokt/__pycache__',
                                    'Ziokt/.pytest_cache', 'Ziokt/.mypy_cache']),
    ('Corium', '/home/admin/Corium', []),
]
archive = Path('/home/admin/Ziokt-Corium-Shadow6-source-2026-10-16.zip')
if archive.exists(): archive.unlink()

with tempfile.TemporaryDirectory(prefix='ziokt-tri-source-') as temporary:
    root = Path(temporary) / 'tree'
    root.mkdir()
    for name, repo, exclusions in repos:
        producer = subprocess.Popen(['git', '-C', repo, 'archive', '--format=tar', '--prefix='+name+'/', 'HEAD'], stdout=subprocess.PIPE)
        consumer = subprocess.Popen(['tar', '-xf', '-', '-C', str(root), *sum((['--exclude='+pattern] for pattern in exclusions), [])], stdin=producer.stdout)
        producer.stdout.close()
        if consumer.wait() or producer.wait(): raise SystemExit('source staging failed: ' + name)
        
        # 合并工作区已修改文件
        modified = subprocess.check_output(['git', '-C', repo, 'diff', '--name-only'], text=True).splitlines()
        for mod_file in modified:
            src = Path(repo) / mod_file
            dst = root / name / mod_file
            if src.is_file() and not src.is_symlink():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                
    prep = '/home/admin/Shadow6/Tools/prepare_text_zip.py'
    for name, _, _ in repos:
        subprocess.run(['python3', prep, str(root/name)], check=True)
    subprocess.run(['zip', '-rq', '-X', str(archive), 'Ziokt', 'Corium', 'Shadow6'], cwd=root, check=True)

print('Source Archive created:', archive, 'Size:', archive.stat().st_size)
PY

# 强制执行纯文本合约预检与哈希校验
python3 /home/admin/Shadow6/Tools/archive_preflight.py --zip /home/admin/Ziokt-Corium-Shadow6-source-2026-10-16.zip
sha256sum /home/admin/Ziokt-Corium-Shadow6-source-2026-10-16.zip
```

---

### 4.2 生产部署目录归档包打包方法 (Deployment Package)

#### 约束与排除规范
- 部署包物理根目录位于 `/home/admin/.local/share/ziokt-production/`。
- **排除运行时 UNIX Socket**：必须通过 `-x "ziokt-production/corium/run/*.sock"` 排除动态 `.sock` 文件，避免解压时产生管道文件错误或损坏。
- 保留完整的数据库状态（`forum.db`、`chain.db`、`dht.db`）与配置凭证。

#### 独立打包执行命令
```bash
cd /home/admin/.local/share && \
rm -f /home/admin/Ziokt-production-deployment-2026-10-16.zip && \
zip -r /home/admin/Ziokt-production-deployment-2026-10-16.zip ziokt-production \
  -x "ziokt-production/corium/run/*.sock" && \
sha256sum /home/admin/Ziokt-production-deployment-2026-10-16.zip
```

---

### 4.3 一键打包整合脚本 (`package_all.sh`) 现成代码

您可以直接使用下方整合脚本，一键顺序执行**源码包生成**、**预检校验**与**部署包生成**：

```bash
#!/usr/bin/env bash
# ==============================================================================
# Ziokt & Corium 生态一键双包构建脚本 (package_all.sh)
# 用途: 自动打包纯文本源码交换包 (通过安全预检) 并完整打包生产部署运行时目录
# ==============================================================================
set -euo pipefail

DATE_TAG=$(date +%Y-%m-%d)
SRC_ZIP="/home/admin/Ziokt-Corium-Shadow6-source-${DATE_TAG}.zip"
DEP_ZIP="/home/admin/Ziokt-production-deployment-${DATE_TAG}.zip"

echo "=========================================================="
echo " [1/2] 开始构建源码纯文本交换归档包..."
echo "       目标路径: $SRC_ZIP"
echo "=========================================================="

python3 - <<PY
from pathlib import Path
import shutil, subprocess, tempfile

repos = [
    ('Shadow6', '/home/admin/Shadow6', [
        'Shadow6/work', 'Shadow6/Benchmark/results', 'Shadow6/.venv', 'Shadow6/.venv-ft', 'Shadow6/.tools',
        'Shadow6/.runtime', 'Shadow6/.tmp', 'Shadow6/.nim_runtime', 'Shadow6/.android-toolchain',
        'Shadow6/Android/.gradle', 'Shadow6/Android/build', 'Shadow6/Android/app/build', 'Shadow6/Android/dist',
        'Shadow6/Android/app/src/main/jniLibs', 'Shadow6/config.mk', 'Shadow6/release*',
        'Shadow6/Core-Rust/target', 'Shadow6/Core-Gleam/build', 'Shadow6/Core-Gleam/obj',
        'Shadow6/Core-Zig/.zig-cache', 'Shadow6/Core-Zig/zig-out', 'Shadow6/Core-Ada/obj', 'Shadow6/Core-Nim/obj',
        'Shadow6/Detector/datasets', 'Shadow6/Detector/models', 'Shadow6/Auto-Orchestrator/generated',
        'Shadow6/Auto-Orchestrator/generated-rust']),
    ('Ziokt', '/home/admin/Ziokt', ['Ziokt/.venv', 'Ziokt/dist', 'Ziokt/build', 'Ziokt/__pycache__',
                                    'Ziokt/.pytest_cache', 'Ziokt/.mypy_cache']),
    ('Corium', '/home/admin/Corium', []),
]
archive = Path('$SRC_ZIP')
if archive.exists(): archive.unlink()

with tempfile.TemporaryDirectory(prefix='ziokt-tri-source-') as temporary:
    root = Path(temporary) / 'tree'
    root.mkdir()
    for name, repo, exclusions in repos:
        producer = subprocess.Popen(['git', '-C', repo, 'archive', '--format=tar', '--prefix='+name+'/', 'HEAD'], stdout=subprocess.PIPE)
        consumer = subprocess.Popen(['tar', '-xf', '-', '-C', str(root), *sum((['--exclude='+pattern] for pattern in exclusions), [])], stdin=producer.stdout)
        producer.stdout.close()
        if consumer.wait() or producer.wait(): raise SystemExit('source staging failed: ' + name)
        
        modified = subprocess.check_output(['git', '-C', repo, 'diff', '--name-only'], text=True).splitlines()
        for mod_file in modified:
            src = Path(repo) / mod_file
            dst = root / name / mod_file
            if src.is_file() and not src.is_symlink():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                
    prep = '/home/admin/Shadow6/Tools/prepare_text_zip.py'
    for name, _, _ in repos:
        subprocess.run(['python3', prep, str(root/name)], check=True)
    subprocess.run(['zip', '-rq', '-X', str(archive), 'Ziokt', 'Corium', 'Shadow6'], cwd=root, check=True)

print(">> 源码归档包生成成功: " + str(archive))
PY

echo ">> 正在对源码包执行合约安全预检 (archive_preflight.py)..."
python3 /home/admin/Shadow6/Tools/archive_preflight.py --zip "$SRC_ZIP"
echo ">> 源码包 SHA-256:"
sha256sum "$SRC_ZIP"

echo ""
echo "=========================================================="
echo " [2/2] 开始构建生产部署目录归档包..."
echo "       目标路径: $DEP_ZIP"
echo "=========================================================="

cd /home/admin/.local/share
rm -f "$DEP_ZIP"
zip -rq "$DEP_ZIP" ziokt-production -x "ziokt-production/corium/run/*.sock"

echo ">> 生产部署包构建完成!"
echo ">> 部署包 SHA-256:"
sha256sum "$DEP_ZIP"
ls -lh "$SRC_ZIP" "$DEP_ZIP"
echo "=========================================================="
echo "全部打包完成，产物均保存在家目录下。"
```

---

## 5. 总结与快速索引

本系统已在生产环境彻底消除了双套模拟存储问题，所有生产应用（包含 ETP 论坛、UFS/DCPM 安全存储、Shadow6 双原生 Provider）均已在生产联邦中真实上线并稳定运行。

- **文档物理绝对路径**：[`/home/admin/ZIOKT_GATEWAY_ARCHITECTURE_AND_ROADMAP.md`](file:///home/admin/ZIOKT_GATEWAY_ARCHITECTURE_AND_ROADMAP.md)
- **生产主入口**：[https://cor-web.ziokt.com/](https://cor-web.ziokt.com/)
- **原生论坛**：[https://cor-web.ziokt.com/app/forum](https://cor-web.ziokt.com/app/forum)
- **UFS 存储管理**：[https://cor-web.ziokt.com/app/ufsdcpm](https://cor-web.ziokt.com/app/ufsdcpm)
- **生产归档包**：[`/home/admin/Ziokt-production-deployment-2026-10-16.zip`](file:///home/admin/Ziokt-production-deployment-2026-10-16.zip)
- **源码归档包**：[`/home/admin/Ziokt-Corium-Shadow6-source-2026-10-16.zip`](file:///home/admin/Ziokt-Corium-Shadow6-source-2026-10-16.zip)



## 2026-10-18：命名、可选 Tracker、隐私与静态站点扩展

新增实现与精确边界参见 [中文部署与使用说明](NAMING_PRIVACY_TRACKER_ZH.md)。

- Ziokt DNS：54 个保留/通用后缀，按组件来源查询；默认不代理公共 DNS；多 realm/名称空间独立隔离；Corium NNS 保持无 TLD、逐后缀主动发布；逐级签名子域委托；公共记录与加密组件描述分离。
- Corium IBC：可选 home-chain 共享 Namespace、拥有者校验、短租约与单调序号、checkpoint/历史证明；本地双真实链已验收，生产需明确配置源链启用高度与治理信任锚。
- MCP/TG：新增名称状态、解析、组件发布、原生 NNS/IBC 写入计划与可选 Tracker 接口；本次配置目录 361 工具；以部署导出的目录与在线 tools/list 为准。
- Tracker：可选、多服务器、显式发布、续租/撤销/过期、匿名中继授权，复用现有签名发现池与 mTLS，不替代 DHT/Gossip。
- 原生实验性屏蔽所有权仅限 test-/dev- 网络；没有独立密码审计，生产屏蔽未开启。审查批准不能自动解密，仍需持有者自愿授权披露。
- 浏览器论坛需要自行提供签名身份；静态站点支持真实 JS/模块与多种静态博客产物，在隔离来源中执行；不执行服务端博客插件。

禁止将 DNS 传输加密、ECH 配置发布、固定大小封装、社区策略或上述测试描述成“完全保密”“绝对匿名”或自动获得生产审计。

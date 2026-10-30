# 独立节点验收记录（进行中，2026-10-30）

本记录取代旧报告中“所有双链共同挖矿已完成”的结论。历史报告不能作为当前节点验收。
两台受控主机分别为 `54.64.24.133` 和 `38.175.194.110`。远端使用 Release 制品和
预编译 Python 运行时；本轮没有在远端编译原生 Core。

## 主链

经用户明确授权，归档两端原分支，保留各自身份和 TLS 密钥，从原生验证通过的 H50
重建 `ziokt-main`。原分支 H51–H64 的占位签名不能算原生验收通过，也没有获准绕过。
新分支通过真实原生提案、投票、完整治理等待窗口，在 H161 激活已有 PoW-v2。

- 原 genesis：`599b7512c4ffb640520433f0772f00e78198ad958f444d25459dbca8c38ce0fa`
- H50：`409d4800864aed38dcd81742948c796d4a02a4a3a06a67e93ea462bd10589a54`
- 两端原生同步确认的 H162：`6d7ef60d26f6dc8e0766e58f89df630c7618d9f00994e4b6f431249c6a460466`
- 已修复原生激活高度验证顺序、重放链头缓存及挖矿/重组写入互斥。
- 双矿工持续同链、重启恢复和 DNA 双端同步仍在验收，尚未宣布通过。

Corium 修改见独立仓库 `corix_v108.sh`、`consensus_hold.py`、
`rebuild_authorization.py` 和 `docs/MAIN_REBUILD_ADMISSION.md`。
针对性原生测试包含真实 TLS 激活同步、错误链头缓存和持有真实写锁时拒绝重组。
这些测试的隔离策略夹具不作为公网治理证据。

原分支完整目录保留在本机
`~/.local/share/ziokt-production/private-bootstrap-backup/main-invalid-branch-full-20261030T041128Z`
和对端 `/root/ziokt-original-main-full-20261030T041249Z`。
回滚代码前先停矿并核对匹配的签名准入文件；不得为恢复可用性重启无效签名分支。

## DNA 消费组件

代码：`ziokt/dna_consumer.py`，部署工具：`tools/deploy_dna_consumer.py`，
真实签名探测：`tools/probe_dna_consumer.py`，测试：`tests/test_dna_consumer.py`。
两端均部署独立 `ziokt-dna-consumer`，仅监听回环端口 8189；初始只读授权。
本机已消费 Corium、Shadow6 原生状态接口，对端已消费 Corium 状态接口。

本机真实链上路径：

- 交易：`a126e10bb1858b52ae91e4cb4e001cd1955ffd80382775536f993f3064f83650`
- 入块：DNA H4391，达到一块确认后执行 Corium 原生读取，持久回执 `completed_read`。
- 独立 DNA 域：`8cf357aa50105e9d0fdc3dcc54beb102e74db1d7084ad2686d80e09b5e27105a`
- 策略：`4228125129edcc2e6d1d222a787f4d5b8eacab30a7731d230d55e439f3f243e8`

共享历史 genesis 不充当独立 DNA 身份。消费时检查原生 DNA 工作证明中的恢复链 ID、
策略承诺、RNA 签名和有效期、发送者授权及持久序列；消费区块重组后停止处理。
本项不包含 DNA 双端同链的通过声明，也不包含金融消费、自动安装或执行包。
`systemctl disable --now ziokt-dna-consumer` 可独立回滚，保留私有日志防止重放。
详见 `docs/DNA_CONSUMER.md`。

## UFS / dCPM

对端通过真实公网 HTTPS 从本机 18443 端口下载签名包，使用独立短期测试 CA、
SHA-256 Digest 认证及明确允许的发布者。源服务关闭后，对端重新打开持久包存储，
仍可核对原始文件；篡改归档被拒绝。测试包仅含文档，没有执行软件。

- 包：`08dfd07cb2b5859117ec134bf3512c7203b24fdbd8f06bd9cf36ce60cf20ea17`
- 版本：`3179ebd7faca453b46e0dae3c8142e967ee5414b060eac107fa537e024bd1f28`
- 文件 SHA-256：`5879e14a4925ba8bea489cc88a68a17b94ea09d40f1ea6cecaae9b057f96f0f0`

产品入口 `companions/ufsdcpm/src/dcpm_ufs_integration.py`；验签及持久化
`companions/ufsdcpm/src/dcpm_ufs_packages.py`。未改动包管理职责或 Corium 权限。
临时源服务 `ziokt-acceptance-ufs` 已停止。对端验收目录
`/opt/ziokt-main-validator/acceptance/ufs` 可归档删除，不影响原生主节点。

## 待继续验收 / Follow-up

- 主链持续双端共同挖矿、重启与分叉恢复；DNA 两端同链和跨节点消费。
- Shadow6 13 Profiles：现有运行时下 11 个本机命名空间数据路径通过；两个 Gleam
  Profile 启动失败仍需修复。这些结果不等于物理跨主机公网原生线协议通过。
- ETP 公网 UDP 探测未送达；两端抓包暂只观察到各自发包，未宣布成功。
- P2P 浏览器的真实远端节点展示、新闻组、完整跨应用源及 RetroShare F2F 验收。
- 所有最终修改的联合源码包、制品摘要、部署版本及完整验收报告。

当前可继续独立节点验证；完整发布验收仍有上述未通过项。

## P2P 原生 RPC 观测补充

`tools/collect_native_topology.py` 仅探测操作者明确批准的一台现有原生对端，
复用 Corium 签名传输与已有 TLS 对端配置，核对返回的原生身份，不扫描或自动发现地址。
快照状态 `native-rpc-responded` 表示该次原生 RPC 确有响应，不代表业务数据已送达。
`ziokt/p2p_explorer.py` 对带时间戳的适配器快照拒绝五分钟以上旧数据及未来时间。
针对性权限/观测测试共 12 项通过。公共浏览仍隐藏地址和原生身份；独立只读验收凭据
只保存在私有目录。停止采集 timer 并移除 `main-live-probe` 来源即可回滚。

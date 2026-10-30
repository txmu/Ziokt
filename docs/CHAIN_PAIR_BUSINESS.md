# 对等双链与业务链选择

自建网络以 `primary` 与 `dna` 两条独立的原生链组成。两条链都必须创建、初始化并
保留各自状态和节点身份；选择 DNA 承载主要业务不会省略主链，反之亦然。

现有网络描述增加 `business_chain: primary | dna`。浏览器和未指定链的只读查询采用
该选择，显式 `chain=primary` 或 `chain=dna` 可以访问另一条链。配置始终需要两个
独立数据库，不能把同一数据库登记为两个角色。原生链创建及治理仍由 Corium 完成。

`tools/configure_chain_pair.py` 接收两端原生 state root/network ID，核验两条链已经初始化，
固定各自 genesis，并生成可用于 `explorer_networks` 的私有配置。它拒绝缺少任一链的网络，
不复制数据库制造第二条链。选择主要业务链仅改变应用路由，不改变任一链的共识。

消费端使用同一 `ziokt.dna_consumer.Consumer` 执行路径、RNA 签名校验、授权允许列表、
去重、持久回执和重组停止规则；主链与 DNA 没有不同的应用权限等级。DNA 校验 recovery
身份及工作策略，主链校验网络/genesis 派生的独立业务域及原生工作策略。共享历史 genesis
不能作为两个域相同的依据。两端消息不得跨域重放。

部署 DNA 消费端仍使用 `tools/deploy_dna_consumer.py` 默认参数；主链消费端使用
`--chain-role primary --network-id <原生网络ID>`，选择不同 `--root`。默认回环端口
分别为 8189、8190，生成独立 systemd 单元。每条链都应部署消费者；默认只读
`status.get`，业务写入必须同时通过消费者授权和目标原生组件的已有门禁。

主要业务应通过所选链的原生 provider 提交交易，并将相同角色的 consumer 指向该链
数据库。消费执行回执、应用就绪与链上最终性分别记录，不互相替代。

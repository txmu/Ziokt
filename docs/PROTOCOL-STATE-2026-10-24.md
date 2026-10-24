# RNA、ZDNS、OpenCI 与链身份

RNA 签名/编码纯函数与生产 admission 分开。MCP 的 announce/verify 是写操作，要求 `ziokt:names:write`、开启写权限及幂等键。`protocol_state.signing_key` 必须指向已有的 0600 SECP256K1 PEM；`protocol_state.owners` 是运营者核验并配置的规范小写域名到公钥摘要映射。不会接受消息自称的所有者，也不会临时生成身份。它是明确配置的信任根，不能取代原生 NNS 登记证明。

`state/protocol/protocol.sqlite` 在 IMMEDIATE/FULL 事务中保存按链、策略、发送者分隔的收发序号及域名记录。传入 previous_sequence 只能收紧限制。验签、所有权或记录校验失败回滚事务，重启不会清除重放状态。网络广播及链上登记状态单独返回；尚无相应执行器时不能声称已广播或已登记。

OpenCI commitment 写接口要求 `ziokt:evidence:write`。证据保存在相同私有数据库，附配置节点的本地签名见证；读取按 MCP 客户身份隔离。本地见证不冒充 Worker 签名、独立重建、永久备份或原生共识登记。OpenCI 原生的 worker receipt、quorum、chain prepare/settlement 路径仍负责这些维度。

Gateway status 与 `ziokt_chain_provenance` 返回当前实际网络、genesis、H50、tip 签名与 work proof，以及配置目录下存在的恢复声明。新源码中定义恢复主链或 DNA 侧链并不能证明生产节点已启用它们。声明存在也不自动视为完整验证；外部仍应验证声明、区块与重放结果。

合作社的 federate 要求双方成员各自的严格超多数同意，unfederate 只要求退出方达到自身门槛，成员表与身份不合并。cooperative_command 控制登记状态，不能被当作财库、NFT、ZKN 的资产授权。资产路径必须保留资产本身的所有权及签名验证。

冻结部署通过必填 `--settings` 选择四个服务角色、HTTPS 服务、Gateway/GUI 健康 URL 和原 GUI 目录。不会默认部署到某个用户名、域名或服务名。production-reference 是已标注的历史配置参考，不是通用部署默认值。

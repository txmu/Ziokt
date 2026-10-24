# 原生 peer 转发与 ZKT 声誉记账

网络互助继续转发到运营者固定的本地原生 P2P 服务，客户端不能指定任意目标。奖励观察直接来自实际 socket 的写入、原始读取的确认、双向 FIN 和 SHA-256 流摘要。只有两个方向的字节数与摘要对应、且流量达到策略门槛时，才生成持久候选回执。原始密文、IP 和临时 capability token 不写入候选回执；session 使用高熵 capability 的摘要。

候选不是奖励。`relay_rewards` 必须显式配置同网络的 ZKT 策略、固定受益节点、原生账本及至少两个已审批的 peer 身份。见证密钥、原生 peer ID、故障域均须互异，见证不能属于受益节点，且需要 Trusted verifier。公开 API 不接受私钥，也不能自行创建“已观察”回执。双方对同一回执的域分离 Ed25519 见证通过后，才记入原生 ZKT 本地声誉账本；配置额度、每日额度、证据摘要和 session nonce 防止重复记账。跨两本 SQLite 的 settling 意图可在崩溃后由原生唯一 claim 对账，避免重试重复加分。

ZKT 是非货币的本地服务声誉；该入口不转移代币、不修改主链区块或 contribution_scores，也不冒充主链共识奖励。要结算共识层 PoUW，仍须走已治理的引擎、可验证证明及原生确认窗口。见证是运营者审批的信任模型，不是硬件认证、无信任带宽证明或对见证串谋的绝对防护。

Web/Windows 可以导出最新待见证回执；Android 原生网络 Worker 将最新公开回执保存在应用私有目录，用户可复制用于独立核验。节点维护者在核对自己真实转发观察之后，可用 `python -m ziokt.relay_rewards --receipt receipt.json --key peer.key --peer peer-id` 签名。将独立见证以 `{receipt_id,witnesses}` 提交至 `/api/people/rewards/settle`，服务端执行验签与原生记账。缺少完整双向流或审批 quorum 时不生成声誉奖励；空闲状态不制造流量。

配置通过 effort-web 的 `relay_rewards` 传入，精确字段为 root、ledger、network、beneficiary、policy_file、peers、threshold、bytes_per_unit、max_units_per_receipt、max_units_per_day。peers 中每项精确包含 public_key、failure_domain、native_peer_id、pool。策略必须符合原生 ziokt.zkt-reputation-policy.v1，network_id 匹配实际网络，application_services 显式声明 network_relay 的积分率。不会把同一机器的多个组件冒充独立 peer。

直连模式明确为非匿名；匿名载体、加密转发、服务验证和积分记账是不同维度。现有 Tor/I2P/多跳策略维持匿名路径失败时不降级直连。

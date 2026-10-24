# ZKT 本地声誉治理与防刷分

ZKT 是本地非货币声誉，不构成代币、主链共识分数或无需信任的服务证明。已有账本、历史积分和默认四级身份保留；治理只影响后续记账。

政策除应用服务积分率、紧急 Core 与倍数、单笔上限外，支持 `provider_weights_bps`、`service_limits`、自定义递增 `tiers`，以及 `anti_abuse` 的每人每日笔数、每日分数、全局每日分数、冷却秒数和证据 epoch 最大历史天数。日额度以节点接收时钟的 UTC 日计算，不信任调用者 epoch；配置不能超过实现的安全边界。默认每日每人1000笔/50000分、全局1000000分。相同证据摘要不能跨身份再次获奖；每人 epoch/nonce 同样唯一。SQLite 写锁覆盖查重、预算检查、账户更新，进程重启与并发调用不突破额度。

`claim_attestors` 可配置已审批的 Ed25519 公钥到独立故障域映射、threshold、minimum_domains，均至少2。每项 observation 签名的域为 `Ziokt/zkt-service-observation/v1`，载荷精确绑定 operation=claim、network_id、policy_digest 和不含 witnesses 的完整 claim。改变受益人、单位、策略或网络均使签名无效。审批身份属于运营者的信任配置，不能把自报架构、同机多个进程或任意用户摘要当作独立服务证明。未启用该配置的历史 CLI 仍属于本机操作者手动记账接口，不宣称证据已独立核验。

初次政策通过本机 `corix zkt policy POLICY_JSON` 设置。若政策带 governance，则之后不能直接 policy 覆盖，也不能在 record 时传自定义政策绕过。治理包含 authorities（公钥→独立域）、threshold、minimum_domains、veto_threshold、timelock_seconds（至少60秒）、voting_period_seconds（最长30天）。下一版必须同 policy_id、同 network_id、version 恰加1且保留治理。可通过治理更换成员、门槛、积分规则、防刷额度和服务见证者。

原生 CLI 支持 `zkt propose SIGNED_JSON`、`zkt vote SIGNED_JSON`、`zkt enact '{"proposal":"HASH"}'` 和 `zkt proposals '{}'`。签名对象使用 ziokt.signed.v1，域 `Ziokt/zkt-governance/v1`。提案载荷为 operation=propose、network_id、base_policy（当前政策规范 JSON SHA256）、policy、64位十六进制 nonce、created_at、activate_at、expires_at；提案 ID 是该载荷的规范 JSON SHA256。投票载荷为 operation=vote、network_id、proposal、approve（布尔）。签名使用排序、紧凑、UTF-8 JSON；每个成员每案只能投票一次，反对票达到 veto_threshold 即否决。

达到审批人数和独立域门槛、时间锁到期且提案未过期后才可 enact。政策与投票在同一账本事务中落盘，旧政策摘要上的竞争提案自动失效。只读状态完整展示当前政策及摘要。签名、域、时间锁或门槛失败时不修改当前政策；本机文件所有者依然属于系统信任边界。

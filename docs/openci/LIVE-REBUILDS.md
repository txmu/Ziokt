# 实时多节点重建

`POST /v1/rebuilds` / `openci rebuild PIPELINE TASK --nonce REQUEST` 使用原任务的源码摘要、固定 OCI 镜像、参数、资源和产物清单，在当前合格节点上建立独立任务。它不会把一次构建拆散后拼接 sysroot，也不会自动结算 Corium。

## 准入

先使用 `worker-approve` 批准架构、项目、资源及信任池。随后运营者核验工具链/镜像和实际部署位置，保存核验报告，再执行 `openci worker-build-profile profile.json`：

```json
{
  "worker": "builder-a",
  "domain": "physical-host-a",
  "approved_images": ["registry.example/build@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
  "evidence": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

`domain` 必须反映独立宿主机/运营故障域，不能为同一机器上的多个账户填写不同值。报告摘要只是运营者核验记录承诺，不是远程硬件证明。凭证必须分别发放，社区节点不能申请 trusted 权限。

Runner 每次领取前检查本地 OCI 镜像，再以自己的认证身份提交 presence。控制器只采用批准镜像与此次报告的交集，心跳有效 60 秒。重新批准资源会清除镜像批准及 presence；修改镜像批准会清除 presence；运行中的节点必须先 drain 才能修改批准。撤销凭证阻止新心跳，关闭节点立即排除节点。

## 运行状态

- 不足两个不同故障域，或缺少 trusted 验证者：`state: disabled`，不创建副本任务。普通 CI 可以继续工作，禁止把它标记为多节点验证成功。
- 节点恢复后重新调用同一未提交请求，实时重新判断，不需重启控制器。
- 足够节点：`state: submitted`，创建带明确 worker affinity 的副本 DAG；不是已执行或已验证。
- 已提交的 nonce 重试返回原计划，不随在线节点变化悄悄换任务。计划等待/失败后需查看原流水线并显式重试或用新 nonce。
- 节点离线按原 lease/attempt 规则恢复。绑定节点未恢复时不会把任务转给同一宿主机冒充独立副本。
- `/v1/verify` 仍须实际检查原生存储字节、完成任务及相同输出；副本要求当前批准的镜像、不同故障域和 trusted 验证任务。该操作只比较指定两个任务，不代表所有额外副本一致。

两个节点可能共享被植入后门的相同编译器。该机制不能单独排除 trusting-trust 攻击；独立工具链来源、引导链验证、随机复验、审计和可信发布仍是独立要求。在线节点数量不得作为各 Corium 节点自行改变共识规则的依据。

## 数据与回滚

新增 `worker_build_profiles`、`worker_presence` 两张附加表，不改原任务/密钥格式。旧程序不认识带 `worker` affinity 的任务，因此回滚前必须停止新提交、取消/排空副本任务并备份数据库；不能让旧调度器领取这些任务。批准记录不能证明历史上物理节点确实独立。

测试分别记录 SQLite/HTTP 调度验证与 CI 原生 OCI 执行；本地单元测试不冒充多宿主机编译证据。

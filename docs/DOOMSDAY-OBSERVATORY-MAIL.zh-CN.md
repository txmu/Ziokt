# 多节点观测、互联网邮件与 Doomsday 冷恢复

本次增加的是可部署的采集、桥接与恢复链路。拓扑只代表已配置观测者的报告；
`coverage.global_completeness` 保持 `unknown`。签名证明报告来源，不证明报告者没有说谎。
真实独立 VPS、互联网邮件账号及离线介质仍需运营者配置和实测。

## P2P 多节点观测

在现有奋斗 Web 服务配置的 `p2p_explorer` 中增加持久化观测数据库。观测节点示例：

```json
{
  "public": true,
  "observation_db": "/srv/ziokt/observation/outgoing.db",
  "sources": [{
    "id": "native-primary", "kind": "corium", "component": "corium",
    "state_root": "/srv/ziokt/corium", "network_id": "primary",
    "local_id": "REPLACE_WITH_ACTUAL_NATIVE_NODE_ID"
  }],
  "observation_export": {
    "source_id": "native-primary", "key_file": "/srv/ziokt/keys/observer.key"
  },
  "viewers": [{
    "token_file": "/srv/ziokt/keys/collector.token",
    "scopes": ["topology:read", "topology:collect"]
  }]
}
```

`observer.key` 是独立的 32 字节 Ed25519 私钥种子；私钥和 token 文件须为当前用户拥有的
0600 普通文件。通过可信渠道把观察者公钥固定到聚合节点；不要使用第一次收到的公钥自动授信。
导出的图不含地址、公告正文和任意标签。Adapter 快照必须提供真实 `observed_at` 秒级采样时间。
原生节点 ID 必须真实且稳定，`network_id` 必须区分主链、侧链及不同 genesis；同名网络不可混用。

聚合节点示例（增加其他节点时重复 `sources` 条目，使用不同 `id`）：

```json
{
  "public": true,
  "observation_db": "/srv/ziokt/observation/aggregate.db",
  "sources": [{
    "id": "vps-a", "kind": "signed", "component": "corium", "network_id": "primary",
    "public_key": "REPLACE_WITH_64_HEX_OBSERVER_PUBLIC_KEY",
    "url": "https://node-a.example.org/api/p2p/observation",
    "token_file": "/srv/ziokt/keys/node-a-collector.token"
  }]
}
```

采集只访问显式配置的 HTTPS 地址，验证 TLS，禁止重定向和继承代理环境变量。
每次采集附加随机 challenge，验证签名、网络、组件、递增序列和采样时间；序列跨进程重启保留。
以请求往返时间中点估算时钟偏移，同时保留半个 RTT 的不确定度；偏差和证据有效期上限为 5 分钟。
断线时可继续显示尚未过期的已验证缓存，过期后隐藏该来源的图，避免把旧关系当成在线状态。
查看完整原始签名证据使用 `/api/p2p/evidence?source=vps-a`，须另有 `topology:collect`
或 `topology:identities` 权限；公开投影只显示摘要和校准信息。

合并键为组件、网络、节点 ID；不同网络中的同名节点不合并。节点与有向边保存 `observed_by`
来源集合。同一身份的状态以较新观测为准。未经签名的本地来源保持独立命名空间。
当前上限为 24 个配置来源，每份报告 128 节点/256 边，返回图 256 节点/512 边，超出时
`truncated=true`；这是受限观测视图，不声称覆盖互联网所有节点。

页面每 15 秒更新，可暂停；标签页隐藏时暂停轮询。图与列表显示相同节点，支持键盘操作。
“奋斗”导航固定指向 <https://fendou.ziokt.com/>。没有 Shadow6 配置时来源显示不可用，
不再生成虚构的活跃传输节点；静态配置仅显示 `configured`。

## SMTP / IMAP 桥接

使用运营者提供的外部邮件账号进行 SMTP submission 和只读 IMAP 收集，不开放公共 SMTP 中继端口。
支持隐式 TLS 和必需成功的 STARTTLS；不支持明文降级。当前认证方式是用户名/应用专用密码。
需要 OAuth-only 邮件服务时，应由邮件服务提供受控的 SMTP/IMAP 应用密码或独立认证代理。

创建 0600 的 `mail.json`，示例：

```json
{
  "state": "/srv/ziokt/mail",
  "internet": {
    "account": "primary",
    "from_address": "alice@example.org",
    "local_recipient": "alice",
    "allowed_senders": ["REPLACE_WITH_64_HEX_MAIL_SIGNING_PUBLIC_KEY"],
    "secret_file": "/srv/ziokt/keys/mail-account.json",
    "smtp": {"host": "smtp.example.org", "port": 465, "tls": "implicit"},
    "imap": {"host": "imap.example.org", "port": 993, "tls": "implicit", "mailbox": "INBOX"}
  }
}
```

`mail-account.json` 仅包含 `username` 和 `password` 两个字符串字段，模式为 0600。
从地址由账号配置固定；只有列入 `allowed_senders` 的签名身份可以使用账号发送，避免形成开放中继。
不同账号必须使用独立状态目录；账号、From 或本地收件映射变化时拒绝复用已有队列。

```sh
python3 -m ziokt mail --config /srv/ziokt/mail.json send \
  --key /srv/ziokt/keys/mail.key --from-address alice@node.ziokt \
  --to bob@example.net --subject 'Hello' --body-file /srv/ziokt/message.txt
python3 -m ziokt mail --config /srv/ziokt/mail.json internet-flush --limit 10
python3 -m ziokt mail --config /srv/ziokt/mail.json internet-poll --limit 10
python3 -m ziokt mail --config /srv/ziokt/mail.json inbox alice --channel internet
python3 -m ziokt mail --config /srv/ziokt/mail.json internet-status
```

发件先落盘，返回 `queued`，SMTP 接受后才记为 `sent`；这不表示对方已阅读。
暂时性错误采用有界退避，最多 5 次；DATA 阶段断线标记 `uncertain`，不自动重复发送。
崩溃时遗留的发送任务在租约到期后同样转为 `uncertain`。运营者核对邮件服务记录后使用
`internet-resolve MESSAGE_ID --decision sent` 或 `--decision retry` 明确处理。
可用用户级调度器定期运行有界的 flush/poll；命令不会修改主机服务或自动启动常驻进程。

IMAP 使用 UIDVALIDITY + UID 去重，先检查消息大小，按最多 1 MiB 的部分 FETCH 取回正文，
收件落盘后才推进游标。保留原始 MIME；只展示纯文本，HTML 和附件不执行。
Content Fabric 附件通过描述符随信提供，收件人仍需有 Ziokt 访问权限。
互联网邮件的 From 头不是 Ziokt 签名身份证明，收件明确标记 `sender_signature_verified=false`。
TLS 是与邮件服务器之间的传输保护，不是端到端邮件加密。

MCP 新增 `mail_identity`、`mail_internet_status`、`mail_internet_flush`、`mail_internet_poll`。
`mail_identity` 返回客户端持久化公钥与原生地址。各 OAuth 客户端的外部账号须在 MCP 配置的
`mail.clients[CLIENT_ID].internet` 下单独分配；`recipients` 显式列出它可读取的邮箱，
默认只允许读取自身公钥对应的原生邮箱。原生投递使用共享持久化存储，签名身份按客户端隔离。

## Doomsday：加密离线快照和冷恢复

不要只依赖域名、单台 VPS、单个发起者或一份在线数据库。已有的匿名路径切换、Content Fabric
多源修复、Community 胶囊与新节点重加入继续使用；本次补充整个节点显式状态清单的冷恢复。

```json
{
  "schema": "ziokt.doomsday.v1",
  "signing_key_file": "/srv/ziokt/keys/recovery-sign.key",
  "encryption_key_file": "/srv/ziokt/keys/recovery-aes.key",
  "artifacts": [
    {"id": "community/state.db", "path": "/srv/ziokt/community/state.db", "kind": "sqlite"},
    {"id": "mail/internet.db", "path": "/srv/ziokt/mail/internet/internet-mail.db", "kind": "sqlite"},
    {"id": "naming/trust.json", "path": "/srv/ziokt/naming/trust.json", "kind": "file"}
  ],
  "replicas": ["/mnt/offline-a/ziokt", "/mnt/offline-b/ziokt"]
}
```

清单和两把不同的 32 字节密钥均使用 0600。密钥应另行离线保管；丢失 AES 密钥无法恢复。
只包含显式列出的文件，不递归收集用户目录。SQLite 使用 backup API 捕获已提交 WAL 数据并检查一致性。
整体最多 256 个文件/64 MiB；多数据库不是跨服务的分布式原子快照，需要这种一致性时先由运营者协调停写。
Ed25519 绑定清单与摘要，AES-GCM 加密完整归档；每份副本写入后校验摘要。

```sh
python3 -m ziokt doomsday status --config /srv/ziokt/doomsday.json
python3 -m ziokt doomsday snapshot --config /srv/ziokt/doomsday.json --output /srv/ziokt/snapshot-001.zds
python3 -m ziokt --airgap doomsday restore --archive /mnt/offline-b/ziokt/snapshot-DIGEST.zds \
  --encryption-key-file /media/keys/recovery-aes.key --publisher TRUSTED_64_HEX_PUBLIC_KEY \
  --destination /srv/ziokt-recovered
```

恢复先在临时目录中验证全部对象，再发布到不存在的新目录；不会覆盖在线节点身份或启动服务。
链状态仍须通过原生重放与安全 hold 检查后才能激活。副本路径不同不等于独立故障域，须确认实际位于不同介质或节点。
原生 Mail 失败投递可从持久化日志恢复，重试保留原已验证信封并累计次数；不再因停机超过 5 分钟
而丢失已接纳的信件。对新的外部信封仍保留新鲜度与重放检查。

## 验证和范围

`Verified topology, TLS mail and offline survival` 工作流独立验证本次改动；不依赖部署生产服务。
本地测试包括真实回环 HTTPS 采集、TLS SMTP/IMAP 往返、签名与重放拒绝、客户端邮箱隔离、
长期断网恢复、SQLite WAL 冷恢复，以及移动端/桌面端浏览器自动更新和暂停。
现有 Lean 浏览器权限模型继续使用生产 `detail_permitted` 谓词；其对应源码哈希经人工复核更新。
新增采集、邮件协议及备份实现没有宣称已完成 Lean 实现级证明。

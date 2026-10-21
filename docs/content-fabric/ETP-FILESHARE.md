# 原生 ETP FileShare 绑定

状态：真实原生接口及 CI 已配置；本修订尚未取得新增双节点测试的完成结果，不能据此宣称 Library 全部接入。

`ziokt_gateway` 可选 `fileshare` 配置，仅 persistence 构建启用；minimal 构建明确 METHOD_UNSUPPORTED，且不创建存储。与 Forum、Mailbox 分别占用原生 Composite stream 3、4、5，不改变原生 FileShare v1 wire、内容地址或节点身份。

```json
{"fileshare":{"storage":"/private/etp-files","exports":{"manual":"/private/published-manual.txt"}}}
```

路径由运营者配置；IPC 只接受标签、原生内容根、分块序号及已固定公钥的 literal peer。最多 16 个启动导出；配置目录必须私有。原生引擎仍拥有并验证自己的文件/下载状态。此处导出明确为原生公开 share，不通过该入口暴露私有 Library 对象或接受私钥。

接口：`etp.fileshare.list`、`manifest`、`request`、`status`、`chunk`。Python EtpGateway 和可选 ApplicationRouter 只做有界、严格类型调用；路由器必须显式允许这些新方法。

- 原生 v1 保持 16 KiB 分块、1024 块/16 MiB 上限。这里不通过放宽清单/Wire 长度假装支持无限大文件。
- 内容根/叶摘要是原生 BLAKE3 格式，不是 Library SHA-256/Merkle 格式。跨应用导入必须校验实际字节、重新建立规范引用，不能将两种摘要互换。
- `requested`、`downloading`、`timed_out`、`absent` 与 `locally_indexed` 分开；locally_indexed 只说明原生本地索引状态，清单结果 `content_verified:false`。仅 `chunk` 成功代表该块经原生验证器实际读取校验；完整对象仍需导入端完整摘要校验。
- 分块读取与原生网络回复使用同一个 `read_shared_chunk`，检查实际文件大小、目标范围及原生分块摘要；不存在另一套 Gateway 文件服务器。
- 当前原生下载任务/共享索引仍在内存，配置导出在重启时通过原生 share_file 重建；未配置的下载完成索引不承诺跨进程保留。原生 60 秒任务超时及错误原样保留，重试不报告为断点持久化。

Library 的身份授权、签名来源、持久导入和撤回语义仍需完整连接；不能只凭该原生传输接口记为完成。CI 的传输记录也明确 `library_import_verified:false` 和 `dht_discovery_verified:false`。

### Native large-message transport (pending CI)

The engine's unframed stream limit is 1024 bytes, smaller than the native
16 KiB FileShare chunk. The gateway now explicitly selects the native flavor's
v2 message framing: `[2,5,digest32,index:u16be,count:u16be,payload]`.
Payloads are at most 850 bytes, frames at most 888 bytes, and complete original
v1 messages at most 40,000 bytes. Both endpoints must opt into this framing;
this is not negotiated automatically with old peers. Original `new()` callers
retain v1. Oversized unframed sends now return an error at the handle instead
of reporting queue admission and being silently discarded later.

Reassembly is keyed by authenticated source address and BLAKE3 message digest,
with at most 16 assemblies, 30-second expiry, strict index/count/size checks,
and final complete-message digest verification. The bounded 512-frame native
outbox retains frames under channel backpressure. FileShare's original content
hashes, manifest validation, peer checks and chunk verification still apply.
Active downloads have a 300-second lifetime; pending manifests have 60 seconds.
This change requires the real two-node CI transfer before being marked verified.

### Library intake and delegated access (pending native CI)

`library.etp.begin`, `step`, `status`, and `cancel` are shared HTTP/MCP operations.
The authenticated account comes from the transport, never the request body.
Writes require both `library:write` and `content:write`; status requires
`library:read` and ownership of the import. MCP reuses one digest-pinned native
ETP child for generic ETP and content operations with identical settings. Do not
run a separate content service against the same native UDP bind or sled store.

Per-account `native_etp.accounts.ACCOUNT.fileshare` explicitly delegates
`authors` (native author IDs), `topics`, and `peers` (fixed native peer addresses).
Existing Forum/Netnews delegation alone does not grant Library intake rights.
The public, native-signed Forum announcement has schema
`ziokt.etp-library-source.v1`, topic, native BLAKE3 `hash`, `sha256:` digest, size,
MIME, `public: true`, and versioned `book` metadata. The actual signed topic must
match the announcement. Only operator-approved sources can be imported; the
native component retains signing keys and verifies its original signatures.

An immutable source proof and nonce identify each durable intake. `step` reads
bounded chunks from original FileShare, persists resumable Fabric uploads, then
verifies the full declared SHA-256 and Fabric Merkle object before atomically
creating a new Library book. Existing records cannot be overwritten. Queued,
waiting-native, receiving, failed, conflict, cancelled, and complete remain
separate states. Local cancellation discards staged bytes; cancelling a completed
intake is rejected, requiring an explicit Library withdrawal instead. Author,
topic and peer delegation are checked on each step and before chunk writes and
commit. HTTP policy changes require service reload; MCP bindings refresh when
configuration changes. There is no claim of atomic revocation of already-running
calls during a configuration reload.

The native source index is currently in-memory. An ETP restart may require
reacquiring the source; already-verified partial Fabric chunks survive. Native
announcement expiry or lost author authorization fails closed. Source removal
is not a global deletion command; automatic source tombstone synchronization,
DHT discovery, multiple FileShare sources and files above 16 MiB remain incomplete.
Native cache and Fabric use different addressing/encryption; importing creates
an intentional verified local copy, not a claim of physical cross-store dedup.

Migration 9 adds `etp_library_jobs` and an active-record reservation index to the
existing Fabric SQLite database. Back up the database and object directory before
upgrading. For rollback, stop intake and all Fabric writers, cancel or export
unfinished jobs, take another backup, then drop `etp_library_jobs` and delete
migration row 9 in one SQLite transaction before returning to the prior version.
Completed Library records/objects remain ordinary Fabric data; do not delete
objects or other migrations during rollback. Reverting code without dropping the
additive table also preserves normal existing operations.

Local controlled-gateway tests exercise authorization, cancellation, SHA failure,
and actual SQLite/object recovery, not native cryptographic execution.
`ci/etp_fileshare_smoke.py:library_run` is the real two-node signed announcement,
native FileShare and persisted Library acceptance test, executed only by CI.

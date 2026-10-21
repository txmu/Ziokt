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
